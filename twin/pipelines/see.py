"""See tab: qwen3.5 (vision) describes an uploaded image, then Stheno reacts in the twin's voice.

Flow (plan section 4, "See"): resize to <= 1024 px -> base64 JPEG in `images` -> qwen3.5 with
think:false, temp 0.7, VISION_PROMPT -> stop qwen3.5 so Stheno can load -> retrieval on the
description -> Stheno reacts with the voice prefix + "You just saw: <description>". The reaction goes through
`voice.reply_in_voice` (Stheno Q4 on LM Studio, one retry on an empty reply; llama3.2:3b on Ollama when LM
Studio is down or the call fails), the same path Decide "say it" and Act "polish" use.
"""
from __future__ import annotations

import base64
import hashlib
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .. import clients, config, gpu, index, prompts
from .. import profile as profile_mod
from . import digest, voice

TAB = "see"
VISION_KEY = "qwen35_vision"
VOICE_KEY = "stheno_q4"
FALLBACK_VOICE_KEY = "llama32_3b"
INDEX_KEY = "nomic"
MAX_SIDE = 1024
JPEG_QUALITY = 85
RETRIEVAL_K = 5
VISION_NUM_PREDICT = 300
REACTION_MAX_TOKENS = 150
REACTION_INSTRUCTION = "React to it in one or two sentences, as yourself."
FALLBACK_REASON = "LM Studio down or the call failed: fell back to llama3.2:3b"

_PROFILE_CACHE: dict[str, profile_mod.Profile] = {}


# ---- helpers -------------------------------------------------------------------
def _get_profile() -> profile_mod.Profile:
    """Return the parsed profile, re-parsing only when the file's sha256 changes."""
    path = profile_mod.resolve_profile_path()
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    prof = _PROFILE_CACHE.get(sha)
    if prof is None:
        prof = profile_mod.load_profile(path)
        _PROFILE_CACHE.clear()
        _PROFILE_CACHE[prof.sha] = prof
    return prof


def _ollama_content(resp) -> str:
    """Extract the assistant text from a non-stream /api/chat response ("" when absent)."""
    if not isinstance(resp, dict):
        return ""
    msg = resp.get("message") or {}
    return (msg.get("content") or "").strip()


def _ollama_chat_with_retry(key: str, messages: list[dict], **kwargs) -> str:
    """Call clients.ollama.chat once, and once more if the content came back empty; return the text."""
    text = ""
    for _ in range(2):
        resp = clients.ollama.chat(key, messages, stream=False, tab=TAB, **kwargs)
        text = _ollama_content(resp)
        if text:
            break
    return text


def _stop_quietly(name: str) -> bool:
    """Stop an Ollama model by server name; never raises (the GPU manager would evict it anyway)."""
    try:
        clients.ollama.stop(name)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---- image ---------------------------------------------------------------------
def _to_pil(img) -> Image.Image:
    """Open a PIL image, numpy array or file path as an RGB PIL image."""
    if isinstance(img, Image.Image):
        return img.convert("RGB")
    if isinstance(img, np.ndarray):
        return Image.fromarray(img).convert("RGB")
    if isinstance(img, (str, Path)):
        with Image.open(img) as opened:
            opened.load()
            return opened.convert("RGB")
    raise TypeError(f"prepare_image expects a PIL.Image, numpy array or file path, got {type(img).__name__}")


def prepare_image(img) -> str:
    """Return a base64 JPEG (quality 85, RGB, longest side <= 1024, aspect kept) for a PIL image or file path."""
    im = _to_pil(img)
    w, h = im.size
    longest = max(w, h)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / float(longest)
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        im = im.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---- pipeline steps ------------------------------------------------------------
def describe_image(img) -> dict:
    """Describe an image with qwen3.5 (one retry on empty content), then ALWAYS stop it so Stheno can load next."""
    b64 = prepare_image(img)
    s = config.spec(VISION_KEY)
    messages = [{"role": "user", "content": prompts.VISION_PROMPT}]
    t0 = time.perf_counter()
    text = ""
    stopped = False
    with gpu.MANAGER.session(VISION_KEY, tab=TAB):
        try:
            text = _ollama_chat_with_retry(
                VISION_KEY, messages, images_on_last_user=[b64],
                options={"temperature": 0.7}, num_predict=VISION_NUM_PREDICT,
            )
        finally:
            stopped = _stop_quietly(s.name)
    return {
        "description": text,
        "timing_ms": (time.perf_counter() - t0) * 1000.0,
        "model": s.name,
        "stopped": stopped,
    }


