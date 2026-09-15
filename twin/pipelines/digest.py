"""One-shot profile digest with qwen3:8b (40960 ctx), cached in data/digest.md by profile sha."""
from __future__ import annotations

from pathlib import Path

from .. import clients
from ..config import DIGEST_PATH
from ..gpu import MANAGER
from ..profile import NO_CHUNK_SECTIONS, Profile
from ..prompts import DIGEST_SYSTEM

_SHA_PREFIX = "<!-- sha: "


def digest_sha(path: Path | None = None) -> str | None:
    """Sha on the digest's first line ("<!-- sha: ... -->"); None when missing or malformed.
    DIGEST_PATH is resolved at call time (a def-time default ignored a rebound module path)."""
    try:
        first = Path(DIGEST_PATH if path is None else path).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    if first.startswith(_SHA_PREFIX) and first.rstrip().endswith("-->"):
        return first[len(_SHA_PREFIX):].rstrip()[:-3].strip()
    return None


def load_digest() -> str:
    try:
        lines = DIGEST_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    if lines and lines[0].startswith(_SHA_PREFIX):
        lines = lines[1:]
    return "\n".join(lines).strip()


def profile_text_without_eval(profile: Profile) -> str:
    """The profile text that reaches the digest prompt: every section except Eval and Changelog
    (profile.NO_CHUNK_SECTIONS); neither may ever reach a model prompt (docs/PLAN_UNIFIED.md 3.1)."""
    parts = [f"name: {profile.name}\nupdated: {profile.updated}"]
    for sec, text in profile.sections.items():
        if sec in NO_CHUNK_SECTIONS:
            continue
        parts.append(f"# {sec}\n{text}")
    return "\n\n".join(parts)


def build_digest(profile: Profile, tab: str = "digest") -> str:
    messages = [
        {"role": "system", "content": DIGEST_SYSTEM},
        {"role": "user", "content": "PROFILE:\n\n" + profile_text_without_eval(profile)},
    ]
    text = ""
    with MANAGER.session("qwen3_long", tab=tab):
        for _ in range(2):
            resp = clients.ollama.chat("qwen3_long", messages, num_predict=500, tab=tab)
            text = (resp.get("message", {}).get("content") or "").strip()
            if text:
                break
    DIGEST_PATH.write_text(f"{_SHA_PREFIX}{profile.sha} -->\n{text}\n", encoding="utf-8")
    return text


def ensure_digest(profile: Profile, force: bool = False) -> str:
    if not force and digest_sha() == profile.sha:
        return load_digest()
    return build_digest(profile)
