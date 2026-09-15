"""Decide pipeline: B1 (yes/no) and B2 (A vs B) predictions with qwen3-8b-8k, then "say it" with Stheno.

Plan section 4 "Decide": retrieve the situation against Decisions/Values/Preferences/Boundaries (plus the
Expert reflections, docs/PLAN_UNIFIED.md 3.3), add the digest, ask qwen3-8b-8k for JSON matching B1_SCHEMA /
B2_SCHEMA at temperature 0.2 with num_predict 600 (1200 on a `length` stop), one retry on empty or invalid
JSON, and render the verdict in the twin's voice with Stheno only when the user clicks "say it" (so the GPU
swap happens only on demand).

Conditions (plan 3.4): `interview` (default) is the phase-1 flow, byte-identical; `persona` skips retrieval and
gives the model IDENTITY + DIGEST; `demographic` skips retrieval and the digest (IDENTITY only). The condition
is stored in the result so `say_it(result)` keeps its signature. Every B1/B2 call that reached the model writes
one `twin.audit` line.

Clients, retrieval and the GPU manager are reached through their module objects (`clients.ollama`,
`clients.lms`, `index.search_chunks`, `index.chunk_lookup`, `gpu.MANAGER`) so tests can monkeypatch them.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from .. import audit, clients, gpu, index, prompts
from .. import profile as profile_mod
from ..config import spec
from . import digest as digest_mod
from . import voice

DECIDE_KEY = "qwen3_8k"
VOICE_KEY = "stheno_q4"
TAB = "decide"
DECISION_SECTIONS = frozenset({"Decisions", "Values", "Preferences", "Boundaries", "Expert reflections",
                               "Reflections"})
DECIDE_BOOST = {"Decisions": 0.05, "Expert reflections": 0.05, "Reflections": 0.05}
CANDIDATES = 24            # chunks pulled from the index before the section filter
NUM_PREDICT = 600
NUM_PREDICT_LONG = 1200    # retry budget when the first answer stopped on `length`
DECIDE_OPTIONS = {"temperature": 0.2}
B1_QUESTION = "QUESTION: Would you do it? Answer yes or no."
B2_QUESTION = "QUESTION: Which would you choose?"

# Anchored: requires the hyphen and word boundaries so 'covid-19' / 'used 4 options' never read as decision ids.
_DECISION_ID_RE = re.compile(r"\bD\s*-\s*0*(\d{1,3})\b", re.I)
_PROFILE_CACHE: dict[str, object] = {"sha": None, "profile": None}


# ---- profile ------------------------------------------------------------------
def get_profile(path: Path | None = None) -> profile_mod.Profile:
    """Return the parsed profile, re-parsing only when the file's sha256 changed since the last call."""
    p = Path(path) if path else profile_mod.resolve_profile_path()
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    cached = _PROFILE_CACHE.get("profile")
    if cached is not None and _PROFILE_CACHE.get("sha") == sha and getattr(cached, "path", "") == str(p):
        return cached
    prof = profile_mod.load_profile(p)
    _PROFILE_CACHE["sha"] = prof.sha
    _PROFILE_CACHE["profile"] = prof
    return prof


def _normalise_decision_id(text: str) -> str | None:
    """'d-3', 'D-03', 'Decisions/D-03', 'D-03: title' -> 'D-3' canonical form; None when no D-NN is present."""
    m = _DECISION_ID_RE.search(str(text))
    return f"D-{int(m.group(1))}" if m else None


def _all_decision_ids(text: str) -> list[str]:
    """Every D-NN in the text in canonical 'D-3' form, in order ('D-3 and D-7' -> ['D-3', 'D-7'])."""
    return [f"D-{int(m.group(1))}" for m in _DECISION_ID_RE.finditer(str(text))]


def _decision_id_map(prof: profile_mod.Profile) -> dict[str, str]:
    """Map canonical 'D-3' forms to the ids as written in the profile ('D-03')."""
    out: dict[str, str] = {}
    for d in prof.decisions:
        canon = _normalise_decision_id(d.id)
        if canon:
            out[canon] = d.id
    return out


def _decision_titles(prof: profile_mod.Profile) -> dict[str, str]:
    """Decision id -> short title as parsed from the profile."""
    return {d.id: d.title for d in prof.decisions}


