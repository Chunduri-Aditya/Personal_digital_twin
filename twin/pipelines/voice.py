"""Shared voice calls: Stheno Q4 on LM Studio (or Q8 on Ollama), with llama3.2:3b on Ollama as the fallback.

`reply_in_voice` (non-streaming) serves Decide "say it", Act "polish" and See "react"; `pick_voice` and
`stream_in_voice` serve the streamed Ask reply (docs/PLAN_UNIFIED.md section 1: one Stheno-to-llama3.2:3b
fallback instead of two copies). The caller builds the messages and post-processes the text; this module only
picks the runtime and retries once on an empty reply. Clients and the GPU manager are reached through their
modules so tests can monkeypatch them; every request body is pinned by tests/test_voice.py and
tests/test_conditions.py.
"""
from __future__ import annotations

from typing import Callable, Iterator

from .. import clients, config, gpu

VOICE_KEY = "stheno_q4"
VOICE_Q8_KEY = "stheno_q8"
FALLBACK_VOICE_KEY = "llama32_3b"
FALLBACK_TEMPERATURE = 0.8
STREAM_TOKENS = 300      # default token budget of a streamed reply (ask.VOICE_TOKENS)
LMS_DOWN_NOTE = " (LM Studio is down: falling back to llama3.2:3b on Ollama)"
EMPTY_STREAM_NOTE = "voice: empty stream, retrying once without streaming"


def _lms_content(resp) -> str:
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return ""
    return (getattr(getattr(choices[0], "message", None), "content", None) or "")


def _lms_delta(chunk) -> str:
    """The text delta of one LM Studio (OpenAI SDK) stream chunk ('' for usage-only chunks)."""
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None) or ""


def _ollama_content(resp) -> str:
    if not isinstance(resp, dict):
        return ""
    return ((resp.get("message") or {}).get("content") or "")


def lms_down() -> bool:
    """True only when the LM Studio health probe explicitly fails (fakes without alive() count as up)."""
    probe = getattr(clients.lms, "alive", None)
    return callable(probe) and probe() is False


def pick_voice(use_q8: bool, temperature: float | None) -> tuple[str, float | None, str]:
    """(key, temperature, trace note): Q8 on Ollama when asked, Stheno on LM Studio when it is up, else llama3.2:3b
    at FALLBACK_TEMPERATURE with a note for the trace (moved from ask._pick_voice, strings unchanged)."""
    if use_q8:
        return VOICE_Q8_KEY, temperature, ""
    if not lms_down():
        return VOICE_KEY, temperature, ""
    return FALLBACK_VOICE_KEY, FALLBACK_TEMPERATURE, LMS_DOWN_NOTE


def stream_in_voice(key: str, messages: list[dict], temperature: float | None, tab: str,
                    on_note: Callable[[str], None] | None = None, max_tokens: int = STREAM_TOKENS) -> Iterator[str]:
    """Stream the raw reply pieces of `key` inside one MANAGER.session(key, tab): LM Studio (`stream=True`) or
    Ollama (`stream=True`, options temperature, num_predict). An entirely empty stream gets ONE non-streaming
    retry with the same body; `on_note(EMPTY_STREAM_NOTE)` is called just before it. Close the iterator early to
    release the session on the consuming thread."""
    s = config.spec(key)
    note = on_note or (lambda _text: None)
    got = False
    with gpu.MANAGER.session(key, tab=tab):
        if s.runtime == "lms":
            stream = clients.lms.chat(key, messages, temperature=temperature, max_tokens=max_tokens,
                                      stream=True, tab=tab)
            for chunk in stream:
                piece = _lms_delta(chunk)
                if piece:
                    got = got or bool(piece.strip())
                    yield piece
            if not got:
                note(EMPTY_STREAM_NOTE)
                resp = clients.lms.chat(key, messages, temperature=temperature, max_tokens=max_tokens,
                                        stream=False, tab=tab)
                piece = _lms_content(resp)
                if piece:
                    yield piece
        else:
            opts = {"temperature": temperature} if temperature is not None else {}
            stream = clients.ollama.chat(key, messages, stream=True, options=opts, num_predict=max_tokens, tab=tab)
            for chunk in stream:
                piece = _ollama_content(chunk)
                if piece:
                    got = got or bool(piece.strip())
                    yield piece
            if not got:
                note(EMPTY_STREAM_NOTE)
                resp = clients.ollama.chat(key, messages, stream=False, options=opts, num_predict=max_tokens, tab=tab)
                piece = _ollama_content(resp)
                if piece:
                    yield piece


def reply_in_voice(messages: list[dict], *, max_tokens: int, tab: str, temperature: float = 1.0) -> tuple[str, str]:
    """Return (raw_reply, voice_key). Stheno Q4 via LM Studio when it is up (one retry on an empty reply);
    otherwise, or when the LM Studio call raises, llama3.2:3b via Ollama at temperature 0.8."""
    if not lms_down():
        try:
            text = ""
            with gpu.MANAGER.session(VOICE_KEY, tab=tab):
                for _ in range(2):
                    resp = clients.lms.chat(VOICE_KEY, messages, temperature=temperature, max_tokens=max_tokens,
                                            tab=tab)
                    text = _lms_content(resp)
                    if text.strip():
                        break
            return text, VOICE_KEY
        except Exception:  # noqa: BLE001
            pass
    text = ""
    with gpu.MANAGER.session(FALLBACK_VOICE_KEY, tab=tab):
        for _ in range(2):
            resp = clients.ollama.chat(FALLBACK_VOICE_KEY, messages, options={"temperature": FALLBACK_TEMPERATURE},
                                       num_predict=max_tokens, tab=tab)
            text = _ollama_content(resp)
            if text.strip():
                break
    return text, FALLBACK_VOICE_KEY
