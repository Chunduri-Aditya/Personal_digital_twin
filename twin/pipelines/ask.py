"""Ask pipeline: router -> follow-up rewrite -> retrieval -> streamed voice reply -> optional checker.

Plan section 4 "Ask" plus the conditions of docs/PLAN_UNIFIED.md 3.4. Everything here is a plain function; the UI
(twin/ui/ask.py) only iterates ``ask_turn``.

Event contract (docs/CONTRACTS.md): every event is ``{"kind": ..., "text": str, "data": dict | None}`` with kind

* ``trace``   one line per step: router intent, rewritten query, chunk ids with scores, voice model, timings
* ``hint``    the intent was ``tool`` or ``image``: points at the Act / See tab (the turn still answers)
* ``token``   one streamed piece of the raw voice reply
* ``checker`` the opt-in qwen2.5 consistency check ran; ``data`` is its verdict
* ``done``    always the last event: ``text`` is the cleaned reply, ``data`` has intent, query, chunk_ids,
              voice_model, checker, condition (plus voice_name, chunks and timings for the UI)

Conditions: ``interview`` (default) is the phase-1 turn, byte-identical; ``persona`` skips retrieval (no embed
call, the static prefix with the digest); ``demographic`` skips retrieval and blanks the digest (identity only).
Every turn that called a model ends with one ``twin.audit`` line (request sha, chunk ids, model keys, ok).

Model access goes through the module objects (``clients.ollama``, ``clients.lms``, ``index.search_chunks``,
``gpu.MANAGER.session``, ``voice.pick_voice`` / ``voice.stream_in_voice``) so tests can swap them for fakes and
assert exact request bodies.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from twin import audit, clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.pipelines import digest, voice

TAB = "ask"

ROUTER_KEY = "llama32_1b"
REWRITE_KEY = "llama32_3b"
FALLBACK_VOICE_KEY = "llama32_3b"
VOICE_LMS_KEY = "stheno_q4"
VOICE_Q8_KEY = "stheno_q8"
CHECKER_KEY = "qwen25"

INTENTS: tuple[str, ...] = tuple(prompts.ROUTER_SCHEMA["properties"]["intent"]["enum"])
DEFAULT_INTENT = "about_me"
HISTORY_TURNS = 6          # history entries (one entry = one message) kept for rewrite and voice
TOP_K = 5
DECIDE_BOOST = {"Decisions": 0.05}

ROUTER_TOKENS = 40
REWRITE_TOKENS = 60
VOICE_TOKENS = 300
CHECKER_TOKENS = 300
CHECKER_TOKENS_RETRY = 600      # one retry when the first verdict is cut off (done_reason == "length")
FALLBACK_TEMPERATURE = 0.8
MAX_QUERY_CHARS = 300

HINTS = {
    "tool": ("This looks like a job for a tool (time, a calculation, or drafting a message). "
             "The Act tab can actually run it; answering in voice anyway."),
    "image": ("This sounds like it is about a picture. Upload it in the See tab to get a real look; "
              "answering from the profile anyway."),
}


# ---- events and results -------------------------------------------------------
def _ev(kind: str, text: str = "", data: dict | None = None) -> dict:
    """Build one event dict in the AskEvent shape."""
    return {"kind": kind, "text": text, "data": data}


@dataclass
class AskResult:
    """Everything one Ask turn produced, collected from its event stream."""
    reply: str = ""
    raw_text: str = ""
    intent: str = DEFAULT_INTENT
    query: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    voice_model: str | None = None
    checker: dict | None = None
    trace: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    condition: str = prompts.DEFAULT_CONDITION

    @classmethod
    def from_events(cls, events: Iterable[dict]) -> "AskResult":
        """Consume an event stream and fold it into an AskResult."""
        r = cls()
        pieces: list[str] = []
        for ev in events:
            kind = ev.get("kind")
            if kind == "token":
                pieces.append(ev.get("text") or "")
            elif kind == "trace":
                r.trace.append(ev.get("text") or "")
            elif kind == "hint":
                r.hints.append(ev.get("text") or "")
            elif kind == "checker":
                r.checker = ev.get("data")
            elif kind == "done":
                d = ev.get("data") or {}
                r.reply = ev.get("text") or ""
                r.intent = d.get("intent", r.intent)
                r.query = d.get("query", "")
                r.chunk_ids = list(d.get("chunk_ids") or [])
                r.voice_model = d.get("voice_model")
                r.checker = d.get("checker", r.checker)
                r.timings = dict(d.get("timings") or {})
                r.condition = d.get("condition") or r.condition
        r.raw_text = "".join(pieces)
        return r


# ---- profile cache -------------------------------------------------------------
_profile_lock = threading.Lock()
_profile_cache: dict = {}   # {"key": (path, mtime_ns, size), "profile": Profile}


def get_profile(force: bool = False):
    """Return the parsed profile, cached at module level; reloads when the resolved file changes."""
    path = profile_mod.resolve_profile_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(path), None, None)
    with _profile_lock:
        cached = _profile_cache.get("profile")
        if not force and cached is not None and _profile_cache.get("key") == key:
            return cached
        prof = profile_mod.load_profile(path)
        _profile_cache["key"] = key
        _profile_cache["profile"] = prof
        return prof


def reset_profile_cache() -> None:
    """Drop the cached profile so the next get_profile() reads the file again."""
    with _profile_lock:
        _profile_cache.clear()


# ---- small helpers -------------------------------------------------------------
def _short(e: BaseException) -> str:
    """One-line description of an exception for trace text."""
    return f"{type(e).__name__}: {str(e)[:160]}"


def _content(resp) -> str:
    """The assistant text of an Ollama /api/chat response or stream chunk ('' when absent)."""
    if not isinstance(resp, dict):
        return ""
    msg = resp.get("message") or {}
    if not isinstance(msg, dict):
        return ""
    return msg.get("content") or ""


def _parse_json(text: str) -> dict | None:
    """Parse a JSON object out of model output, tolerating surrounding prose; None on failure."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _str_list(v) -> list[str]:
    """Coerce a model-provided list into a list of non-empty strings."""
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _clean_history(history) -> list[dict]:
    """Keep only well-formed user/assistant text turns, last HISTORY_TURNS of them, as {role, content}."""
    out = []
    for m in history or []:
        if not isinstance(m, dict):
            continue
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out[-HISTORY_TURNS:]


