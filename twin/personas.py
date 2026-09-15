"""Persona registry: data/personas/<slug>.md profile files that can be switched into data/twin_profile.md (the
app's live profile slot) or imported from an uploaded .md. Built for the Status tab's Persona controls.

Each entry's transcript/reflections settings are explicit, never inferred, so a switch never falls back to
another persona's transcript or stale reflections draft (the bug twin.index.build_all's default resolution had
for a profile with no transcript of its own: it fell back to Mara's example transcript and to
data/reflections.md even when that draft belonged to a different persona). "mara" defers to
index.resolve_transcript_source's own default resolution (`default_transcript=True`), which is what the
signed-off demo build used and which prefers her REDACTED example transcript when it exists, matching the
already-built demo indexes; every other persona, including imports, has none unless a matching
data/personas/<slug>.transcript.md sits beside its profile -- pass that in yourself if you later record a real
interview for a persona (twin.redact's redaction pipeline is not wired to persona sidecars).

Each switch also caches the digest it built at data/personas/<slug>.digest.md and restores it before the next
build_all when that persona's profile sha is unchanged, so switching back to a persona already built does not
pay for another qwen3:8b digest generation.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import index
from . import profile as profile_mod
from .config import DATA_DIR, DIGEST_PATH, EXAMPLE_PROFILE_V2_PATH, PROFILE_PATH

PERSONAS_DIR = DATA_DIR / "personas"
PERSONAS_DIR.mkdir(exist_ok=True)
ACTIVE_PATH = PERSONAS_DIR / "active.json"
MARA_SLUG = "mara"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class PersonaError(ValueError):
    """A persona registry or import operation could not complete (unknown slug, bad upload, duplicate name)."""


@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    profile_path: Path
    transcript_path: Path | None    # None = no transcript at all; build_all gets no_transcript=True
    reflections_path: Path | None   # redirects collect_chunks' "no Expert reflections section" draft fallback
    default_transcript: bool = False  # True (mara only): let index.py resolve the transcript the normal way


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return s or "persona"


def _entry(slug: str, path: Path) -> Persona:
    name = slug
    try:
        name = profile_mod.load_profile(path).name or slug
    except Exception:  # noqa: BLE001
        pass
    if slug == MARA_SLUG:
        return Persona(slug, name, path, None, None, default_transcript=True)
    tp = PERSONAS_DIR / f"{slug}.transcript.md"
    rp = PERSONAS_DIR / f"{slug}.reflections.md"
    return Persona(slug, name, path, tp if tp.exists() else None, rp)


def _digest_cache_path(slug: str) -> Path:
    return PERSONAS_DIR / f"{slug}.digest.md"


def seed_registry() -> None:
    """Seed personas/mara.md from the example profile already on disk, without rebuilding anything. A no-op
    once that file (and active.json) exist."""
    mara_path = PERSONAS_DIR / f"{MARA_SLUG}.md"
    if not mara_path.exists() and EXAMPLE_PROFILE_V2_PATH.exists():
        shutil.copyfile(EXAMPLE_PROFILE_V2_PATH, mara_path)
    if not ACTIVE_PATH.exists():
        write_active(MARA_SLUG)


def registry() -> dict[str, Persona]:
    seed_registry()
    out: dict[str, Persona] = {}
    for p in sorted(PERSONAS_DIR.glob("*.md")):
        if p.name.endswith((".transcript.md", ".reflections.md", ".digest.md")):
            continue
        out[p.stem] = _entry(p.stem, p)
    return out


def choices() -> list[tuple[str, str]]:
    """(label, slug) pairs for the Status tab's Persona dropdown, in registry() order."""
    return [(f"{p.name} ({slug})", slug) for slug, p in registry().items()]


def active_slug() -> str:
    seed_registry()
    try:
        slug = str(json.loads(ACTIVE_PATH.read_text(encoding="utf-8")).get("slug") or "")
    except Exception:  # noqa: BLE001
        slug = ""
    reg = registry()
    if slug in reg:
        return slug
    return MARA_SLUG if MARA_SLUG in reg else next(iter(reg), "")


def write_active(slug: str) -> None:
    ACTIVE_PATH.write_text(json.dumps({"slug": slug}), encoding="utf-8")


def active_persona() -> Persona | None:
    return registry().get(active_slug())


def switch(slug: str) -> Persona:
    """Copy the persona's profile into data/twin_profile.md, rebuild the three indexes/chunks.json/digest with
    THIS persona's own transcript/reflections settings, then record it active. Restores a cached digest first
    when this persona was already built at the same profile sha, so a switch back never re-pays for a fresh
    qwen3:8b digest; the cache is refreshed after a successful build. Raises PersonaError for an unknown slug;
    propagates index.RedactionRequired / index.LeakError from the build unchanged (build_all never writes
    DIGEST_PATH in that case, so nothing stale gets cached)."""
    entry = registry().get(slug)
    if entry is None:
        raise PersonaError(f"unknown persona {slug!r}; known: {', '.join(registry()) or '(none)'}")
    PROFILE_PATH.write_bytes(entry.profile_path.read_bytes())
    prof = profile_mod.load_profile(PROFILE_PATH)
    cached_digest = _digest_cache_path(slug)
    if cached_digest.exists():
        from .pipelines.digest import digest_sha
        if digest_sha(cached_digest) == prof.sha:
            shutil.copyfile(cached_digest, DIGEST_PATH)
    if entry.default_transcript:
        index.build_all(prof, True, with_reflections=True)
    else:
        index.build_all(prof, True, with_reflections=bool(entry.transcript_path), transcript_path=entry.transcript_path,
                        no_transcript=entry.transcript_path is None, reflections_path=entry.reflections_path)
    if DIGEST_PATH.exists():
        shutil.copyfile(DIGEST_PATH, cached_digest)
    write_active(slug)
    return entry


def import_md(data: bytes, filename: str) -> Persona:
    """Validate and register an uploaded .md as a new persona under its own slug. Never switches to it and never
    builds an index -- that stays a separate, explicit Switch persona click. Rejects a non-.md file, text that
    is not valid UTF-8, an empty frontmatter `name:`, or a slug that already exists."""
    if not filename.lower().endswith(".md"):
        raise PersonaError(f"{filename!r} is not a .md file")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise PersonaError(f"{filename!r} is not valid UTF-8 text: {e}") from e
    prof = profile_mod.parse_profile(text, filename)
    if not prof.name.strip():
        raise PersonaError(f"{filename!r} has no `name:` in its frontmatter; refusing to import")
    slug = slugify(prof.name)
    reg = registry()
    if slug in reg:
        raise PersonaError(f"a persona with slug {slug!r} ({reg[slug].name!r}) already exists; rename the "
                           "file's frontmatter `name:` to import as a new persona")
    dest = PERSONAS_DIR / f"{slug}.md"
    dest.write_bytes(data)
    return _entry(slug, dest)