def _decision_chunks(prof: profile_mod.Profile, decision_ids: list[str]) -> list[dict]:
    """Profile chunk dicts for the given decision ids (order preserved, unknown ids skipped)."""
    by_id = {c.id: c for c in prof.chunks}
    out = []
    for did in decision_ids:
        c = by_id.get(f"Decisions/{did}")
        if c is not None:
            out.append(asdict(c))
    return out


# ---- retrieval and context ----------------------------------------------------
def decision_index_key() -> str:
    """Prefer the LM Studio nomic index: an Ollama embedding call would evict the pre-warmed qwen3-8b-8k
    (OLLAMA_MAX_LOADED_MODELS=1), while gpu.ensure('qwen3_8k') leaves LM Studio's small embedder alone."""
    return "lms_nomic" if index.index_path("lms_nomic").exists() else "nomic"


def _chunk_source(chunk: dict) -> str:
    """Source of a chunk dict, inferred from the id for chunks.json rows written before `source` existed."""
    return str(chunk.get("source") or index.infer_source(chunk.get("id", "")))


def retrieve_for_decision(situation: str, k: int = 8, index_key: str | None = None,
                          condition: str = prompts.DEFAULT_CONDITION) -> list[dict]:
    """Top-k chunks for the situation restricted to DECISION_SECTIONS (best score first, DECIDE_BOOST applied),
    followed by EVERY reflection chunk (source "reflection" in index.chunk_lookup()) not already among them, in
    chunks.json order. The whole index is searched (index.search clamps k to its size) so the section filter
    cannot starve k. Outside the interview condition returns [] without any embed call."""
    condition = prompts._condition(condition)
    if condition != "interview":
        return []
    if index_key is None:
        index_key = decision_index_key()
    lookup = index.chunk_lookup()
    n = max(CANDIDATES, len(lookup))
    hits = index.search_chunks(index_key, situation, k=n, boost=dict(DECIDE_BOOST), tab=TAB)
    kept = [c for c in hits if c.get("section") in DECISION_SECTIONS]
    kept.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)
    out = kept[:max(0, int(k))]
    seen = {c.get("id") for c in out}
    scored = {c.get("id"): c for c in hits}
    for cid, chunk in lookup.items():
        if cid in seen or _chunk_source(chunk) != "reflection":
            continue
        c = dict(scored[cid]) if cid in scored else dict(chunk)   # keeps the search score when it has one
        c["source"] = "reflection"
        out.append(c)
        seen.add(cid)
    return out


def build_context(chunks: list[dict], digest: str, condition: str = prompts.DEFAULT_CONDITION,
                  profile: profile_mod.Profile | None = None) -> str:
    """The CONTEXT the decision model sees. interview: numbered chunk blocks followed by the digest (byte-identical
    to phase 1); persona: "IDENTITY:\\n<identity>\\n\\nDIGEST:\\n<digest>"; demographic: "IDENTITY:\\n<identity>"
    (no chunks, no digest). `profile` defaults to get_profile() for the two ablations."""
    condition = prompts._condition(condition)
    digest_block = f"DIGEST:\n{(digest or '').strip() or '(none)'}"
    if condition != "interview":
        prof = profile if profile is not None else get_profile()
        identity = f"IDENTITY:\n{(prof.identity or '').strip()}"
        return identity if condition == "demographic" else f"{identity}\n\n{digest_block}"
    lines = []
    for i, c in enumerate(chunks, 1):
        title = (c.get("title") or c.get("id") or "").strip()
        text = (c.get("text") or "").strip()
        lines.append(f"[{i}] ({c.get('id', '')}) {title}\n{text}")
    body = "\n\n".join(lines) if lines else "(nothing retrieved)"
    return f"{body}\n\n{digest_block}"


def _user_message(context: str, situation: str, option_a: str | None = None, option_b: str | None = None) -> str:
    """User turn for B1 (no options) or B2 (two options)."""
    parts = [f"CONTEXT:\n{context}", f"SITUATION:\n{situation.strip()}"]
    if option_a is None:
        parts.append(B1_QUESTION)
    else:
        parts.append(f"OPTIONS:\nA: {option_a.strip()}\nB: {(option_b or '').strip()}")
        parts.append(B2_QUESTION)
    return "\n\n".join(parts)


