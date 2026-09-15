"""Eval tab: voice bake-off (candidates x eval questions, anonymised LLM judges) and retrieval bake-off.

Results live in config.EVAL_RESULTS_PATH keyed by profile sha, candidate, question id and judge, and are
saved after EVERY model call so an interrupted run resumes and the UI replays without loading a model.
Every local model call happens inside gpu.MANAGER.session. The optional Claude judge runs in a side
thread without the GPU lock: it uses no local VRAM and the point of the thread is to overlap with the
local judges.

The qwen25 consistency checker (reply vs retrieved chunks, plan section 4 role map) is always on in the
bake-off and stored under rec["checker"]; it runs right after qwen25's judge pass so the model loads once.

Conditions (docs/PLAN_UNIFIED.md 3.4): a bake-off cell is keyed `cand` for the interview condition (the phase-1
layout, so data/eval_results.json from phase 1 replays unchanged) and `cand@condition` for the persona and
demographic ablations, which get no retrieval and no checker (nothing to check against). `validate_keys` splits
such keys on "@". Every generation and every live check writes one `twin.audit` line.

CLI: python -m twin.pipelines.evals --run [--n 5] [--judges llama31,qwen25] [--no-claude] [--retrieval]
     [--candidates a,b] [--conditions interview,persona,demographic] | --show
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from twin import audit, clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.pipelines import digest
from twin.profile import EvalQA, Profile

CANDIDATES = ["stheno_q4", "stheno_q8", "llama31", "qwen25", "hermes3", "qwen3_8k"]
JUDGES = ("llama31", "qwen25")
RETRIEVAL_INDEXES = ["nomic", "gemma", "lms_nomic"]
SCORE_KEYS = ("factual_agreement", "voice_fidelity", "no_roleplay_artifacts", "overall")
CLAUDE_JUDGE = "claude"

TAB = "eval"
REPLY_TOKENS = 300
JUDGE_TOKENS = 300
JUDGE_TOKENS_RETRY = 600        # retry budget when the first verdict is cut off / unparseable (plan sec. 4 Decide rule)
CHECKER_KEY = "qwen25"          # consistency checker (reply vs retrieved chunks): always on in Eval
CHECKER_TOKENS = 300
CHECKER_TOKENS_RETRY = 600
STHENO_TEMPERATURE = 1.15
OTHER_TEMPERATURE = 0.7

SUMMARY_HEADERS = ["candidate", "replies", "factual", "voice", "artifacts", "overall", "consistent", "overall by judge"]
RETRIEVAL_HEADERS = ["index", "recall@1", "recall@3", "recall@5", "mrr", "embed_ms", "note"]

_RESULTS_LOCK = threading.Lock()  # guards every read-modify-write + save of the shared results dict

_STOPWORDS = frozenset("""
the and for that with this you your are was were have has had not but from they them their what when
where which who whom how why would could should about into over than then there here also just like
very more most some any all one two out off its does did done doing being been because before after
while each other only own same too can will may might must shall our ours yours his her hers him she
cannot tbh lol yeah yes probably think thing things stuff kind sort get got gets getting make makes
made much many lot lots way ways still even ever never always sometimes basically really actually
anyway maybe don doesn didn isn aren wasn weren won wouldn couldn shouldn ll ve
""".split())

_SOURCES_RE = re.compile(r"^\s*sources?:\s*(.+?)\s*$", re.M | re.I)
_WORD_RE = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------------------
# results file
# ---------------------------------------------------------------------------

def _now() -> str:
    """UTC timestamp for the meta block."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_results() -> dict:
    """Read config.EVAL_RESULTS_PATH ({} when missing or unreadable)."""
    p = Path(config.EVAL_RESULTS_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_results(results: dict) -> Path:
    """Write the whole results dict as JSON (indent 2, non-ASCII kept) to config.EVAL_RESULTS_PATH."""
    p = Path(config.EVAL_RESULTS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(results, indent=2, ensure_ascii=False)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        p.write_text(text, encoding="utf-8")  # e.g. the UI holds the file open on Windows
    return p


def _entry(results: dict, profile: Profile) -> dict:
    """Return results[profile.sha], creating the voice/retrieval/meta blocks when absent."""
    e = results.setdefault(profile.sha, {})
    if not isinstance(e, dict):
        e = results[profile.sha] = {}
    e.setdefault("voice", {})
    e.setdefault("retrieval", {})
    meta = e.setdefault("meta", {})
    meta.setdefault("profile_path", profile.path)
    return e


def results_for_current_profile() -> dict:
    """Cached results block for the profile currently on disk ({} if none). No model call."""
    profile = profile_mod.load_profile()
    return load_results().get(profile.sha) or {}


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------

def _ollama_content(resp) -> str:
    """message.content of an Ollama /api/chat response ("" when absent)."""
    if not isinstance(resp, dict):
        return ""
    return ((resp.get("message") or {}).get("content")) or ""


def _lms_content(resp) -> str:
    """choices[0].message.content of an openai ChatCompletion ("" when absent)."""
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        return ""


def parse_json_object(text: str) -> dict | None:
    """Parse a JSON object from model text: whole text first, then the span from the first '{' to the last '}'."""
    if not text:
        return None
    t = text.strip()
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b <= a:
        return None
    try:
        obj = json.loads(t[a:b + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def clamp_scores(parsed: dict | None) -> dict | None:
    """Coerce the four rubric scores to ints clamped to 1..5 (None when any score is missing/non-numeric)."""
    if not isinstance(parsed, dict):
        return None
    out: dict = {}
    for k in SCORE_KEYS:
        try:
            v = float(parsed.get(k))
        except (TypeError, ValueError):
            return None
        out[k] = max(1, min(5, int(round(v))))
    note = parsed.get("note", "")
    out["note"] = "" if note is None else str(note)
    return out


def judge_user_text(question: str, gold: str, style_rules: str, candidate_reply: str) -> str:
    """The judge's user message. Deliberately carries no candidate model name (anonymised grading)."""
    return (
        f"QUESTION:\n{question}\n\nGOLD:\n{gold}\n\nSTYLE RULES:\n{style_rules}\n\n"
        f"CANDIDATE:\n{candidate_reply}"
    )


# ---------------------------------------------------------------------------
# model calls
# ---------------------------------------------------------------------------

def precompute_retrieval(profile: Profile, questions: Iterable[EvalQA], index_key: str = "nomic",
                         k: int = 5) -> dict[str, list[dict]]:
    """Retrieve context chunks for every eval question up front with the small embedder, before any big model loads."""
    out: dict[str, list[dict]] = {}
    for q in questions:
        out[q.qid] = index.search_chunks(index_key, q.question, k=k, tab=TAB)
    return out


def candidate_temperature(candidate_key: str) -> float:
    """Stheno keeps its card samplers (1.15); every other candidate runs at 0.7."""
    return STHENO_TEMPERATURE if candidate_key.startswith("stheno") else OTHER_TEMPERATURE


def generate_detail(candidate_key: str, system: str, question: str, name: str = "", tab: str = TAB) -> dict:
    """Generate one candidate reply inside its GPU session; one retry on empty content. Returns {reply, raw, ms}."""
    s = config.spec(candidate_key)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    temperature = candidate_temperature(candidate_key)
    raw = ""
    t0 = time.perf_counter()
    with gpu.MANAGER.session(candidate_key, tab=tab):
        for _ in range(2):
            if s.runtime == "lms":
                resp = clients.lms.chat(candidate_key, messages, temperature=temperature,
                                        max_tokens=REPLY_TOKENS, tab=tab)
                raw = _lms_content(resp)
            else:
                resp = clients.ollama.chat(candidate_key, messages, options={"temperature": temperature},
                                           num_predict=REPLY_TOKENS, tab=tab)
                raw = _ollama_content(resp)
            if raw.strip():
                break
    ms = (time.perf_counter() - t0) * 1000.0
    return {"reply": prompts.postprocess_voice(raw, name), "raw": raw, "ms": round(ms, 1)}


def generate_reply(candidate_key: str, system: str, question: str, name: str = "") -> str:
    """Generate one candidate reply and return the post-processed text."""
    return generate_detail(candidate_key, system, question, name)["reply"]


def judge_reply(judge_key: str, question: str, gold: str, style_rules: str, candidate_reply: str,
                tab: str = TAB) -> dict:
    """Score an anonymised reply with a local judge (format=JUDGE_SCHEMA, temp 0); one retry on bad JSON, then {error}."""
    messages = [
        {"role": "system", "content": prompts.JUDGE_SYSTEM},
        {"role": "user", "content": judge_user_text(question, gold, style_rules, candidate_reply)},
    ]
    content = ""
    with gpu.MANAGER.session(judge_key, tab=tab):
        # temperature 0 is greedy, so an identical retry would reproduce the failure: the realistic failure
        # with a grammar-constrained format is truncation, so the one retry gets a bigger token budget.
        for num_predict in (JUDGE_TOKENS, JUDGE_TOKENS_RETRY):
            resp = clients.ollama.chat(judge_key, messages, format=prompts.JUDGE_SCHEMA,
                                       options={"temperature": 0}, num_predict=num_predict, tab=tab)
            content = _ollama_content(resp)
            scores = clamp_scores(parse_json_object(content))
            if scores is not None:
                return scores
    return {"error": "invalid judge JSON", "raw": content[:300]}


def checker_user_text(chunks: list[dict], reply: str) -> str:
    """The checker's user message: numbered '[i] (title) text' context lines then the reply (same shape as Ask)."""
    lines = []
    for i, c in enumerate(chunks or [], 1):
        title = c.get("title") or c.get("id", "")
        lines.append(f"[{i}] ({title}) {(c.get('text') or '').strip()}")
    ctx = "\n".join(lines) if lines else "(nothing retrieved)"
    return f"CONTEXT:\n{ctx}\n\nREPLY:\n{reply}"


def _str_list(v) -> list[str]:
    """Coerce a JSON value to a list of strings ([] when it is not a list)."""
    return [str(x) for x in v] if isinstance(v, list) else []


def check_reply(reply: str, chunks: list[dict], tab: str = TAB) -> dict:
    """Consistency-check a reply against its retrieved chunks with qwen25 (format=CHECKER_SCHEMA, temp 0).

    One retry with a bigger budget when the verdict is cut off (done_reason 'length') or unparseable.
    Returns {consistent, unsupported_claims, contradictions} or {consistent: None, error}; never raises."""
    messages = [
        {"role": "system", "content": prompts.CHECKER_SYSTEM},
        {"role": "user", "content": checker_user_text(chunks, reply)},
    ]
    content, parsed = "", None
    try:
        with gpu.MANAGER.session(CHECKER_KEY, tab=tab):
            for num_predict in (CHECKER_TOKENS, CHECKER_TOKENS_RETRY):
                resp = clients.ollama.chat(CHECKER_KEY, messages, format=prompts.CHECKER_SCHEMA,
                                           options={"temperature": 0}, num_predict=num_predict, tab=tab)
                content = _ollama_content(resp)
                parsed = parse_json_object(content)
                if parsed is not None and isinstance(parsed.get("consistent"), bool):
                    break
    except Exception as e:  # noqa: BLE001
        return {"consistent": None, "error": f"{type(e).__name__}: {e}"[:300]}
    if not parsed or not isinstance(parsed.get("consistent"), bool):
        return {"consistent": None, "error": f"unparseable checker output: {content.strip()[:120]!r}"}
    return {"consistent": parsed["consistent"], "unsupported_claims": _str_list(parsed.get("unsupported_claims")),
            "contradictions": _str_list(parsed.get("contradictions"))}


def claude_judge(question: str, gold: str, style_rules: str, candidate_reply: str, tab: str = TAB) -> dict:
    """Score with Claude when ANTHROPIC_API_KEY is available; {error} otherwise. Never logs the key."""
    if not clients.anthropic_client.available():
        return {"error": "anthropic unavailable"}
    try:
        text = clients.anthropic_client.chat(
            system=prompts.JUDGE_SYSTEM + " Output JSON only.",
            messages=[{"role": "user", "content": judge_user_text(question, gold, style_rules, candidate_reply)}],
            tab=tab,
        )
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}
    scores = clamp_scores(parse_json_object(text or ""))
    return scores if scores is not None else {"error": "invalid judge JSON", "raw": (text or "")[:300]}


# ---------------------------------------------------------------------------
# voice bake-off
# ---------------------------------------------------------------------------

def _has_score(rec: dict, judge: str) -> bool:
    """True when rec already holds a non-error score from this judge (error entries are retried on resume)."""
    sc = (rec.get("judges") or {}).get(judge)
    return isinstance(sc, dict) and "error" not in sc


def _claude_worker(results: dict, entry: dict, candidates: list[str], questions: list[EvalQA],
                   style_rules: str) -> None:
    """Side thread: score every generated reply with Claude under judges['claude'], saving after each call."""
    for cand in candidates:
        for q in questions:
            with _RESULTS_LOCK:
                rec = (entry["voice"].get(cand) or {}).get(q.qid)
                if rec is None or _has_score(rec, CLAUDE_JUDGE):
                    continue
                reply = rec.get("reply", "")
            score = claude_judge(q.question, q.answer, style_rules, reply)
            with _RESULTS_LOCK:
                rec.setdefault("judges", {})[CLAUDE_JUDGE] = score
                entry["meta"]["updated"] = _now()
                save_results(results)


def cell_key(candidate_key: str, condition: str = prompts.DEFAULT_CONDITION) -> str:
    """Results key of one candidate x condition: `cand` for interview (phase-1 layout), else `cand@condition`."""
    condition = prompts._condition(condition)
    return candidate_key if condition == "interview" else f"{candidate_key}@{condition}"


def split_cell_key(key: str) -> tuple[str, str]:
    """`cand@condition` -> (cand, condition); a plain key is the interview condition. ValueError on a bad condition."""
    cand, sep, cond = str(key).partition("@")
    if not sep:
        return cand, "interview"
    if cond.strip().lower() not in prompts.CONDITIONS:
        raise ValueError(f"condition {cond!r} in {key!r} must be one of {prompts.CONDITIONS}")
    return cand, cond.strip().lower()


def _conditions(conditions: Iterable[str] | None) -> list[str]:
    """Normalised, de-duplicated condition list (default ["interview"]); ValueError on an unknown condition."""
    out: list[str] = []
    for c in conditions or ():
        c = prompts._condition(c)
        if c not in out:
            out.append(c)
    return out or ["interview"]


def _audit(condition: str, request_text: str, chunk_ids: list[str], model_keys: list[str], ok: bool,
           extra: dict | None = None) -> None:
    """One audit line under tab "eval" (request text reduced to its sha); an audit failure never breaks a run."""
    try:
        audit.record(TAB, condition, request_text, chunk_ids, model_keys, ok, extra=extra)
    except Exception:  # noqa: BLE001
        pass


def validate_keys(candidates: Iterable[str] = (), judges: Iterable[str] = ()) -> None:
    """Raise ValueError (naming the key) before any model session when a key cannot play its role.

    Candidates must be local chat models (runtime ollama/lms) and may carry a `@condition` suffix (a results
    cell key, condition one of prompts.CONDITIONS); judges must be Ollama chat models."""
    for key in candidates:
        cand, _condition = split_cell_key(key)
        s = config.MODELS.get(cand)
        if s is None or s.kind != "chat" or s.runtime not in ("ollama", "lms"):
            raise ValueError(f"candidate {key!r} must be a local (ollama/lms) chat model key")
    for key in judges:
        s = config.MODELS.get(key)
        if s is None or s.kind != "chat" or s.runtime != "ollama":
            raise ValueError(f"judge {key!r} must be an Ollama chat model key")


def _has_checker(rec: dict) -> bool:
    """True when rec already holds a non-error checker verdict (error entries are retried on resume)."""
    ck = rec.get("checker")
    return isinstance(ck, dict) and ck.get("consistent") is not None


def run_voice_bakeoff(n_questions: int = 5, judges: Iterable[str] = JUDGES, use_claude: bool | None = None,
                      candidates: Iterable[str] | None = None, progress: Callable[[str], None] | None = None,
                      index_key: str = "nomic", use_checker: bool = True,
                      conditions: Iterable[str] = ("interview",)) -> dict:
    """Candidate-outer generation (each model loads once and answers every condition while loaded), then
    judge-outer scoring, then the qwen25 consistency checker on the interview cells (run while qwen25 is loaded
    as a judge, so no extra model swap); resumes from the cache.

    Cells are keyed `cell_key(cand, condition)`: `cand` for interview (so phase-1 results replay unchanged),
    `cand@condition` otherwise. Retrieval is precomputed for interview cells only; the other conditions use
    prompts.build_voice_system(profile, digest, [], condition=condition) and are never checked.
    Returns results[profile.sha]. use_claude=None means "when the Anthropic key is available"."""
    say = progress or (lambda _s: None)
    profile = profile_mod.load_profile()
    dg = digest.load_digest()
    questions = list(profile.eval[:max(0, int(n_questions))])
    raw = list(candidates) if candidates else list(CANDIDATES)
    conds = _conditions(conditions)
    judge_keys = list(judges) if judges else []
    validate_keys(raw, judge_keys + ([CHECKER_KEY] if use_checker else []))
    # a plain candidate key runs under every requested condition; a results cell key (`cand@condition`)
    # is exactly that one cell, so stored keys can be passed back in (never reaching config.spec unsplit)
    cells: list[tuple[str, str]] = []
    for key in raw:
        cand, cond = split_cell_key(key)
        for cell in ([(cand, cond)] if "@" in key else [(cand, c) for c in conds]):
            if cell not in cells:
                cells.append(cell)
    cands = list(dict.fromkeys(cand for cand, _c in cells))
    cell_keys = [cell_key(cand, cond) for cand, cond in cells]

    results = load_results()
    with _RESULTS_LOCK:
        entry = _entry(results, profile)
        entry["meta"].update({"profile_path": profile.path, "n_questions": len(questions), "updated": _now()})

    # cells that still need model work; retrieval runs only for the interview questions those cells reference
    def _rec(key: str, qid: str) -> dict:
        return (entry["voice"].get(key) or {}).get(qid) or {}

    need_reply = {(cand, cond, q.qid) for cand, cond in cells for q in questions
                  if "reply" not in _rec(cell_key(cand, cond), q.qid)}
    need_check = {(cand, q.qid) for cand, cond in cells for q in questions
                  if use_checker and cond == "interview" and not _has_checker(_rec(cand, q.qid))}
    need_qids = [q for q in questions
                 if any((c, "interview", q.qid) in need_reply or (c, q.qid) in need_check for c in cands)]
    retrieval: dict[str, list[dict]] = {}
    systems: dict[tuple[str, str], str] = {}
    if need_qids:
        say(f"retrieval: precomputing context for {len(need_qids)} questions with {index_key}")
        retrieval = precompute_retrieval(profile, need_qids, index_key=index_key)
        for q in need_qids:
            systems[("interview", q.qid)] = prompts.build_voice_system(profile, dg, retrieval.get(q.qid, []))
    for cond in dict.fromkeys(cond for _cand, cond in cells):
        if cond != "interview":
            system = prompts.build_voice_system(profile, dg, [], condition=cond)
            for q in questions:
                systems[(cond, q.qid)] = system

    # phase 1: generation, candidate-outer so every model loads exactly once (all conditions while loaded)
    total = len(cells) * len(questions)
    done = 0
    for cand, cond in cells:
        key = cell_key(cand, cond)
        voice_c = entry["voice"].setdefault(key, {})
        for q in questions:
            done += 1
            if (cand, cond, q.qid) not in need_reply:
                continue
            say(f"[{done}/{total}] generate {key} {q.qid}")
            chunks = retrieval.get(q.qid, []) if cond == "interview" else []
            ok = False
            try:
                detail = generate_detail(cand, systems[(cond, q.qid)], q.question, profile.name)
                ok = True
            finally:
                _audit(cond, q.question, [c.get("id", "") for c in chunks], [cand], ok,
                       {"qid": q.qid, "step": "generate"})
            with _RESULTS_LOCK:
                old = voice_c.get(q.qid) or {}
                voice_c[q.qid] = {**detail, "judges": old.get("judges") or {}}
                entry["meta"]["updated"] = _now()
                save_results(results)

    def _checker_phase() -> None:
        """Phase 4: consistency-check every interview reply that lacks a verdict, saving after each call."""
        n = len(need_check)
        for i, (cand, qid) in enumerate(sorted(need_check, key=lambda cq: (cands.index(cq[0]), cq[1])), 1):
            with _RESULTS_LOCK:
                rec = (entry["voice"].get(cand) or {}).get(qid)
                if rec is None or "reply" not in rec:
                    continue
                reply = rec.get("reply", "")
            say(f"[{i}/{n}] checker {CHECKER_KEY} on {cand} {qid}")
            verdict = check_reply(reply, retrieval.get(qid, []))
            with _RESULTS_LOCK:
                rec["checker"] = verdict
                entry["meta"]["updated"] = _now()
                save_results(results)

    # phase 2: Claude ceiling judge in a side thread (no GPU, no GPU lock), joined at the end
    thread: threading.Thread | None = None
    want_claude = clients.anthropic_client.available() if use_claude is None else bool(use_claude)
    if want_claude:
        if clients.anthropic_client.available():
            thread = threading.Thread(target=_claude_worker, name="eval-claude-judge", daemon=True,
                                      args=(results, entry, cell_keys, questions, profile.style_rules))
            thread.start()
            say("claude judge running in a side thread")
        else:
            say("claude judge requested but ANTHROPIC_API_KEY / anthropic package unavailable; skipping")

    # phase 3: local judges, judge-outer so each judge loads once
    total = len(judge_keys) * len(cells) * len(questions)
    done = 0
    for judge in judge_keys:
        for cand, cond in cells:
            key = cell_key(cand, cond)
            for q in questions:
                done += 1
                with _RESULTS_LOCK:
                    rec = (entry["voice"].get(key) or {}).get(q.qid)
                    if rec is None or _has_score(rec, judge):
                        continue
                    reply = rec.get("reply", "")
                say(f"[{done}/{total}] judge {judge} on {key} {q.qid}")
                score = judge_reply(judge, q.question, q.answer, profile.style_rules, reply)
                with _RESULTS_LOCK:
                    rec.setdefault("judges", {})[judge] = score
                    entry["meta"]["updated"] = _now()
                    save_results(results)
        if judge == CHECKER_KEY and use_checker:
            _checker_phase()  # qwen25 is loaded right now: no extra swap
    if use_checker and CHECKER_KEY not in judge_keys:
        _checker_phase()

    if thread is not None:
        thread.join()
        say("claude judge finished")
    return entry


def live_one(candidate_key: str, qid: str | None = None, judge_key: str | None = "llama31",
             index_key: str = "nomic", use_checker: bool = True,
             condition: str = prompts.DEFAULT_CONDITION) -> dict:
    """One candidate x one eval question (retrieve, generate, judge, qwen25 consistency check) for the live demo
    button; not cached. The checker is always on in Eval (plan role map); use_checker=False skips it. Outside
    the interview condition there is no retrieval (no embed call) and no checker (nothing to check against)."""
    condition = prompts._condition(condition)
    validate_keys([candidate_key], [judge_key] if judge_key else [])
    profile = profile_mod.load_profile()
    dg = digest.load_digest()
    if not profile.eval:
        raise ValueError("profile has no Eval questions")
    q = next((x for x in profile.eval if x.qid == qid), profile.eval[0]) if qid else profile.eval[0]
    chunks: list[dict] = []
    models = [candidate_key]
    ok = False
    try:
        if condition == "interview":
            chunks = index.search_chunks(index_key, q.question, k=5, tab=TAB)
        system = prompts.build_voice_system(profile, dg, chunks, condition=condition)
        detail = generate_detail(candidate_key, system, q.question, profile.name)
        score = None
        if judge_key:
            models.append(judge_key)
            score = judge_reply(judge_key, q.question, q.answer, profile.style_rules, detail["reply"])
        checker = None
        if use_checker and condition == "interview":
            models.append(CHECKER_KEY)
            checker = check_reply(detail["reply"], chunks)
        ok = True
    finally:
        _audit(condition, q.question, [c.get("id", "") for c in chunks], models, ok, {"qid": q.qid, "step": "live"})
    return {"qid": q.qid, "question": q.question, "gold": q.answer, "candidate": candidate_key,
            **detail, "judge": judge_key, "score": score, "checker": checker, "condition": condition}


# ---------------------------------------------------------------------------
# retrieval bake-off
# ---------------------------------------------------------------------------

def lexical_words(text: str) -> set[str]:
    """Lowercase word set of a text: letters/digits only, at least 3 chars, stopwords removed."""
    return {w for w in _WORD_RE.findall((text or "").lower()) if len(w) >= 3 and w not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two sets (0.0 when both are empty)."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(gold: set[str], chunk: set[str]) -> float:
    """Fraction of the gold words present in the chunk (0.0 when gold is empty). Unlike Jaccard it does not
    favour short chunks that share one word."""
    return len(gold & chunk) / len(gold) if gold else 0.0


def ground_truth_chunk(answer: str, lookup: dict[str, dict]) -> str | None:
    """Chunk id a gold answer 'comes from': an explicit 'Sources:' id when present, else the chunk containing the
    largest fraction of the answer's words (ties broken by Jaccard)."""
    answer = answer or ""
    m = _SOURCES_RE.search(answer)
    if m:
        for cid in re.split(r"[,;|]", m.group(1)):
            if cid.strip() in lookup:
                return cid.strip()
        answer = _SOURCES_RE.sub("", answer)
    gold = lexical_words(answer)
    if not gold:
        return None
    best, best_score = None, (0.0, 0.0)
    for cid, chunk in lookup.items():
        words = lexical_words((chunk or {}).get("text", ""))
        score = (containment(gold, words), jaccard(gold, words))
        if score > best_score:
            best, best_score = cid, score
    return best


def _retrieval_summary(per: list[dict]) -> dict:
    """recall@1/3/5, MRR and mean latency over per-question records (questions without a ground truth are skipped)."""
    scored = [p for p in per if p.get("gt") is not None]
    n = len(scored)

    def recall(nn: int) -> float:
        """Fraction of ground-truthed questions whose chunk ranked within the top nn."""
        return round(sum(1 for p in scored if p.get("rank") is not None and p["rank"] <= nn) / n, 4) if n else 0.0

    mrr = round(sum(1.0 / p["rank"] for p in scored if p.get("rank")) / n, 4) if n else 0.0
    ms = round(sum(p.get("ms", 0.0) for p in per) / len(per), 1) if per else 0.0
    return {"recall@1": recall(1), "recall@3": recall(3), "recall@5": recall(5), "mrr": mrr,
            "embed_ms_mean": ms, "n": n, "per_question": per}


def run_retrieval_bakeoff(k: int = 5, indexes: Iterable[str] | None = None,
                          progress: Callable[[str], None] | None = None) -> dict:
    """Score every index on every eval question (lexical-overlap ground truth); saves under results[sha]['retrieval']."""
    say = progress or (lambda _s: None)
    profile = profile_mod.load_profile()
    lookup = index.chunk_lookup() or {c.id: asdict(c) for c in profile.chunks}
    questions = list(profile.eval)
    gts = {q.qid: ground_truth_chunk(q.answer, lookup) for q in questions}

    results = load_results()
    with _RESULTS_LOCK:
        entry = _entry(results, profile)
        entry["meta"].update({"profile_path": profile.path, "n_retrieval_questions": len(questions),
                              "updated": _now()})

    for ik in list(indexes) if indexes else list(RETRIEVAL_INDEXES):
        per: list[dict] = []
        say(f"retrieval bake-off: {ik}")
        try:
            for q in questions:
                t0 = time.perf_counter()
                hits = index.search_chunks(ik, q.question, k=k, tab=TAB)
                ms = (time.perf_counter() - t0) * 1000.0
                ids = [h.get("id") for h in hits]
                gt = gts[q.qid]
                rank = (ids.index(gt) + 1) if gt in ids else None
                per.append({"qid": q.qid, "gt": gt, "top": ids, "rank": rank, "ms": round(ms, 1)})
                with _RESULTS_LOCK:
                    entry["retrieval"][ik] = _retrieval_summary(per)
                    entry["meta"]["updated"] = _now()
                    save_results(results)
        except Exception as e:  # noqa: BLE001  (e.g. the index file is not built)
            with _RESULTS_LOCK:
                entry["retrieval"][ik] = {**_retrieval_summary(per), "error": f"{type(e).__name__}: {e}"[:300]}
                entry["meta"]["updated"] = _now()
                save_results(results)
            say(f"retrieval bake-off: {ik} failed: {type(e).__name__}")
    return entry["retrieval"]


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

def _mean(xs: list) -> float | None:
    """Arithmetic mean rounded to 2 decimals (None for an empty list)."""
    return round(sum(xs) / len(xs), 2) if xs else None


def _judge_order(names: Iterable[str]) -> list[str]:
    """Stable display order: default local judges, then claude, then anything else as seen."""
    seen = list(dict.fromkeys(names))
    pri = list(JUDGES) + [CLAUDE_JUDGE]
    return [j for j in pri if j in seen] + [j for j in seen if j not in pri]


def summary_rows(results_for_sha: dict | None) -> list[list]:
    """One row per candidate: [candidate, n_replies, factual, voice, artifacts, overall, consistent, 'judge: x.x | ...'].

    `consistent` is the fraction of checked replies the qwen25 checker found consistent (None when none checked)."""
    voice = (results_for_sha or {}).get("voice") or {}
    if not isinstance(voice, dict):
        return []
    order = [c for c in CANDIDATES if c in voice] + [c for c in voice if c not in CANDIDATES]
    rows: list[list] = []
    for cand in order:
        recs = [r for r in (voice.get(cand) or {}).values() if isinstance(r, dict) and "reply" in r]
        pooled: dict[str, list] = {k: [] for k in SCORE_KEYS}
        per_judge: dict[str, list] = {}
        for r in recs:
            for judge, sc in (r.get("judges") or {}).items():
                if not isinstance(sc, dict) or "error" in sc:
                    continue
                for k in SCORE_KEYS:
                    if isinstance(sc.get(k), (int, float)):
                        pooled[k].append(sc[k])
                if isinstance(sc.get("overall"), (int, float)):
                    per_judge.setdefault(judge, []).append(sc["overall"])
        by_judge = " | ".join(f"{j}: {_mean(per_judge[j]):.1f}" for j in _judge_order(per_judge) if per_judge[j])
        verdicts = [r["checker"]["consistent"] for r in recs
                    if isinstance(r.get("checker"), dict) and isinstance(r["checker"].get("consistent"), bool)]
        rows.append([cand, len(recs), _mean(pooled["factual_agreement"]), _mean(pooled["voice_fidelity"]),
                     _mean(pooled["no_roleplay_artifacts"]), _mean(pooled["overall"]),
                     _mean([1.0 if v else 0.0 for v in verdicts]), by_judge])
    return rows


def retrieval_rows(results_for_sha: dict | None) -> list[list]:
    """One row per index: [index, recall@1, recall@3, recall@5, mrr, embed_ms_mean, note]."""
    ret = (results_for_sha or {}).get("retrieval") or {}
    if not isinstance(ret, dict):
        return []
    order = [k for k in RETRIEVAL_INDEXES if k in ret] + [k for k in ret if k not in RETRIEVAL_INDEXES]
    rows: list[list] = []
    for ik in order:
        r = ret.get(ik) or {}
        if not isinstance(r, dict):
            r = {}
        rows.append([ik, r.get("recall@1"), r.get("recall@3"), r.get("recall@5"), r.get("mrr"),
                     r.get("embed_ms_mean"), r.get("error", "")])
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt(v) -> str:
    """Cell formatter for the CLI tables."""
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _print_table(headers: list[str], rows: list[list]) -> None:
    """Print an aligned plain-text table."""
    cells = [[str(h) for h in headers]] + [[_fmt(v) for v in row] for row in rows]
    widths = [max(len(r[i]) if i < len(r) else 0 for r in cells) for i in range(len(headers))]
    for r in cells:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


def print_tables(entry: dict) -> None:
    """Print the voice and retrieval tables for one results block."""
    print("\nVoice bake-off")
    rows = summary_rows(entry)
    _print_table(SUMMARY_HEADERS, rows) if rows else print("(no cached voice results)")
    print("\nRetrieval bake-off")
    rows = retrieval_rows(entry)
    _print_table(RETRIEVAL_HEADERS, rows) if rows else print("(no cached retrieval results)")


def _csv(s: str) -> list[str]:
    """Split a comma-separated CLI value into stripped, non-empty items."""
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (see module docstring). --show never touches a model server."""
    ap = argparse.ArgumentParser(prog="python -m twin.pipelines.evals")
    ap.add_argument("--run", action="store_true", help="run the voice bake-off (resumes from the cache)")
    ap.add_argument("--show", action="store_true", help="print the cached tables for the current profile")
    ap.add_argument("--n", type=int, default=5, help="number of eval questions (default 5)")
    ap.add_argument("--judges", default=",".join(JUDGES), help="comma-separated local judge keys")
    ap.add_argument("--no-claude", action="store_true", help="never call the Claude judge")
    ap.add_argument("--retrieval", action="store_true", help="also run the retrieval bake-off")
    ap.add_argument("--candidates", default="", help="comma-separated candidate keys (default: all six)")
    ap.add_argument("--conditions", default="interview",
                    help="comma-separated conditions to generate under: demographic, persona, interview "
                         "(default interview; the ablations are cached as cand@condition)")
    args = ap.parse_args(argv)

    if not args.run and not args.show:
        ap.print_help()
        return 0

    if args.run:
        judges = _csv(args.judges)
        cands = _csv(args.candidates) or None
        try:
            validate_keys(cands or CANDIDATES, judges)
            conds = _conditions(_csv(args.conditions))
        except ValueError as e:
            ap.error(f"{e}; choose from {sorted(config.MODELS)} / {prompts.CONDITIONS}")
        try:
            entry = run_voice_bakeoff(n_questions=args.n, judges=judges,
                                      use_claude=False if args.no_claude else None,
                                      candidates=cands, progress=lambda s: print(s, flush=True),
                                      conditions=conds)
            if args.retrieval:
                # run_retrieval_bakeoff reloads and saves its own results dict; copy its block into the
                # voice entry so print_tables shows the retrieval rows of this run, not a stale "(none)".
                entry["retrieval"] = run_retrieval_bakeoff(progress=lambda s: print(s, flush=True))
        finally:
            for line in gpu.MANAGER.free_all():
                print(line)
        print_tables(entry)
        print(f"\nresults: {config.EVAL_RESULTS_PATH}")
        return 0

    profile = profile_mod.load_profile()
    entry = load_results().get(profile.sha) or {}
    print(f"profile: {profile.path} (sha {profile.sha[:12]})")
    if not entry:
        print("no cached results for this profile; run with --run")
    print_tables(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