def _clean_query(text: str) -> str:
    """Turn the rewrite model's output into one bare query line: first line, no label, no quotes."""
    t = (text or "").strip()
    if not t:
        return ""
    t = t.splitlines()[0].strip()
    # drop a "query:" label wherever it sits on the line, including a prose preamble before it
    if re.search(r"\bquery\s*:", t, flags=re.I):
        t = re.sub(r"^.*?\bquery\s*:\s*", "", t, count=1, flags=re.I)
    t = t.strip().strip("\"'`“”‘’").strip()
    return t[:MAX_QUERY_CHARS].strip()


# A reply that used the whole VOICE_TOKENS budget usually stops mid-sentence (demo rehearsal 2026-09-14: B4.1 ended
# "... is that nobody" in 2 of 2 runs). The done text is cut back to its last complete sentence; token events stay raw.
TRIM_MIN_KEEP = 0.5                                        # never trim away more than half of the reply
_SENTENCE_END_RE = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s|$)")
_COMPLETE_END_RE = re.compile(r"[.!?…]+[\"'”’)\]]*$")
_EMOJI_TRAILERS = "️‍⃣"                     # variation selector-16, zero-width joiner, keycap


def _ends_complete(text: str) -> bool:
    """True when the text ends on sentence punctuation (optionally closed by a quote or bracket) or on an emoji."""
    t = text.rstrip()
    if not t or _COMPLETE_END_RE.search(t):
        return True
    t = t.rstrip(_EMOJI_TRAILERS)
    ch = t[-1:] or " "
    return unicodedata.category(ch) == "So" or 0x1F000 <= ord(ch) <= 0x1FAFF


def _trim_to_last_sentence(text: str) -> str:
    """Cut text after its last sentence end (. ! ? or an ellipsis, optionally followed by a closing quote). Returns
    the text unchanged when it already ends complete, has no sentence end, or the cut would keep less than
    TRIM_MIN_KEEP of it."""
    t = (text or "").rstrip()
    if _ends_complete(t):
        return text
    ends = list(_SENTENCE_END_RE.finditer(t))
    if not ends:
        return text
    cut = t[:ends[-1].end()].rstrip()
    return cut if len(cut) >= TRIM_MIN_KEEP * len(t) else text