# ---- model call with retries --------------------------------------------------
def _content_of(resp: dict) -> str:
    """Assistant text from an Ollama /api/chat response ('' when missing)."""
    return ((resp or {}).get("message") or {}).get("content") or ""


def _parse_json_object(text: str) -> dict | None:
    """Parse text as a JSON object; None when empty, invalid, or not an object."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        data = json.loads(t)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _chat_json(messages: list[dict], schema: dict) -> dict:
    """Call qwen3-8b-8k with the schema; retry once at num_predict 1200 on a `length` stop and once on
    empty/invalid JSON. Must be called inside gpu.MANAGER.session(DECIDE_KEY). Never raises OllamaError."""
    num_predict = NUM_PREDICT
    retried_length = False
    retried_parse = False
    raw = ""
    attempts = 0
    while True:
        attempts += 1
        try:
            resp = clients.ollama.chat(
                DECIDE_KEY, messages, format=schema, options=dict(DECIDE_OPTIONS),
                num_predict=num_predict, tab=TAB,
            )
        except clients.OllamaError as e:
            return {"parsed": None, "raw": raw, "error": f"ollama: {e}", "attempts": attempts,
                    "num_predict": num_predict}
        raw = _content_of(resp)
        if (resp or {}).get("done_reason") == "length" and not retried_length:
            retried_length = True
            num_predict = NUM_PREDICT_LONG
            continue
        parsed = _parse_json_object(raw)
        if parsed is not None:
            return {"parsed": parsed, "raw": raw, "error": None, "attempts": attempts, "num_predict": num_predict}
        if not retried_parse:
            retried_parse = True
            continue
        why = "empty reply" if not raw.strip() else "reply is not a JSON object"
        return {"parsed": None, "raw": raw, "error": f"{why} after {attempts} attempts", "attempts": attempts,
                "num_predict": num_predict}


# ---- validation ---------------------------------------------------------------
def _clamp_confidence(value) -> float:
    """Coerce to float and clamp into [0, 1]; non-numeric values become 0.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return max(0.0, min(1.0, f))


def _string_list(value) -> list[str]:
    """Coerce a JSON value to a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _split_citations(values, prof: profile_mod.Profile) -> tuple[list[str], list[str]]:
    """Split cited ids into (known profile decision ids, unknown strings), de-duplicated in order."""
    id_map = _decision_id_map(prof)
    cited: list[str] = []
    uncited: list[str] = []
    for v in _string_list(values):
        known = [id_map[c] for c in _all_decision_ids(v) if c in id_map]
        if known:
            for did in known:
                if did not in cited:
                    cited.append(did)
        elif v not in uncited:
            uncited.append(v)
    return cited, uncited


def _validate(kind: str, parsed: dict | None, prof: profile_mod.Profile) -> tuple[dict, str | None]:
    """Normalise the model's JSON into the result fields; returns (fields, error_or_None)."""
    error = None
    parsed = parsed or {}
    fields: dict = {"confidence": _clamp_confidence(parsed.get("confidence")),
                    "reasons": _string_list(parsed.get("reasons"))}
    cited, uncited = _split_citations(parsed.get("cited_decisions"), prof)
    fields["cited_decisions"] = cited
    fields["uncited"] = uncited
    if kind == "b1":
        verdict = str(parsed.get("verdict") or "").strip().lower()
        if verdict not in ("yes", "no"):
            error = f"verdict missing or invalid: {parsed.get('verdict')!r}"
            verdict = None
        fields["verdict"] = verdict
        fields["what_would_change_my_mind"] = str(parsed.get("what_would_change_my_mind") or "").strip()
    else:
        choice = str(parsed.get("choice") or "").strip().upper()
        if choice not in ("A", "B"):
            error = f"choice missing or invalid: {parsed.get('choice')!r}"
            choice = None
        fields["choice"] = choice
        fields["tradeoff"] = str(parsed.get("tradeoff") or "").strip()
    return fields, error


# ---- audit --------------------------------------------------------------------
def _audit(condition: str, request_text: str, chunk_ids: list[str], model_keys: list[str], ok: bool,
           extra: dict | None = None) -> None:
    """One audit line (request text reduced to its sha); an audit failure never breaks the call."""
    try:
        audit.record(TAB, condition, request_text, chunk_ids, model_keys, ok, extra=extra)
    except Exception:  # noqa: BLE001
        pass


