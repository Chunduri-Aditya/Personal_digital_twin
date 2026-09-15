"""Items pipeline (docs/PLAN_UNIFIED.md 3.5, docs/research/D4): the frozen item bank, the self-report answer waves,
the twin run per condition and the retest-normalised scoring.

Bank: data/items/bank.json (IPIP-50, GSS, games, gold). Gold item text is overridden by the current profile's Eval
question with the same Q-id; items carrying an "excluded" key and gold items whose question matches the politics
regex (docs/items_licensing.md section 3) are skipped and reported. Nothing from the profile's Eval answers, the
Changelog or the self answers ever reaches a twin-facing prompt: the gold answer goes only to the judges.

Twin run (`run_items`): model-outer order so the GPU loads at most four big models: retrieval for every item under
the interview condition with the LM Studio nomic index (embedder only, cached in memory) -> qwen3-8b-8k answers every
closed item for every condition through a per-item JSON schema (temperature 0.2, num_predict 80, one retry on invalid
JSON) -> Stheno Q4 answers the open (gold) items -> llama3.1 judges -> qwen2.5 judges. data/items/twin_answers.json
is written after EVERY call ({sha: {condition: {item_id: cell}, "meta": {...}}}) so a run resumes; cells already
present are skipped. The answer distribution per condition and instrument is reported so enum collapse is visible.

Scoring (`score`): ground truth = wave 2 when present else wave 1; the retest denominator (wave 1 vs wave 2) only
when both exist, otherwise every normalised cell reads "ceiling pending". IPIP per domain (reverse items 6-v): MAE,
Pearson r, acc = 1 - MAE/4; GSS categorical accuracy (invalid answers count as wrong); games MAE and acc = 1 -
MAE/range plus prisoner's-dilemma accuracy; gold = mean judge overall/5. Bootstrap 95% CI over items
(numpy default_rng(seed), n_boot resamples). The decision line says whether interview beats demographic and persona.

CLI: python -m twin.pipelines.items --run --condition all|demographic|persona|interview [--score] [--show] [--no-resume]
     python -m twin.pipelines.items --score        (never touches a model)
     python -m twin.pipelines.items --show
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from twin import audit, clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.pipelines import digest as digest_mod
from twin.pipelines import evals, voice
from twin.profile import Profile
from twin.prompts import CONDITIONS, DEFAULT_CONDITION

TAB = "items"
ITEM_MODEL = "qwen3_8k"            # closed items (JSON schema)
VOICE_KEY = "stheno_q4"            # open items (voice)
JUDGES = ("llama31", "qwen25")
RETRIEVAL_INDEX = "lms_nomic"      # LM Studio embedder: never evicts an Ollama model
RETRIEVAL_K = 5
ITEM_BOOST = {"Decisions": 0.05, "Expert reflections": 0.05, "Reflections": 0.05}
CLOSED_OPTIONS = {"temperature": 0.2}
CLOSED_NUM_PREDICT = 80
OPEN_MAX_TOKENS = 300
OPEN_TEMPERATURE = 1.15

INSTRUMENTS = ("ipip50", "game", "gold", "gss")                     # bank order
INSTRUMENT_LABELS = {"ipip50": "IPIP-50 personality", "game": "Economic games",
                     "gold": "Gold set (the profile's Eval questions)", "gss": "GSS attitudes and behaviours"}
IPIP_DOMAINS = ("E", "A", "C", "N", "O")
IPIP_DOMAIN_LABELS = {"E": "Extraversion", "A": "Agreeableness", "C": "Conscientiousness",
                      "N": "Emotional Stability", "O": "Intellect/Imagination"}
LIKERT_ANCHORS = ["Very Inaccurate", "Moderately Inaccurate", "Neither Accurate Nor Inaccurate",
                  "Moderately Accurate", "Very Accurate"]
LIKERT_RANGE = (1, 5)
CLOSED_TYPES = ("likert5", "categorical", "number", "fraction", "binary")
ANSWER_KEYS = {"likert5": "answer", "categorical": "answer", "number": "give", "fraction": "fraction", "binary": "action"}
# docs/items_licensing.md section 3: a gold item whose (profile-overridden) question matches this is skipped.
POLITICS_RE = re.compile(r"politic|vote|voting|election|party|government|left-wing|right-wing|liberal|conservative",
                         re.I)

SCORE_HEADERS = ["condition", "instrument", "domain", "n", "metric", "value", "ci95", "retest", "normalized"]
CEILING_PENDING = "ceiling pending"
# (instrument, domain, metric) rows the decision line compares across conditions.
DECISION_METRICS = (("ipip50", "all", "acc"), ("ipip50", "all", "r"), ("gss", "all", "accuracy"),
                    ("game", "all", "acc"), ("gold", "all", "judge_overall"))
RETRIEVAL_FLAG_THRESHOLD = 0.5

_LOCK = threading.Lock()   # guards every read-modify-write + save of the twin answers dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# bank
# ---------------------------------------------------------------------------

def load_bank(path=None) -> dict:
    """data/items/bank.json as a dict ({"version", "frozen", "notes", "items": [...]}); config.BANK_PATH at call time."""
    p = Path(config.BANK_PATH if path is None else path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError(f"{p}: expected an object with an 'items' list")
    return data


def gold_qid(item_id: str) -> str:
    """'GOLD_Q-07' -> 'Q-07' (the profile's Eval id)."""
    return item_id[len("GOLD_"):] if str(item_id).startswith("GOLD_") else str(item_id)


def game_name(item_id: str) -> str:
    """'GAME_trust_send' -> 'trust_send' (the D4 game enum value)."""
    return item_id[len("GAME_"):] if str(item_id).startswith("GAME_") else str(item_id)


def _profile_or_none(profile: Profile | None) -> Profile | None:
    if profile is not None:
        return profile
    try:
        return profile_mod.load_profile()
    except Exception:  # noqa: BLE001  (no profile at all: the bank text stands)
        return None


def _bank_split(profile: Profile | None = None) -> tuple[list[dict], list[tuple[str, str]]]:
    """(kept items in bank order, [(id, reason)] skipped). Gold text is overridden from the profile's Eval question of
    the same Q-id (`item["qid"]` added); an item with an "excluded" key, a gold item without an Eval question in the
    profile, and a gold item whose question matches POLITICS_RE are skipped."""
    prof = _profile_or_none(profile)
    evalq = {q.qid: q for q in prof.eval} if prof is not None else {}
    kept: list[dict] = []
    excluded: list[tuple[str, str]] = []
    for raw in load_bank()["items"]:
        item = dict(raw)
        iid = str(item.get("id", ""))
        if "excluded" in item:
            excluded.append((iid, f"excluded: {item['excluded']}"))
            continue
        if item.get("instrument") == "gold":
            qid = gold_qid(iid)
            q = evalq.get(qid)
            if q is not None:
                item["text"] = q.question
            elif prof is not None:
                excluded.append((iid, f"no Eval question {qid} in the profile"))
                continue
            item["qid"] = qid
            if POLITICS_RE.search(item.get("text") or ""):
                excluded.append((iid, "politics (question matches the politics regex)"))
                continue
        kept.append(item)
    return kept, excluded


def bank_items(profile: Profile | None = None) -> list[dict]:
    """Bank items in bank order, gold text overridden by the profile's Eval question, exclusions applied."""
    return _bank_split(profile)[0]


def excluded_items(profile: Profile | None = None) -> list[tuple[str, str]]:
    """[(item_id, reason)] for every bank item `bank_items` skips."""
    return _bank_split(profile)[1]


def items_by_instrument(items: Iterable[dict]) -> dict[str, list[dict]]:
    """{instrument: [items]} in bank order (instruments in first-seen order)."""
    out: dict[str, list[dict]] = {}
    for it in items:
        out.setdefault(str(it.get("instrument", "")), []).append(it)
    return out


def _range(item: dict, default: tuple) -> tuple:
    r = item.get("range")
    if isinstance(r, (list, tuple)) and len(r) == 2:
        return r[0], r[1]
    return default


# ---------------------------------------------------------------------------
# self answers (waves)
# ---------------------------------------------------------------------------

def load_answers(path) -> dict | None:
    """An answer file {"wave", "date", "name", "answers": {id: value}} or None when missing/invalid."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        return None
    return data


def resolve_waves() -> dict:
    """{"wave1": (path, answers|None), "wave2": (path, answers|None), "example": bool}: the real files when
    either real wave exists (the other real wave may still be missing -> None), else both example files (never
    mixed)."""
    real1 = Path(config.SELF_ANSWERS_PATH)
    real2 = Path(config.SELF_ANSWERS_RETEST_PATH)
    if real1.exists() or real2.exists():
        return {"wave1": (real1, load_answers(real1) if real1.exists() else None),
                "wave2": (real2, load_answers(real2) if real2.exists() else None), "example": False}
    ex1 = Path(config.EXAMPLE_SELF_ANSWERS_PATH)
    ex2 = Path(config.EXAMPLE_SELF_ANSWERS_RETEST_PATH)
    return {"wave1": (ex1, load_answers(ex1)), "wave2": (ex2, load_answers(ex2)), "example": True}


def save_answers(wave: int, answers: dict, date: str, name: str) -> Path:
    """Write {"wave", "date", "name", "answers"} to SELF_ANSWERS_PATH (wave 1) or SELF_ANSWERS_RETEST_PATH (wave 2)."""
    w = int(wave)
    if w not in (1, 2):
        raise ValueError(f"wave must be 1 or 2, got {wave!r}")
    p = Path(config.SELF_ANSWERS_PATH if w == 1 else config.SELF_ANSWERS_RETEST_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"wave": w, "date": str(date or ""), "name": str(name or ""), "answers": dict(answers or {})}
    p.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# schemas and answer validation
# ---------------------------------------------------------------------------

def schema_for(item: dict) -> dict:
    """The JSON schema qwen3 must satisfy for one closed item (D4 shapes). ValueError for open items."""
    t = item.get("type")
    iid = str(item.get("id", ""))
    if t == "likert5":
        lo, hi = _range(item, LIKERT_RANGE)
        return {"type": "object",
                "properties": {"item_id": {"type": "string", "enum": [iid]},
                               "answer": {"type": "integer", "minimum": lo, "maximum": hi}},
                "required": ["item_id", "answer"]}
    if t == "categorical":
        return {"type": "object",
                "properties": {"item_id": {"type": "string", "enum": [iid]},
                               "answer": {"type": "string", "enum": list(item.get("options") or [])}},
                "required": ["item_id", "answer"]}
    if t == "number":
        lo, hi = _range(item, (0, 10))
        return {"type": "object",
                "properties": {"game": {"type": "string", "enum": [game_name(iid)]},
                               "give": {"type": "integer", "minimum": lo, "maximum": hi}},
                "required": ["game", "give"]}
    if t == "fraction":
        lo, hi = _range(item, (0, 1))
        return {"type": "object",
                "properties": {"game": {"type": "string", "enum": [game_name(iid)]},
                               "fraction": {"type": "number", "minimum": lo, "maximum": hi}},
                "required": ["game", "fraction"]}
    if t == "binary":
        return {"type": "object",
                "properties": {"game": {"type": "string", "enum": [game_name(iid)]},
                               "action": {"type": "string", "enum": list(item.get("options") or ["cooperate", "defect"])}},
                "required": ["game", "action"]}
    raise ValueError(f"no closed-answer schema for item type {t!r} ({iid})")


def _as_number(v):
    """int/float from an int, float or numeric string; None otherwise (bools rejected)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def coerce_value(item: dict, v):
    """Validate/normalise one answer value for an item: int in range (likert5, number), float in range (fraction),
    a canonical option label (categorical, binary; case/space-insensitive match), stripped text (open). None when
    invalid or empty."""
    t = item.get("type")
    if v is None:
        return None
    if t in ("likert5", "number"):
        lo, hi = _range(item, LIKERT_RANGE if t == "likert5" else (0, 10))
        f = _as_number(v)
        if f is None or not math.isfinite(f) or float(f) != int(f):
            return None
        i = int(f)
        return i if lo <= i <= hi else None
    if t == "fraction":
        lo, hi = _range(item, (0, 1))
        f = _as_number(v)
        if f is None or not math.isfinite(f):
            return None
        f = float(f)
        return f if lo <= f <= hi else None
    if t in ("categorical", "binary"):
        options = list(item.get("options") or (["cooperate", "defect"] if t == "binary" else []))
        if not isinstance(v, str):
            return None
        if v in options:
            return v
        key = " ".join(v.split()).lower()
        for o in options:
            if " ".join(str(o).split()).lower() == key:
                return o
        return None
    if t == "open":
        s = str(v).strip()
        return s or None
    return None


def parse_closed(item: dict, text: str):
    """The validated answer value parsed from qwen3's JSON text (None when unparseable or out of range/enum)."""
    obj = evals.parse_json_object(text or "")
    if obj is None:
        return None
    key = ANSWER_KEYS.get(str(item.get("type")))
    if key is None:
        return None
    return coerce_value(item, obj.get(key))


# ---------------------------------------------------------------------------
# prompts (twin-facing: never the Eval answers, the Changelog or the self answers)
# ---------------------------------------------------------------------------

def ITEM_SYSTEM(name: str, condition: str) -> str:
    return (
        f"You are {name}, filling in a questionnaire about yourself. Answer every item exactly as {name} would, "
        f"using only the material about {name} below (condition: {condition}); when the material does not settle "
        "it, pick the answer most consistent with it. Do not explain. Answer with JSON matching the schema and "
        "nothing else."
    )


def condition_context(profile: Profile, condition: str, chunks: list[dict], digest: str) -> str:
    """demographic: IDENTITY only; persona: IDENTITY + DIGEST; interview: IDENTITY + DIGEST + numbered CONTEXT
    chunks + the profile's Self-ratings."""
    condition = prompts._condition(condition)
    parts = ["IDENTITY:\n" + (profile.identity or "").strip()]
    if condition in ("persona", "interview"):
        parts.append("DIGEST:\n" + ((digest or "").strip() or "(none)"))
    if condition == "interview":
        lines = []
        for i, c in enumerate(chunks or [], 1):
            title = c.get("title") or c.get("id", "")
            lines.append(f"[{i}] ({title}) {(c.get('text') or '').strip()}")
        parts.append("CONTEXT:\n" + ("\n".join(lines) if lines else "(nothing retrieved)"))
        parts.append("SELF-RATINGS:\n" + ((profile.self_ratings or "").strip() or "(none)"))
    return "\n\n".join(parts)


def item_user_text(item: dict) -> str:
    """The user turn for a closed item: the text plus its numbered options / range / payoff, then the JSON reminder."""
    t = item.get("type")
    text = (item.get("text") or "").strip()
    if t == "likert5":
        lo, _hi = _range(item, LIKERT_RANGE)
        anchors = list(item.get("options") or LIKERT_ANCHORS)
        scale = "\n".join(f"{i} = {a}" for i, a in enumerate(anchors, int(lo)))
        body = f"STATEMENT: {text}\nHow accurately does this statement describe you? Answer with one number:\n{scale}"
    elif t == "categorical":
        options = list(item.get("options") or [])
        opts = "\n".join(f"{i}. {o}" for i, o in enumerate(options, 1))
        body = f"QUESTION: {text}\nOPTIONS (answer with the exact option text):\n{opts}"
    elif t == "number":
        lo, hi = _range(item, (0, 10))
        body = f"QUESTION: {text}\nAnswer with a whole number from {lo} to {hi}."
    elif t == "fraction":
        lo, hi = _range(item, (0, 1))
        body = f"QUESTION: {text}\nAnswer with a number from {lo} to {hi}."
    elif t == "binary":
        options = list(item.get("options") or ["cooperate", "defect"])
        body = f"QUESTION: {text}\nOPTIONS: {' or '.join(options)}"
    else:
        body = text
    return body + "\nAnswer with JSON only."


def closed_messages(profile: Profile, condition: str, item: dict, chunks: list[dict], digest: str) -> list[dict]:
    """[system, user] for a closed item under a condition (qwen3-8b-8k with format=schema_for(item))."""
    return [
        {"role": "system", "content": ITEM_SYSTEM(profile.name, prompts._condition(condition)) + "\n\n"
                                      + condition_context(profile, condition, chunks, digest)},
        {"role": "user", "content": item_user_text(item)},
    ]


def open_messages(profile: Profile, condition: str, item: dict, chunks: list[dict], digest: str) -> list[dict]:
    """[system, user] for an open (gold) item: the Ask voice system prompt under the condition, the question as user."""
    return [
        {"role": "system", "content": prompts.build_voice_system(profile, digest, chunks, condition=condition)},
        {"role": "user", "content": (item.get("text") or "").strip()},
    ]


# ---------------------------------------------------------------------------
# twin answers file
# ---------------------------------------------------------------------------

def load_twin_answers() -> dict:
    """config.TWIN_ANSWERS_PATH as a dict ({} when missing/invalid)."""
    try:
        data = json.loads(Path(config.TWIN_ANSWERS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_twin_answers(results: dict) -> Path:
    """Atomic JSON write of the whole twin answers dict (plain write when the replace fails, e.g. the file is open)."""
    p = Path(config.TWIN_ANSWERS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(results, indent=1, ensure_ascii=False)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        p.write_text(text, encoding="utf-8")
    return p


def _entry(results: dict, profile: Profile) -> dict:
    e = results.setdefault(profile.sha, {})
    if not isinstance(e, dict):
        e = results[profile.sha] = {}
    meta = e.setdefault("meta", {})
    meta.setdefault("profile_path", profile.path)
    return e


def _cell(entry: dict, condition: str, item_id: str) -> dict | None:
    c = entry.get(condition)
    if not isinstance(c, dict):
        return None
    cell = c.get(item_id)
    return cell if isinstance(cell, dict) else None


def _needs_answer(cell: dict | None) -> bool:
    """A cell is (re)done when it is missing, has no answer key, or carries an error (retried on resume)."""
    return cell is None or "answer" not in cell or bool(cell.get("error"))


def _has_judge(cell: dict | None, judge: str) -> bool:
    if cell is None:
        return False
    sc = (cell.get("judges") or {}).get(judge)
    return isinstance(sc, dict) and "error" not in sc


def _store(results: dict, entry: dict, condition: str, item_id: str, cell: dict) -> None:
    with _LOCK:
        entry.setdefault(condition, {})[item_id] = cell
        entry["meta"]["updated"] = _now()
        save_twin_answers(results)


# ---------------------------------------------------------------------------
# model calls
# ---------------------------------------------------------------------------

def retrieve_for_item(item: dict, index_key: str = RETRIEVAL_INDEX, k: int = RETRIEVAL_K) -> list[dict]:
    """Top-k chunks for the item text with the section boost (Decisions, Expert reflections, Reflections)."""
    return index.search_chunks(index_key, (item.get("text") or "").strip(), k=k, boost=dict(ITEM_BOOST), tab=TAB)


def _closed_call(item: dict, messages: list[dict]) -> dict:
    """qwen3-8b-8k with format=schema_for(item); one retry on invalid JSON / an Ollama error. Must run inside
    gpu.MANAGER.session(ITEM_MODEL). Returns the cell: {"answer", "raw", "ms", "attempts"} (+ "error")."""
    schema = schema_for(item)
    raw, value, error, attempts = "", None, None, 0
    t0 = time.perf_counter()
    for _ in range(2):
        attempts += 1
        try:
            resp = clients.ollama.chat(ITEM_MODEL, messages, format=schema, options=dict(CLOSED_OPTIONS),
                                       num_predict=CLOSED_NUM_PREDICT, tab=TAB)
        except clients.OllamaError as e:
            raw, error = "", f"ollama: {e}"[:300]
            continue
        raw = evals._ollama_content(resp)
        value = parse_closed(item, raw)
        if value is not None:
            error = None
            break
        error = "empty reply" if not raw.strip() else "invalid or out-of-range JSON answer"
    ms = (time.perf_counter() - t0) * 1000.0
    cell = {"answer": value, "raw": raw[:500], "ms": round(ms, 1), "attempts": attempts}
    if value is None:
        cell["error"] = f"{error} after {attempts} attempts"
    return cell


def _open_call(profile: Profile, messages: list[dict]) -> dict:
    """Stheno Q4 (or the llama3.2:3b fallback) for an open item via voice.reply_in_voice; post-processed."""
    t0 = time.perf_counter()
    raw, key = voice.reply_in_voice(messages, max_tokens=OPEN_MAX_TOKENS, tab=TAB, temperature=OPEN_TEMPERATURE)
    ms = (time.perf_counter() - t0) * 1000.0
    reply = prompts.postprocess_voice(raw, profile.name)
    cell = {"answer": reply, "raw": raw, "ms": round(ms, 1), "voice": key, "judges": {}}
    if not reply.strip():
        cell["error"] = "empty reply"
    return cell


# ---------------------------------------------------------------------------
# distribution report (enum collapse is visible here)
# ---------------------------------------------------------------------------

def distribution_report(entry: dict, items: list[dict], conditions: Iterable[str]) -> list[str]:
    """Per condition: the IPIP likert histogram, the GSS most-common / first-option shares, every game value and the
    gold reply count with the mean judge overall."""
    lines: list[str] = []
    groups = items_by_instrument(items)
    for cond in conditions:
        cells = entry.get(cond) if isinstance(entry.get(cond), dict) else {}

        def ans(iid: str):
            c = cells.get(iid)
            return c.get("answer") if isinstance(c, dict) else None

        lines.append(f"distribution [{cond}]:")
        ip = groups.get("ipip50", [])
        hist: Counter = Counter()
        invalid = 0
        for it in ip:
            v = ans(it["id"])
            if isinstance(v, int) and not isinstance(v, bool):
                hist[v] += 1
            else:
                invalid += 1
        lo, hi = LIKERT_RANGE
        lines.append("  ipip50 likert histogram: " + " ".join(f"{k}:{hist.get(k, 0)}" for k in range(lo, hi + 1))
                     + f" (invalid {invalid} of {len(ip)})")
        gs = groups.get("gss", [])
        labels: Counter = Counter()
        answered = first = 0
        for it in gs:
            v = ans(it["id"])
            if isinstance(v, str):
                answered += 1
                labels[v] += 1
                if (it.get("options") or [None])[0] == v:
                    first += 1
        if answered:
            top_label, top_n = labels.most_common(1)[0]
            lines.append(f"  gss: answered {answered}/{len(gs)}, most common option {top_label!r} x{top_n} "
                         f"({top_n / answered:.0%}), first-option share {first / answered:.0%}")
        else:
            lines.append(f"  gss: answered 0/{len(gs)}")
        gm = groups.get("game", [])
        lines.append("  game: " + (", ".join(f"{game_name(it['id'])}={ans(it['id'])!r}" for it in gm) or "(none)"))
        go = groups.get("gold", [])
        replies = sum(1 for it in go if isinstance(ans(it["id"]), str) and ans(it["id"]).strip())
        per_judge: dict[str, list[float]] = {}
        for it in go:
            c = cells.get(it["id"])
            for judge, sc in ((c or {}).get("judges") or {}).items():
                if isinstance(sc, dict) and isinstance(sc.get("overall"), (int, float)):
                    per_judge.setdefault(judge, []).append(float(sc["overall"]))
        jtxt = ", ".join(f"{j} {sum(v) / len(v):.2f}" for j, v in per_judge.items() if v) or "none yet"
        lines.append(f"  gold: {replies}/{len(go)} replies; mean judge overall: {jtxt}")
    return lines


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def run_items(conditions: Iterable[str] = ("interview",), progress: Callable[[str], None] | None = None,
              profile: Profile | None = None, resume: bool = True) -> dict:
    """Model-outer twin run over every bank item for the given conditions (see the module docstring).

    Returns {"sha", "conditions", "entry" (results[sha]), "report" (distribution lines), "excluded", "calls", "models"}.
    Writes config.TWIN_ANSWERS_PATH after every call; frees the GPU and writes one audit line per condition."""
    say = progress or (lambda _s: None)
    conds: list[str] = []
    for c in conditions or ():
        c = prompts._condition(c)
        if c not in conds:
            conds.append(c)
    if not conds:
        raise ValueError("no conditions given")
    prof = profile if profile is not None else profile_mod.load_profile()
    dg = digest_mod.load_digest()
    items, excluded = _bank_split(prof)
    closed = [it for it in items if it.get("type") in CLOSED_TYPES]
    opened = [it for it in items if it.get("type") == "open"]
    evalq = {q.qid: q for q in prof.eval}

    results = load_twin_answers()
    with _LOCK:
        entry = _entry(results, prof)
        if not resume:
            for c in conds:
                entry[c] = {}
        try:
            bank = load_bank()
            bank_meta = {"bank_version": bank.get("version"), "bank_frozen": bank.get("frozen")}
        except (OSError, ValueError):
            bank_meta = {}
        entry["meta"].update({"profile_path": prof.path, "profile_name": prof.name, "retrieval_index": RETRIEVAL_INDEX,
                              "excluded": [list(x) for x in excluded], "updated": _now(), **bank_meta})
        save_twin_answers(results)
    for c in conds:
        entry.setdefault(c, {})

    models_used: list[str] = []

    def used(key: str) -> None:
        if key and key not in models_used:
            models_used.append(key)

    calls = 0
    ok = False
    report: list[str] = []
    if excluded:
        say("excluded: " + ", ".join(f"{iid} ({why})" for iid, why in excluded))
    try:
        # phase 1: retrieval (embedder only), interview cells that still need an answer
        retrieval: dict[str, list[dict]] = {}
        if "interview" in conds:
            need = [it for it in items if _needs_answer(_cell(entry, "interview", it["id"]))]
            if need:
                say(f"retrieval: {len(need)} items with {RETRIEVAL_INDEX} (k={RETRIEVAL_K})")
                used(index.INDEX_KEYS.get(RETRIEVAL_INDEX, RETRIEVAL_INDEX))
            for i, it in enumerate(need, 1):
                say(f"[{i}/{len(need)}] retrieval {RETRIEVAL_INDEX} {it['id']}")
                retrieval[it["id"]] = retrieve_for_item(it)

        def chunks_for(cond: str, it: dict) -> list[dict]:
            return retrieval.get(it["id"], []) if cond == "interview" else []

        # phase 2: closed items with qwen3-8b-8k, one session for every condition x item
        todo = [(c, it) for c in conds for it in closed if _needs_answer(_cell(entry, c, it["id"]))]
        if todo:
            used(ITEM_MODEL)
            with gpu.MANAGER.session(ITEM_MODEL, tab=TAB):
                for i, (c, it) in enumerate(todo, 1):
                    say(f"[{i}/{len(todo)}] {ITEM_MODEL} {c} {it['id']}")
                    chunks = chunks_for(c, it)
                    cell = _closed_call(it, closed_messages(prof, c, it, chunks, dg))
                    cell["chunk_ids"] = [ch.get("id", "") for ch in chunks]
                    calls += cell.get("attempts", 1)
                    _store(results, entry, c, it["id"], cell)

        # phase 3: open items in the twin's voice
        todo = [(c, it) for c in conds for it in opened if _needs_answer(_cell(entry, c, it["id"]))]
        for i, (c, it) in enumerate(todo, 1):
            say(f"[{i}/{len(todo)}] {VOICE_KEY} {c} {it['id']}")
            chunks = chunks_for(c, it)
            cell = _open_call(prof, open_messages(prof, c, it, chunks, dg))
            cell["chunk_ids"] = [ch.get("id", "") for ch in chunks]
            used(cell.get("voice", VOICE_KEY))
            calls += 1
            _store(results, entry, c, it["id"], cell)

        # phases 4 and 5: judge-outer scoring of every open reply (the gold answer goes to the judge only)
        for judge in JUDGES:
            todo = [(c, it) for c in conds for it in opened
                    if (cl := _cell(entry, c, it["id"])) is not None and isinstance(cl.get("answer"), str)
                    and cl["answer"].strip() and not _has_judge(cl, judge)]
            if todo:
                used(judge)
            for i, (c, it) in enumerate(todo, 1):
                say(f"[{i}/{len(todo)}] judge {judge} {c} {it['id']}")
                cl = _cell(entry, c, it["id"]) or {}
                q = evalq.get(it.get("qid", ""))
                gold = q.answer if q is not None else ""
                score = evals.judge_reply(judge, it["text"], gold, prof.style_rules, cl.get("answer", ""), tab=TAB)
                calls += 1
                with _LOCK:
                    cl.setdefault("judges", {})[judge] = score
                    entry["meta"]["updated"] = _now()
                    save_twin_answers(results)

        report = distribution_report(entry, items, conds)
        for ln in report:
            say(ln)
        with _LOCK:
            entry["meta"]["last_report"] = report
            entry["meta"]["last_run"] = {"conditions": conds, "calls": calls, "models": list(models_used),
                                         "finished": _now()}
            save_twin_answers(results)
        ok = True
    finally:
        try:
            gpu.MANAGER.free_all()
        except Exception:  # noqa: BLE001
            pass
        for c in conds:
            try:
                audit.record(TAB, c, "run", [], models_used, ok, extra={"calls": calls, "resume": bool(resume)})
            except Exception:  # noqa: BLE001
                pass
    return {"sha": prof.sha, "conditions": conds, "entry": entry, "report": report, "excluded": excluded,
            "calls": calls, "models": models_used}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def scored_value(item: dict, v):
    """IPIP item value with the reverse key applied (6 - v for reverse items); None passes through."""
    if v is None:
        return None
    return 6 - v if item.get("reverse") else v


def _answers_of(w) -> dict | None:
    """Answer mapping from a resolve_waves() tuple, an answer document or a plain {id: value} mapping."""
    if w is None:
        return None
    if isinstance(w, tuple):
        w = w[1] if len(w) > 1 else None
    if w is None:
        return None
    if isinstance(w, dict) and isinstance(w.get("answers"), dict):
        return w["answers"]
    return w if isinstance(w, dict) else None


def _path_of(w) -> str | None:
    if isinstance(w, tuple) and w and w[0] is not None:
        return str(w[0])
    return None


def _pairs(items: list[dict], a: dict | None, b: dict | None, transform=None) -> tuple[np.ndarray, np.ndarray]:
    """(x, y) float arrays over the items where both mappings hold a valid value (coerced, transform applied)."""
    xs, ys = [], []
    if a is None or b is None:
        return np.zeros(0), np.zeros(0)
    for it in items:
        va = coerce_value(it, a.get(it["id"]))
        vb = coerce_value(it, b.get(it["id"]))
        if va is None or vb is None:
            continue
        if transform is not None:
            va, vb = transform(it, va), transform(it, vb)
        xs.append(float(va))
        ys.append(float(vb))
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def _pearson_rows(X: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Row-wise Pearson r for (B, n) arrays; nan where a row has zero variance or fewer than 3 items."""
    if X.shape[1] < 3:
        return np.full(X.shape[0], np.nan)
    xm = X - X.mean(axis=1, keepdims=True)
    ym = Y - Y.mean(axis=1, keepdims=True)
    num = (xm * ym).sum(axis=1)
    den = np.sqrt((xm ** 2).sum(axis=1) * (ym ** 2).sum(axis=1))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    return r


def _metric_rows(kind: str, X: np.ndarray, Y: np.ndarray | None, rng_width: float = 1.0) -> np.ndarray:
    """Metric per row of (B, n) arrays: mae, acc (= 1 - mae/width), r, or mean (of X alone)."""
    if kind == "mae":
        return np.abs(X - Y).mean(axis=1)
    if kind == "acc":
        return 1.0 - np.abs(X - Y).mean(axis=1) / float(rng_width)
    if kind == "r":
        return _pearson_rows(X, Y)
    if kind == "mean":
        return X.mean(axis=1)
    raise ValueError(kind)


def _point(kind: str, x: np.ndarray, y: np.ndarray | None, width: float = 1.0) -> float | None:
    if x.size == 0:
        return None
    v = _metric_rows(kind, x[None, :], None if y is None else y[None, :], width)[0]
    return None if not np.isfinite(v) else round(float(v), 4)


def bootstrap_ci(kind: str, x: np.ndarray, y: np.ndarray | None, n_boot: int = 1000, seed: int = 0,
                 width: float = 1.0) -> list[float] | None:
    """95% percentile bootstrap CI over items for one metric (numpy default_rng(seed)); None when undefined."""
    n = int(x.size)
    if n == 0 or n_boot <= 0:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(n_boot), n))
    vals = _metric_rows(kind, x[idx], None if y is None else y[idx], width)
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return None
    return [round(float(np.percentile(finite, 2.5)), 4), round(float(np.percentile(finite, 97.5)), 4)]


def _normalize(value, retest_value, retest: bool):
    if not retest:
        return CEILING_PENDING
    if value is None or retest_value is None or retest_value == 0:
        return None
    return round(float(value) / float(retest_value), 3)


def _row(cond, instrument, domain, n, n_items, metric, value, ci, retest_value, normalized) -> dict:
    return {"condition": cond, "instrument": instrument, "domain": domain, "n": int(n), "n_items": int(n_items),
            "metric": metric, "value": value, "ci95": ci, "retest": retest_value, "normalized": normalized}


def _continuous_rows(cond, instrument, domain, items, twin, truth, w1, w2, retest, width, n_boot, seed,
                     transform=None, metrics=("mae", "r", "acc")) -> list[dict]:
    tx, ty = _pairs(items, twin, truth, transform)
    rx, ry = _pairs(items, w1, w2, transform) if retest else (np.zeros(0), np.zeros(0))
    rows = []
    for m in metrics:
        value = _point(m, tx, ty, width)
        ci = bootstrap_ci(m, tx, ty, n_boot, seed, width)
        rv = _point(m, rx, ry, width) if retest else None
        rows.append(_row(cond, instrument, domain, tx.size, len(items), m, value, ci, rv, _normalize(value, rv, retest)))
    return rows


def _match_vector(items: list[dict], a: dict | None, b: dict | None) -> np.ndarray:
    """1.0 where both hold the same valid option, else 0.0 (an invalid or missing answer counts as wrong)."""
    out = []
    for it in items:
        va = coerce_value(it, (a or {}).get(it["id"]))
        vb = coerce_value(it, (b or {}).get(it["id"]))
        out.append(1.0 if va is not None and vb is not None and va == vb else 0.0)
    return np.asarray(out, dtype=float)


def _categorical_rows(cond, instrument, domain, items, twin, truth, w1, w2, retest, n_boot, seed,
                      metric="accuracy") -> list[dict]:
    tm = _match_vector(items, twin, truth)
    answered = sum(1 for it in items if coerce_value(it, (twin or {}).get(it["id"])) is not None)
    value = _point("mean", tm, None)
    ci = bootstrap_ci("mean", tm, None, n_boot, seed)
    rv = _point("mean", _match_vector(items, w1, w2), None) if retest else None
    return [_row(cond, instrument, domain, answered, len(items), metric, value, ci, rv, _normalize(value, rv, retest))]


def _gold_rows(cond, items, judges_by_item: dict, n_boot, seed) -> list[dict]:
    per_item = []
    for it in items:
        scores = [float(sc["overall"]) / 5.0 for sc in (judges_by_item.get(it["id"]) or {}).values()
                  if isinstance(sc, dict) and isinstance(sc.get("overall"), (int, float))]
        if scores:
            per_item.append(sum(scores) / len(scores))
    x = np.asarray(per_item, dtype=float)
    value = _point("mean", x, None)
    ci = bootstrap_ci("mean", x, None, n_boot, seed)
    return [_row(cond, "gold", "all", x.size, len(items), "judge_overall", value, ci, None, "n/a")]


def score(conditions: Iterable[str] | None = None, waves: dict | None = None, twin: dict | None = None,
          n_boot: int = 1000, seed: int = 0, profile: Profile | None = None) -> dict:
    """Score the cached twin answers against the self answers (no model call).

    `waves`: resolve_waves() shape (default) or {"wave1": answers, "wave2": answers|None}; `twin`: the twin answers
    block for the profile ({condition: {item_id: cell}}, default: the file's entry for the profile sha);
    `conditions`: default = every condition present in `twin`, CONDITIONS order. Returns
    {"sha", "profile_path", "updated", "conditions", "n_boot", "seed", "waves": {...}, "rows": [...], "excluded",
    "decision"}; rows are dicts under SCORE_HEADERS (+ "n_items")."""
    prof = profile if profile is not None else profile_mod.load_profile()
    items, excluded = _bank_split(prof)
    groups = items_by_instrument(items)
    if waves is None:
        waves = resolve_waves()
    w1 = _answers_of(waves.get("wave1"))
    w2 = _answers_of(waves.get("wave2"))
    if w1 is None and w2 is None:
        raise ValueError("no self answers found (data/items/self_answers*.json): fill the Items form first")
    truth = w2 if w2 is not None else w1
    retest = w1 is not None and w2 is not None
    if twin is None:
        twin = load_twin_answers().get(prof.sha) or {}
    conds = [prompts._condition(c) for c in conditions] if conditions else \
        [c for c in CONDITIONS if isinstance(twin.get(c), dict) and twin.get(c)]

    rows: list[dict] = []
    for cond in conds:
        cells = twin.get(cond) if isinstance(twin.get(cond), dict) else {}
        answers = {iid: c.get("answer") for iid, c in cells.items() if isinstance(c, dict)}
        judges = {iid: (c.get("judges") or {}) for iid, c in cells.items() if isinstance(c, dict)}
        ip = groups.get("ipip50", [])
        for domain in IPIP_DOMAINS + ("all",):
            dom_items = [it for it in ip if domain == "all" or it.get("domain") == domain]
            if dom_items:
                rows += _continuous_rows(cond, "ipip50", domain, dom_items, answers, truth, w1, w2, retest,
                                         LIKERT_RANGE[1] - LIKERT_RANGE[0], n_boot, seed, transform=scored_value)
        gs = groups.get("gss", [])
        if gs:
            rows += _categorical_rows(cond, "gss", "all", gs, answers, truth, w1, w2, retest, n_boot, seed)
        gm = groups.get("game", [])
        numeric = [it for it in gm if it.get("type") in ("number", "fraction")]
        for it in numeric:
            lo, hi = _range(it, (0, 1) if it["type"] == "fraction" else (0, 10))
            rows += _continuous_rows(cond, "game", game_name(it["id"]), [it], answers, truth, w1, w2, retest,
                                     float(hi) - float(lo), n_boot, seed, metrics=("mae", "acc"))
        if numeric:
            # family row: mean per-item accuracy (each item on its own range), bootstrapped over the games
            def _acc_vec(a, b):
                out = []
                for it in numeric:
                    va, vb = coerce_value(it, (a or {}).get(it["id"])), coerce_value(it, (b or {}).get(it["id"]))
                    if va is None or vb is None:
                        continue
                    lo_, hi_ = _range(it, (0, 1) if it["type"] == "fraction" else (0, 10))
                    out.append(1.0 - abs(float(va) - float(vb)) / (float(hi_) - float(lo_)))
                return np.asarray(out, dtype=float)
            x = _acc_vec(answers, truth)
            value = _point("mean", x, None)
            rv = _point("mean", _acc_vec(w1, w2), None) if retest else None
            rows.append(_row(cond, "game", "all", x.size, len(numeric), "acc", value,
                             bootstrap_ci("mean", x, None, n_boot, seed), rv, _normalize(value, rv, retest)))
        for it in [it for it in gm if it.get("type") == "binary"]:
            rows += _categorical_rows(cond, "game", game_name(it["id"]), [it], answers, truth, w1, w2, retest,
                                      n_boot, seed)
        go = groups.get("gold", [])
        if go:
            rows += _gold_rows(cond, go, judges, n_boot, seed)

    scores = {
        "sha": prof.sha, "profile_path": prof.path, "updated": _now(), "conditions": conds,
        "n_boot": int(n_boot), "seed": int(seed),
        "waves": {"wave1": _path_of(waves.get("wave1")), "wave2": _path_of(waves.get("wave2")) if w2 is not None else None,
                  "example": bool(waves.get("example", False)), "ground_truth": "wave2" if w2 is not None else "wave1",
                  "retest": retest},
        "rows": rows, "excluded": [list(x) for x in excluded],
    }
    scores["decision"] = decision_line(scores)
    return scores


def _find_row(rows: list[dict], cond: str, instrument: str, domain: str, metric: str) -> dict | None:
    for r in rows:
        if (r.get("condition"), r.get("instrument"), r.get("domain"), r.get("metric")) == (cond, instrument, domain, metric):
            return r
    return None


def decision_line(scores: dict) -> str:
    """'Decision: interview beats demographic and persona on <metrics>: yes|no|partial' plus the retrieval flag when
    the interview GSS accuracy (normalised, or raw while the ceiling is pending) is below 0.5, and a ceiling note."""
    rows = list(scores.get("rows") or [])
    conds = list(scores.get("conditions") or [])
    missing = [c for c in CONDITIONS if c not in conds]
    if missing:
        head = (f"Decision: interview beats demographic and persona: n/a "
                f"(conditions not run yet: {', '.join(missing)})")
    else:
        wins, losses = [], []
        for inst, dom, met in DECISION_METRICS:
            vals = [(_find_row(rows, c, inst, dom, met) or {}).get("value") for c in ("interview", "demographic", "persona")]
            if any(v is None for v in vals):
                continue
            label = f"{inst} {met}"
            (wins if vals[0] > vals[1] and vals[0] > vals[2] else losses).append(label)
        names = wins + losses
        if not names:
            verdict = "n/a (no comparable metrics)"
        elif not losses:
            verdict = "yes"
        elif not wins:
            verdict = "no"
        else:
            verdict = f"partial (yes on {', '.join(wins)}; no on {', '.join(losses)})"
        head = f"Decision: interview beats demographic and persona on {', '.join(names) or 'no metrics'}: {verdict}"
    gss = _find_row(rows, "interview", "gss", "all", "accuracy")
    if gss is not None:
        norm, raw = gss.get("normalized"), gss.get("value")
        if isinstance(norm, (int, float)) and not isinstance(norm, bool):
            if norm < RETRIEVAL_FLAG_THRESHOLD:
                head += (f"; fix retrieval (recall@5) before content (normalized gss accuracy {norm:.2f} "
                         f"< {RETRIEVAL_FLAG_THRESHOLD})")
        elif norm == CEILING_PENDING and isinstance(raw, (int, float)) and raw < RETRIEVAL_FLAG_THRESHOLD:
            head += (f"; fix retrieval (recall@5) before content (raw gss accuracy {raw:.2f} "
                     f"< {RETRIEVAL_FLAG_THRESHOLD}, ceiling pending so the raw value is used)")
    if not (scores.get("waves") or {}).get("retest", False):
        head += " (ceiling pending: no wave-2 retest yet, every normalized cell waits for it)"
    return head


def save_scores(scores: dict) -> Path:
    p = Path(config.ITEM_SCORES_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def load_scores() -> dict | None:
    try:
        data = json.loads(Path(config.ITEM_SCORES_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("rows"), list) else None


def _fmt_num(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
    return str(v)


def summary_rows(scores: dict | None) -> list[list]:
    """Rows under SCORE_HEADERS for the UI / CLI table (ci95 as '[lo, hi]', n as 'answered/total' when they differ)."""
    out: list[list] = []
    for r in (scores or {}).get("rows") or []:
        n, n_items = r.get("n"), r.get("n_items", r.get("n"))
        n_txt = str(n) if n == n_items else f"{n}/{n_items}"
        ci = r.get("ci95")
        ci_txt = f"[{_fmt_num(ci[0])}, {_fmt_num(ci[1])}]" if isinstance(ci, (list, tuple)) and len(ci) == 2 else ""
        out.append([r.get("condition"), r.get("instrument"), r.get("domain"), n_txt, r.get("metric"),
                    _fmt_num(r.get("value")), ci_txt, _fmt_num(r.get("retest")), _fmt_num(r.get("normalized"))])
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_table(headers: list[str], rows: list[list]) -> None:
    cells = [[str(h) for h in headers]] + [["" if v is None else str(v) for v in row] for row in rows]
    widths = [max(len(r[i]) if i < len(r) else 0 for r in cells) for i in range(len(headers))]
    for r in cells:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


def print_scores(scores: dict | None) -> None:
    if not scores or not scores.get("rows"):
        print("(no scores)")
        return
    w = scores.get("waves") or {}
    print(f"ground truth: {w.get('ground_truth')} ({'example' if w.get('example') else 'real'} answers); "
          f"retest: {'yes' if w.get('retest') else 'no (ceiling pending)'}; bootstrap n={scores.get('n_boot')} seed={scores.get('seed')}")
    _print_table(SCORE_HEADERS, summary_rows(scores))
    print(scores.get("decision") or decision_line(scores))


def coverage_lines(entry: dict | None, items: list[dict]) -> list[str]:
    """Per condition: answered / total cells, error cells, judged open replies (for --show and the UI)."""
    lines = []
    for cond in CONDITIONS:
        cells = (entry or {}).get(cond)
        if not isinstance(cells, dict):
            continue
        answered = sum(1 for it in items if (c := cells.get(it["id"])) and c.get("answer") not in (None, ""))
        errors = sum(1 for it in items if (c := cells.get(it["id"])) and c.get("error"))
        judged = sum(1 for it in items if it.get("type") == "open" and (c := cells.get(it["id"]))
                     and all(_has_judge(c, j) for j in JUDGES))
        lines.append(f"{cond}: {answered}/{len(items)} answered, {errors} errors, {judged} open replies judged by both judges")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m twin.pipelines.items")
    ap.add_argument("--run", action="store_true", help="run the twin over the item bank (resumes from the cache)")
    ap.add_argument("--condition", default="interview", choices=["all", *CONDITIONS],
                    help="condition(s) to run (default interview)")
    ap.add_argument("--score", action="store_true", help="score the cached twin answers (no model call)")
    ap.add_argument("--show", action="store_true", help="print the cached scores and coverage (no model call)")
    ap.add_argument("--no-resume", action="store_true", help="redo every cell of the chosen condition(s)")
    ap.add_argument("--n-boot", type=int, default=1000, help="bootstrap resamples (default 1000)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    if not (args.run or args.score or args.show):
        ap.print_help()
        return 0
    conds = list(CONDITIONS) if args.condition == "all" else [args.condition]
    prof = profile_mod.load_profile()
    print(f"profile: {prof.path} ({prof.name}, sha {prof.sha[:12]})")
    if args.run:
        out = run_items(conditions=conds, progress=lambda s: print(s, flush=True), profile=prof,
                        resume=not args.no_resume)
        print(f"run: {out['calls']} model calls, models {', '.join(out['models']) or 'none'}, "
              f"results: {config.TWIN_ANSWERS_PATH}")
    if args.score:
        sc = score(n_boot=args.n_boot, seed=args.seed, profile=prof)
        save_scores(sc)
        print_scores(sc)
        print(f"scores: {config.ITEM_SCORES_PATH}")
    if args.show:
        items = bank_items(prof)
        entry = load_twin_answers().get(prof.sha)
        for ln in coverage_lines(entry, items) or ["no twin answers for this profile; run with --run"]:
            print(ln)
        for ln in ((entry or {}).get("meta") or {}).get("last_report") or []:
            print(ln)
        sc = load_scores()
        if sc and sc.get("sha") == prof.sha:
            print_scores(sc)
        else:
            print("no cached scores for this profile; run with --score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