def _numbered_context(chunks: list[dict]) -> str:
    """Render retrieved chunks as '[i] (title) text' lines, the same shape the voice prompt uses."""
    lines = []
    for i, c in enumerate(chunks, 1):
        title = c.get("title") or c.get("id", "")
        lines.append(f"[{i}] ({title}) {(c.get('text') or '').strip()}")
    return "\n".join(lines) if lines else "(nothing retrieved)"


def _ollama_chat(key: str, messages: list[dict], **kw) -> dict:
    """Non-streaming Ollama chat with one retry when message.content comes back empty (plan risk)."""
    resp: dict = {}
    for _ in range(2):
        resp = clients.ollama.chat(key, messages, tab=TAB, **kw)
        if _content(resp).strip():
            break
    return resp


# ---- steps ---------------------------------------------------------------------
def _route(message: str) -> tuple[str, str]:
    """Classify the message with llama3.2:1b; returns (intent, note). Any failure -> about_me."""
    msgs = [{"role": "system", "content": prompts.ROUTER_SYSTEM}, {"role": "user", "content": message}]
    try:
        with gpu.MANAGER.session(ROUTER_KEY, tab=TAB):
            resp = _ollama_chat(ROUTER_KEY, msgs, format=prompts.ROUTER_SCHEMA,
                                options={"temperature": 0}, num_predict=ROUTER_TOKENS)
    except Exception as e:  # noqa: BLE001
        return DEFAULT_INTENT, f" (router failed: {_short(e)}; defaulting)"
    content = _content(resp)
    parsed = _parse_json(content)
    intent = parsed.get("intent") if parsed else None
    if isinstance(intent, str) and intent.strip().lower() in INTENTS:
        return intent.strip().lower(), ""
    return DEFAULT_INTENT, f" (unparseable router output {content.strip()[:60]!r}; defaulting)"


def route(message: str) -> str:
    """Router intent for one message: one of INTENTS, about_me on any failure."""
    return _route(message)[0]


def _rewrite(message: str, turns: list[dict]) -> tuple[str, str]:
    """Rewrite a follow-up into a standalone query with llama3.2:3b; returns (query, note)."""
    convo = "\n".join(f"{t['role']}: {t['content']}" for t in turns[-HISTORY_TURNS:])
    msgs = [
        {"role": "system", "content": prompts.REWRITE_SYSTEM},
        {"role": "user", "content": f"{convo}\nlatest: {message}"},
    ]
    try:
        with gpu.MANAGER.session(REWRITE_KEY, tab=TAB):
            resp = _ollama_chat(REWRITE_KEY, msgs, options={"temperature": 0}, num_predict=REWRITE_TOKENS)
    except Exception as e:  # noqa: BLE001
        return message, f" (rewrite failed: {_short(e)}; using the message)"
    q = _clean_query(_content(resp))
    if not q:
        return message, " (empty rewrite; using the message)"
    return q, ""


def rewrite(message: str, history: list[dict]) -> str:
    """Standalone query for `message`; the message itself when there is no usable history."""
    turns = _clean_history(history)
    if not turns:
        return message
    return _rewrite(message, turns)[0]


def retrieve(query: str, intent: str = DEFAULT_INTENT, index_key: str = "nomic") -> list[dict]:
    """Top-5 profile chunks for the query; Decisions get +0.05 when the intent is decide."""
    boost = dict(DECIDE_BOOST) if intent == "decide" else None
    return index.search_chunks(index_key, query, k=TOP_K, boost=boost, tab=TAB)


def _stream_voice(key: str, messages: list[dict], temperature: float | None) -> Iterator[dict]:
    """Token events from voice.stream_in_voice (LM Studio or Ollama stream inside one GPU session, one non-stream
    retry on an empty stream); the retry note becomes a trace event ahead of the retried text."""
    notes: list[str] = []
    stream = voice.stream_in_voice(key, messages, temperature, TAB, on_note=notes.append, max_tokens=VOICE_TOKENS)
    try:
        for piece in stream:
            while notes:
                yield _ev("trace", notes.pop(0))
            yield _ev("token", piece)
        while notes:
            yield _ev("trace", notes.pop(0))
    finally:
        stream.close()   # release the GPU session on this thread even if the consumer stops early