def _reaction_messages(description: str) -> tuple[list[dict], list[str]]:
    """Build [system voice prompt with retrieved CONTEXT, user 'You just saw: ...'] and the chunk ids used."""
    prof = _get_profile()
    dg = digest.load_digest()
    chunks = index.search_chunks(INDEX_KEY, description, k=RETRIEVAL_K, tab=TAB)
    system = prompts.build_voice_system(prof, dg, chunks)
    user = f"You just saw: {description}\n{REACTION_INSTRUCTION}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return messages, [c.get("id", "") for c in chunks]


def react(description: str) -> dict:
    """React to a description in the twin's voice through voice.reply_in_voice (Stheno Q4 at temperature 1.0,
    150 tokens, one retry on an empty reply; llama3.2:3b when LM Studio is down or the call fails)."""
    prof = _get_profile()
    messages, chunk_ids = _reaction_messages(description)
    t0 = time.perf_counter()
    raw, voice_key = voice.reply_in_voice(messages, max_tokens=REACTION_MAX_TOKENS, tab=TAB, temperature=1.0)
    fallback_reason = FALLBACK_REASON if voice_key == FALLBACK_VOICE_KEY else ""
    reply = prompts.postprocess_voice(raw, prof.name)
    return {
        "reaction": reply,
        "chunk_ids": chunk_ids,
        "voice_model": config.spec(voice_key).name,
        "voice_key": voice_key,
        "fallback_reason": fallback_reason,
        "timing_ms": (time.perf_counter() - t0) * 1000.0,
    }


def see_turn(img) -> dict:
    """Full See turn: describe with qwen3.5, stop it, then react with the voice model. Returns a dict with
    description, reaction, trace (step lines with timings) and chunk_ids."""
    t0 = time.perf_counter()
    trace: list[str] = []
    # Hold the manager's RLock for the whole turn so the heartbeat thread cannot re-warm qwen3.5
    # between the vision session and the Stheno session (session() re-enters the same RLock).
    with gpu.MANAGER.lock:
        d = describe_image(img)
        trace.append(f"vision {d['model']}: {len(d['description'])} chars in {d['timing_ms']:.0f} ms "
                     f"(num_ctx {config.spec(VISION_KEY).num_ctx}, think false, temp 0.7, num_predict {VISION_NUM_PREDICT})")
        trace.append(f"stop {d['model']} (keep_alive 0): {'ok' if d['stopped'] else 'failed, manager will evict it'}")
        if not d["description"]:
            trace.append("vision returned empty content twice; reaction skipped")
            trace.append(f"total {(time.perf_counter() - t0) * 1000.0:.0f} ms")
            return {"description": "", "reaction": "", "trace": trace, "chunk_ids": []}
        r = react(d["description"])
    trace.append(f"retrieval {INDEX_KEY} k={RETRIEVAL_K} on the description: {', '.join(r['chunk_ids']) or '(none)'}")
    if r["fallback_reason"]:
        trace.append(f"fallback voice: {r['fallback_reason']}")
    trace.append(f"voice {r['voice_model']}: {len(r['reaction'])} chars in {r['timing_ms']:.0f} ms")
    trace.append(f"total {(time.perf_counter() - t0) * 1000.0:.0f} ms")
    return {
        "description": d["description"],
        "reaction": r["reaction"],
        "trace": trace,
        "chunk_ids": r["chunk_ids"],
        "voice_model": r["voice_model"],
    }