# ---- public entry points ------------------------------------------------------
def _decide(kind: str, situation: str, option_a: str | None, option_b: str | None,
            condition: str = prompts.DEFAULT_CONDITION) -> dict:
    """Shared B1/B2 driver: retrieve, build the prompt, call the model inside the GPU session, validate."""
    t0 = time.perf_counter()
    condition = prompts._condition(condition)
    model_name = spec(DECIDE_KEY).name
    result: dict = {"kind": kind, "situation": (situation or "").strip(), "model": model_name,
                    "chunk_ids": [], "chunks": [], "raw": "", "error": None, "attempts": 0, "timing_ms": 0.0,
                    "condition": condition}
    if kind == "b2":
        result["option_a"] = (option_a or "").strip()
        result["option_b"] = (option_b or "").strip()

    prof = get_profile()
    empty_fields, _ = _validate(kind, {}, prof)
    result.update(empty_fields)

    if not result["situation"]:
        result["error"] = "situation is empty"
        result["timing_ms"] = (time.perf_counter() - t0) * 1000.0
        return result
    if kind == "b2" and not (result["option_a"] and result["option_b"]):
        result["error"] = "both options are required"
        result["timing_ms"] = (time.perf_counter() - t0) * 1000.0
        return result

    digest_text = digest_mod.load_digest()
    chunks = retrieve_for_decision(result["situation"], condition=condition)
    result["chunk_ids"] = [c.get("id", "") for c in chunks]
    result["chunks"] = [{"id": c.get("id", ""), "title": c.get("title", ""), "score": float(c.get("score", 0.0))}
                        for c in chunks]
    schema = prompts.B1_SCHEMA if kind == "b1" else prompts.B2_SCHEMA
    messages = [
        {"role": "system", "content": prompts.DECIDE_SYSTEM(prof.name)},
        {"role": "user", "content": _user_message(build_context(chunks, digest_text, condition, prof),
                                                  result["situation"],
                                                  result.get("option_a") if kind == "b2" else None,
                                                  result.get("option_b") if kind == "b2" else None)},
    ]

    try:
        with gpu.MANAGER.session(DECIDE_KEY, tab=TAB):
            call = _chat_json(messages, schema)
    except BaseException:
        _audit(condition, result["situation"], result["chunk_ids"], [DECIDE_KEY], False, {"kind": kind})
        raise

    result["raw"] = call["raw"]
    result["attempts"] = call["attempts"]
    result["num_predict"] = call["num_predict"]
    if call["parsed"] is None:
        result["error"] = call["error"]
    else:
        fields, verr = _validate(kind, call["parsed"], prof)
        result.update(fields)
        result["error"] = verr
    result["timing_ms"] = (time.perf_counter() - t0) * 1000.0
    _audit(condition, result["situation"], result["chunk_ids"], [DECIDE_KEY], result["error"] is None,
           {"kind": kind})
    return result


def decide_b1(situation: str, condition: str = prompts.DEFAULT_CONDITION) -> dict:
    """B1: would the twin do it? Returns verdict yes|no, confidence, reasons, cited_decisions, what_would_change_my_mind
    plus chunk_ids, raw, model, timing_ms, kind='b1', condition and error (None or str)."""
    return _decide("b1", situation, None, None, condition=condition)


def decide_b2(situation: str, option_a: str, option_b: str, condition: str = prompts.DEFAULT_CONDITION) -> dict:
    """B2: A or B? Returns choice A|B, confidence, reasons, cited_decisions, tradeoff
    plus chunk_ids, raw, model, timing_ms, kind='b2', condition and error (None or str)."""
    return _decide("b2", situation, option_a, option_b, condition=condition)


def _decision_phrase(result: dict) -> str | None:
    """'yes' / 'no' for B1, 'A (option text)' for B2; None when the result carries no decision."""
    if result.get("kind") == "b2":
        choice = result.get("choice")
        if choice not in ("A", "B"):
            return None
        opt = result.get("option_a" if choice == "A" else "option_b")
        return f"{choice} ({opt})" if opt else choice
    verdict = result.get("verdict")
    return verdict if verdict in ("yes", "no") else None