def check_reply(reply: str, chunks: list[dict]) -> dict:
    """Run the qwen2.5 consistency checker on a reply against its chunks; never raises."""
    msgs = [
        {"role": "system", "content": prompts.CHECKER_SYSTEM},
        {"role": "user", "content": f"CONTEXT:\n{_numbered_context(chunks)}\n\nREPLY:\n{reply}"},
    ]
    try:
        with gpu.MANAGER.session(CHECKER_KEY, tab=TAB):
            resp = _ollama_chat(CHECKER_KEY, msgs, format=prompts.CHECKER_SCHEMA,
                                options={"temperature": 0}, num_predict=CHECKER_TOKENS)
            content = _content(resp)
            parsed = _parse_json(content)
            if parsed is None and resp.get("done_reason") == "length":
                # long claim lists hit the cap and truncate the JSON: one retry with more room
                resp = _ollama_chat(CHECKER_KEY, msgs, format=prompts.CHECKER_SCHEMA,
                                    options={"temperature": 0}, num_predict=CHECKER_TOKENS_RETRY)
                content = _content(resp)
                parsed = _parse_json(content)
    except Exception as e:  # noqa: BLE001
        return {"consistent": None, "error": _short(e)}
    if not parsed or not isinstance(parsed.get("consistent"), bool):
        return {"consistent": None, "error": f"unparseable checker output: {content.strip()[:120]!r}"}
    return {
        "consistent": parsed["consistent"],
        "unsupported_claims": _str_list(parsed.get("unsupported_claims")),
        "contradictions": _str_list(parsed.get("contradictions")),
    }


def _checker_summary(data: dict) -> str:
    """One-line badge text for a checker verdict."""
    if data.get("consistent") is None:
        return f"checker failed: {data.get('error', '')}"
    if data["consistent"] and not data.get("unsupported_claims") and not data.get("contradictions"):
        return "consistent with the profile"
    return (f"{'consistent' if data['consistent'] else 'inconsistent'}: "
            f"{len(data.get('unsupported_claims') or [])} unsupported, "
            f"{len(data.get('contradictions') or [])} contradictions")


# ---- the turn ------------------------------------------------------------------
def _audit_turn(condition: str, message: str, ctx: dict, ok: bool) -> None:
    """One audit line for the turn (request text reduced to its sha); an audit failure never breaks a turn."""
    try:
        audit.record(TAB, condition, message, ctx["chunk_ids"], ctx["models"], ok)
    except Exception:  # noqa: BLE001
        pass


def _ask_events(message: str, history: list[dict], *, use_q8: bool, temperature: float | None,
                use_checker: bool, index_key: str, condition: str = prompts.DEFAULT_CONDITION) -> Iterator[dict]:
    """The Ask turn itself, as a generator of events; runs entirely on the calling thread. Once a model was
    called, one audit line is written when the turn ends (ok=False when it raised or was closed early)."""
    condition = prompts._condition(condition)
    ctx: dict = {"used": False, "chunk_ids": [], "models": []}
    ok = False
    try:
        yield from _turn(message, history, use_q8=use_q8, temperature=temperature, use_checker=use_checker,
                         index_key=index_key, condition=condition, ctx=ctx)
        ok = True
    finally:
        if ctx["used"]:
            _audit_turn(condition, (message or "").strip(), ctx, ok)


def _turn(message: str, history: list[dict], *, use_q8: bool, temperature: float | None, use_checker: bool,
          index_key: str, condition: str, ctx: dict) -> Iterator[dict]:
    """The steps of one turn; `ctx` collects the chunk ids and model keys for the audit line."""
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    message = (message or "").strip()
    turns = _clean_history(history)
    if not message:
        yield _ev("trace", "empty message, nothing to do")
        yield _ev("done", "", {"intent": DEFAULT_INTENT, "query": "", "chunk_ids": [], "voice_model": None,
                               "voice_name": None, "checker": None, "chunks": [], "timings": timings,
                               "condition": condition})
        return

    prof = get_profile()
    digest_text = digest.load_digest()
    yield _ev("trace", f"profile: {prof.name or '?'} ({len(prof.chunks)} chunks, sha {prof.sha[:8]}); "
                       f"digest {len(digest_text)} chars; history {len(turns)} turns")
    interview = condition == "interview"
    if condition == "demographic":
        digest_text = ""          # identity only: no digest, no retrieval
    chunks: list[dict] = []
    if not interview:
        yield _ev("trace", f"condition: {condition} (chunks: {len(chunks)}, "
                           f"digest: {'yes' if digest_text.strip() else 'no'})")

    # (2) router
    ctx["used"] = True
    ctx["models"].append(ROUTER_KEY)
    t0 = time.perf_counter()
    intent, note = _route(message)
    timings["router"] = round(time.perf_counter() - t0, 3)
    yield _ev("trace", f"router: {intent}{note} ({timings['router']:.2f} s)")
    if intent in HINTS:
        yield _ev("hint", HINTS[intent], {"intent": intent})

    # (3) rewrite, follow-ups only
    if turns:
        ctx["models"].append(REWRITE_KEY)
        t0 = time.perf_counter()
        query, note = _rewrite(message, turns)
        timings["rewrite"] = round(time.perf_counter() - t0, 3)
        yield _ev("trace", f"rewrite: {query!r}{note} ({timings['rewrite']:.2f} s)")
    else:
        query = message
        yield _ev("trace", "rewrite: skipped (no history)")

    # (4) retrieval, interview only (the embedder runs inside index.search_chunks in its own session)
    if interview:
        t0 = time.perf_counter()
        try:
            chunks = retrieve(query, intent, index_key)
            note = ""
        except Exception as e:  # noqa: BLE001
            chunks = []
            note = f" failed: {_short(e)}; answering without context"
        timings["retrieval"] = round(time.perf_counter() - t0, 3)
        hits = ", ".join(f"{c.get('id', '?')} {float(c.get('score', 0.0)):.3f}" for c in chunks) or "none"
        boost_note = " boost=Decisions+0.05" if intent == "decide" else ""
        yield _ev("trace", f"retrieval[{index_key}] k={TOP_K}{boost_note}{note}: {hits} ({timings['retrieval']:.2f} s)")
    ctx["chunk_ids"] = [c.get("id", "") for c in chunks]

    # (5) prompt: static prefix first, CONTEXT last (interview only), then the last turns and the message
    system = prompts.build_voice_system(prof, digest_text, chunks, condition=condition)
    messages = [{"role": "system", "content": system}] + turns + [{"role": "user", "content": message}]

    # (6) voice
    key, temp, note = voice.pick_voice(use_q8, temperature)
    s = config.spec(key)
    ctx["models"].append(key)
    yield _ev("trace", f"voice: {key} = {s.name} on {s.runtime}, temperature {temp}{note}")
    t0 = time.perf_counter()
    pieces: list[str] = []
    stream = _stream_voice(key, messages, temp)
    try:
        for ev in stream:
            if ev["kind"] == "token":
                pieces.append(ev["text"])
            yield ev
    finally:
        stream.close()   # release the GPU lock on this thread even if the consumer stops early
    timings["voice"] = round(time.perf_counter() - t0, 3)
    full = "".join(pieces)

    # (7) post-process; a reply that hit the VOICE_TOKENS cap is cut back to its last full sentence
    reply = prompts.postprocess_voice(full, prof.name)
    cleaned_chars = len(reply)
    trim_note = ""
    if len(pieces) >= VOICE_TOKENS:
        trimmed = _trim_to_last_sentence(reply)
        if trimmed != reply:
            reply = trimmed
            trim_note = f"; trimmed to {len(reply)} chars at the last full sentence (token cap)"
    yield _ev("trace", f"voice: {len(pieces)} pieces, {len(full)} chars raw, {cleaned_chars} cleaned "
                       f"({timings['voice']:.2f} s){trim_note}")

    # (8) checker (interview only: the other conditions have no CONTEXT to check against)
    checker = None
    if use_checker and interview:
        ctx["models"].append(CHECKER_KEY)
        t0 = time.perf_counter()
        checker = check_reply(reply, chunks)
        timings["checker"] = round(time.perf_counter() - t0, 3)
        yield _ev("checker", _checker_summary(checker), checker)
        yield _ev("trace", f"checker: {CHECKER_KEY} = {config.spec(CHECKER_KEY).name}, "
                           f"{_checker_summary(checker)} ({timings['checker']:.2f} s)")
    elif use_checker:
        yield _ev("trace", f"checker: skipped (no CONTEXT under the {condition} condition)")

    timings["total"] = round(time.perf_counter() - t_start, 3)
    yield _ev("trace", f"total {timings['total']:.2f} s")
    yield _ev("done", reply, {
        "intent": intent,
        "query": query,
        "chunk_ids": [c.get("id", "") for c in chunks],
        "voice_model": key,
        "voice_name": s.name,
        "checker": checker,
        "chunks": [{"id": c.get("id", ""), "title": c.get("title", ""), "score": float(c.get("score", 0.0))}
                   for c in chunks],
        "timings": timings,
        "condition": condition,
    })


_DONE = object()