def _one_line(text: str) -> str:
    """Collapse a message to a single line."""
    return re.sub(r"\s+", " ", text or "").strip()


def say_it(result: dict) -> str:
    """Render a decision result as one short text message in the twin's voice with Stheno (LM Studio). The voice
    prompt follows the result's condition (`result["condition"]`, default interview)."""
    decision = _decision_phrase(result)
    if decision is None:
        return f"(nothing to say: {result.get('error') or 'no decision'})"
    condition = prompts._condition(result.get("condition") or "interview")
    prof = get_profile()
    digest_text = digest_mod.load_digest()
    chunks = _decision_chunks(prof, list(result.get("cited_decisions") or []))
    reasons = [r for r in (result.get("reasons") or []) if str(r).strip()]
    because = f", because {'; '.join(str(r).strip().rstrip('.') for r in reasons)}" if reasons else ""
    situation = _one_line(result.get("situation", "")).rstrip(".")
    user = (f"Someone asked: {situation}. Your decision: {decision}{because}. "
            "Say this as one short text message in your own words.")
    messages = [
        {"role": "system", "content": prompts.build_voice_system(prof, digest_text, chunks, condition=condition)},
        {"role": "user", "content": user},
    ]
    # Stheno Q4 on LM Studio (one retry on an empty reply); llama3.2:3b when LM Studio is down.
    used_ids = [c.get("id", "") for c in chunks] if condition == "interview" else []   # CONTEXT is interview-only
    try:
        content, voice_key = voice.reply_in_voice(messages, max_tokens=120, tab=TAB, temperature=1.0)
    except BaseException:
        _audit(condition, result.get("situation", ""), used_ids, [VOICE_KEY], False, {"kind": "say_it"})
        raise
    _audit(condition, result.get("situation", ""), used_ids, [voice_key], True, {"kind": "say_it"})
    return _one_line(prompts.postprocess_voice(content, prof.name))


def render_result_markdown(result: dict) -> str:
    """Markdown block for the UI: verdict/choice, confidence, reasons, cited decisions with titles, and the
    what-would-change-my-mind / tradeoff line, plus a small model/timing/condition footer."""
    try:
        titles = _decision_titles(get_profile())
    except OSError:
        titles = {}
    lines: list[str] = []
    if result.get("error"):
        lines.append(f"**Error:** {result['error']}")
    if result.get("kind") == "b2":
        choice = result.get("choice")
        if choice in ("A", "B"):
            opt = result.get("option_a" if choice == "A" else "option_b")
            head = f"**Choice: {choice}**" + (f" — {opt}" if opt else "")
        else:
            head = "**Choice: (none)**"
    else:
        verdict = result.get("verdict")
        head = f"**Verdict: {verdict.upper()}**" if verdict in ("yes", "no") else "**Verdict: (none)**"
    conf = result.get("confidence")
    if conf is not None:
        head += f"  \nConfidence: {_clamp_confidence(conf):.2f}"
    lines.append(head)
    reasons = result.get("reasons") or []
    if reasons:
        lines.append("**Reasons**\n" + "\n".join(f"- {r}" for r in reasons))
    cited = result.get("cited_decisions") or []
    if cited:
        lines.append("**Cited decisions**\n" + "\n".join(
            f"- {did}: {titles[did]}" if did in titles else f"- {did}" for did in cited))
    uncited = result.get("uncited") or []
    if uncited:
        lines.append("_Uncited references (not in the profile): " + ", ".join(uncited) + "_")
    if result.get("kind") == "b2":
        if result.get("tradeoff"):
            lines.append(f"**Tradeoff:** {result['tradeoff']}")
    elif result.get("what_would_change_my_mind"):
        lines.append(f"**What would change my mind:** {result['what_would_change_my_mind']}")
    footer = (f"_{result.get('model', '')} · {float(result.get('timing_ms') or 0.0):.0f} ms · "
              f"{len(result.get('chunk_ids') or [])} chunks · {int(result.get('attempts') or 0)} call(s)")
    if result.get("condition"):
        footer += f" · condition {result['condition']}"
    lines.append(footer + "_")
    return "\n\n".join(lines)