class _Raised:
    """Carrier for an exception crossing the worker-thread queue."""
    __slots__ = ("exc",)

    def __init__(self, exc: BaseException):
        """Wrap the exception so the queue consumer can tell it apart from events."""
        self.exc = exc


def _relay(gen: Iterator[dict]) -> Iterator[dict]:
    """Run `gen` to completion on one dedicated thread and hand its events to the caller in order.

    gpu.MANAGER.lock is an RLock, which only the acquiring thread may release. Gradio resumes a streaming
    generator from an anyio worker pool, so consecutive next() calls can land on different threads while
    the Status timer shares that pool; keeping the whole turn (lock included) on one thread avoids
    "cannot release un-acquired lock". Exceptions are re-raised in the caller; if the caller stops early
    the worker closes the generator after its current chunk, releasing the lock on the same thread.
    """
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    def run() -> None:
        """Worker body: drive the generator, forward events, always finish with the _DONE sentinel."""
        try:
            for ev in gen:
                q.put(ev)
                if stop.is_set():
                    break
        except Exception as e:  # noqa: BLE001
            q.put(_Raised(e))
        finally:
            try:
                gen.close()
            except Exception as e:  # noqa: BLE001
                q.put(_Raised(e))
            q.put(_DONE)

    threading.Thread(target=run, name="twin-ask", daemon=True).start()
    try:
        while True:
            item = q.get()
            if item is _DONE:
                return
            if isinstance(item, _Raised):
                raise item.exc
            yield item
    finally:
        stop.set()


def ask_turn(message: str, history: list[dict], *, use_q8: bool = False, temperature: float | None = 1.0,
             use_checker: bool = False, index_key: str = "nomic", worker_thread: bool = True,
             condition: str = prompts.DEFAULT_CONDITION) -> Iterator[dict]:
    """One Ask turn as a stream of events (trace / hint / token / checker / done; see the module docstring).

    `history` is OpenAI-style [{"role": "user"|"assistant", "content": str}, ...] of previous turns only.
    `condition` is one of prompts.CONDITIONS (default interview; persona and demographic skip retrieval).
    By default the pipeline runs on a dedicated worker thread (see _relay); pass worker_thread=False when
    the caller already holds gpu.MANAGER.lock or wants everything on its own thread.
    """
    gen = _ask_events(message, history, use_q8=use_q8, temperature=temperature,
                      use_checker=use_checker, index_key=index_key, condition=condition)
    if not worker_thread:
        yield from gen
        return
    yield from _relay(gen)


def ask_sync(message: str, history: list[dict], *, use_q8: bool = False, temperature: float | None = 1.0,
             use_checker: bool = False, index_key: str = "nomic",
             condition: str = prompts.DEFAULT_CONDITION) -> AskResult:
    """Run a whole Ask turn on the calling thread and return the collected AskResult."""
    return AskResult.from_events(_ask_events(message, history, use_q8=use_q8, temperature=temperature,
                                             use_checker=use_checker, index_key=index_key, condition=condition))


# ---- CLI -----------------------------------------------------------------------
def main(argv=None) -> int:
    """CLI: python -m twin.pipelines.ask "question" [--q8] [--checker] [--temperature T] [--index nomic]
    [--condition demographic|persona|interview]."""
    ap = argparse.ArgumentParser(prog="python -m twin.pipelines.ask")
    ap.add_argument("message")
    ap.add_argument("--q8", action="store_true")
    ap.add_argument("--checker", action="store_true")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--index", default="nomic", choices=list(index.INDEX_KEYS))
    ap.add_argument("--condition", default=prompts.DEFAULT_CONDITION, choices=list(prompts.CONDITIONS),
                    help="demographic (identity only), persona (static prefix + digest) or interview (default)")
    args = ap.parse_args(argv)
    for ev in ask_turn(args.message, [], use_q8=args.q8, temperature=args.temperature,
                       use_checker=args.checker, index_key=args.index, condition=args.condition):
        if ev["kind"] == "token":
            print(ev["text"], end="", flush=True)
        elif ev["kind"] == "done":
            print()
            print(f"[done] {json.dumps(ev['data'], ensure_ascii=False)}", file=sys.stderr)
            print(ev["text"])
        elif ev["kind"] == "checker":
            print(f"[checker] {json.dumps(ev['data'], ensure_ascii=False)}", file=sys.stderr)
        else:
            print(f"[{ev['kind']}] {ev['text']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
