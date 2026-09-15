"""Build, load and search the three embedding indexes over the profile, the redacted interview transcript and
the expert reflections; CLI: python -m twin.index.

v2 (docs/PLAN_UNIFIED.md 3.3): `collect_chunks` tags every chunk with a source (profile | transcript |
reflection); the npz files and chunks.json carry a per-row `source` and a `combined_sha` over the three inputs;
`search(..., sources=...)` masks rows before top-k; `build_all` refuses to embed while any transcript chunk
contains more than 60% of a gold Eval answer's words (LeakError) or while a real transcript has no up-to-date
redacted copy (RedactionRequired). Old npz/chunks.json files without the new keys still load.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from . import clients
from . import transcript as transcript_mod
from .config import (CHUNKS_PATH, DATA_DIR, EXAMPLE_REDACTED_TRANSCRIPT_PATH, EXAMPLE_TRANSCRIPT_PATH,
                     REDACTED_TRANSCRIPT_PATH, REFLECTIONS_PATH, TRANSCRIPT_PATH, spec)
from .gpu import MANAGER
from .profile import Chunk, Profile, _split_frontmatter, load_profile

INDEX_KEYS = {"nomic": "nomic_ollama", "gemma": "embeddinggemma", "lms_nomic": "nomic_lms"}
SOURCES = ("profile", "transcript", "reflection")
REFLECTION_SECTION = "Expert reflections"   # profile section whose chunks are tagged source "reflection" (D2 wins)
DRAFT_SECTION = "Reflections"               # reflect.py draft chunks, indexed only while the profile lacks the section
CONTAINMENT_THRESHOLD = 0.6


class RedactionRequired(RuntimeError):
    """A real transcript exists but no redacted copy matches its bytes; run python -m twin.redact first."""


class LeakError(RuntimeError):
    """A transcript chunk contains most of a gold Eval answer; nothing was embedded."""


@dataclass
class Index:
    vectors: np.ndarray
    ids: list[str]
    embedder: str
    sha: str
    source: list[str] = field(default_factory=list)
    combined_sha: str = ""


def index_path(index_key: str) -> Path:
    return DATA_DIR / f"index_{index_key}.npz"


# ---------------------------------------------------------------------------
# chunk helpers (accept Chunk objects and chunk dicts alike)
# ---------------------------------------------------------------------------
def _id(chunk) -> str:
    return chunk["id"] if isinstance(chunk, dict) else chunk.id


def _title(chunk) -> str:
    return chunk["title"] if isinstance(chunk, dict) else chunk.title


def _text(chunk) -> str:
    return chunk["text"] if isinstance(chunk, dict) else chunk.text


def infer_source(chunk_id: str) -> str:
    """Source of a chunk from its id alone (for files written before `source` existed)."""
    sec = (chunk_id or "").split("/", 1)[0]
    if sec == transcript_mod.CHUNK_SECTION:
        return "transcript"
    if sec in (REFLECTION_SECTION, DRAFT_SECTION):
        return "reflection"
    return "profile"


def _source(chunk) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("source") or infer_source(chunk.get("id", "")))
    return getattr(chunk, "source", "") or infer_source(chunk.id)


def _chunk_dict(chunk) -> dict:
    d = asdict(chunk) if isinstance(chunk, Chunk) else dict(chunk)
    d["source"] = _source(chunk)
    return d


def doc_text(index_key: str, chunk) -> str:
    if index_key == "gemma":
        return f"title: {_title(chunk)} | text: {_text(chunk)}"
    return f"search_document: {_text(chunk)}"


def query_text(index_key: str, q: str) -> str:
    if index_key == "gemma":
        return f"task: search result | query: {q}"
    return f"search_query: {q}"


def embed_texts(index_key: str, texts: list[str], tab: str = "") -> np.ndarray:
    key = INDEX_KEYS[index_key]
    s = spec(key)
    with MANAGER.session(key, tab=tab):
        if s.runtime == "lms":
            return clients.lms.embed(key, texts, tab=tab)
        return clients.ollama.embed(key, texts, tab=tab)


def _normalise(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return (v / n).astype(np.float32)


# ---------------------------------------------------------------------------
# sources: transcript resolution, chunk collection, shas
# ---------------------------------------------------------------------------
def file_sha(path) -> str:
    """sha256 of a file's bytes; "" when the path is None or unreadable."""
    if not path:
        return ""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _frontmatter_source_sha(path) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    meta, _ = _split_frontmatter(text)
    return meta.get("source_sha", "")


def resolve_transcript_source(no_redact: bool = False, quiet: bool = False) -> Path | None:
    """The transcript file the index may read.

    Real transcript present: its redacted copy when that copy's frontmatter `source_sha` matches the real
    file's bytes; else the real file only with `no_redact`; else RedactionRequired. No real transcript: the
    example's redacted copy when it matches, else the (synthetic) example itself, else None."""
    if TRANSCRIPT_PATH.exists():
        real_sha = file_sha(TRANSCRIPT_PATH)
        if REDACTED_TRANSCRIPT_PATH.exists() and _frontmatter_source_sha(REDACTED_TRANSCRIPT_PATH) == real_sha:
            return REDACTED_TRANSCRIPT_PATH
        if no_redact:
            return TRANSCRIPT_PATH
        state = "is out of date" if REDACTED_TRANSCRIPT_PATH.exists() else "does not exist"
        raise RedactionRequired(
            f"{REDACTED_TRANSCRIPT_PATH.name} {state} for {TRANSCRIPT_PATH.name}: "
            "run python -m twin.redact data/interview_transcript.md first (or pass --no-redact)"
        )
    if (EXAMPLE_REDACTED_TRANSCRIPT_PATH.exists()
            and _frontmatter_source_sha(EXAMPLE_REDACTED_TRANSCRIPT_PATH) == file_sha(EXAMPLE_TRANSCRIPT_PATH)):
        return EXAMPLE_REDACTED_TRANSCRIPT_PATH
    if EXAMPLE_TRANSCRIPT_PATH.exists():
        if not quiet:
            print("example transcript (synthetic), unredacted")
        return EXAMPLE_TRANSCRIPT_PATH
    return None


def _reflections_path(reflections_path) -> Path:
    return Path(REFLECTIONS_PATH if reflections_path is None else reflections_path)


def _tag_profile_chunks(profile: Profile) -> list[Chunk]:
    """Profile chunks keep source "profile" except the "Expert reflections" section, tagged "reflection"."""
    return [replace(c, source="reflection" if c.section == REFLECTION_SECTION else "profile") for c in profile.chunks]


def _profile_corpus(profile: Profile) -> tuple[list[Chunk], dict]:
    return _tag_profile_chunks(profile), {"profile": profile.sha, "transcript": "", "reflections": ""}


def collect_chunks(profile: Profile, transcript_path=None, reflections_path=None) -> tuple[list[Chunk], dict]:
    """Every chunk the index holds, tagged by source, plus the input shas
    {"profile", "transcript" (sha256 of the file bytes or ""), "reflections" (sha or "")}.

    Profile chunks: source "profile", except section "Expert reflections" -> "reflection" (D2 wins). Transcript
    chunks (source "transcript") come from transcript.transcript_chunks: turns in excluded blocks are never
    chunked and the skipped count is printed. The reflect.py draft (REFLECTIONS_PATH unless `reflections_path`
    is given) is added as "Reflections/<lens>" (source "reflection") ONLY when the profile has no
    "Expert reflections" section. `transcript_path=None` means no transcript."""
    chunks = _tag_profile_chunks(profile)
    shas = {"profile": profile.sha, "transcript": "", "reflections": ""}
    if transcript_path:
        t = transcript_mod.load_transcript(Path(transcript_path))
        skipped = transcript_mod.excluded_turns(t)
        print(f"excluded blocks: {len(t.exclude_blocks)} (turns skipped: {len(skipped)})")
        chunks.extend(transcript_mod.transcript_chunks(t))
        shas["transcript"] = t.sha
    rp = _reflections_path(reflections_path)
    if REFLECTION_SECTION not in profile.sections and rp.exists():
        from .pipelines import reflect
        for lens, text in reflect.load_reflections(rp).items():
            chunks.append(Chunk(f"{DRAFT_SECTION}/{lens}", DRAFT_SECTION, lens, lens, text, "reflection"))
        shas["reflections"] = file_sha(rp)
    return chunks, shas


def source_shas(profile: Profile, transcript_path=None, reflections_path=None) -> dict:
    """The shas collect_chunks would report, from the files alone (no parsing, no embedding)."""
    shas = {"profile": profile.sha, "transcript": file_sha(transcript_path) if transcript_path else "",
            "reflections": ""}
    rp = _reflections_path(reflections_path)
    if REFLECTION_SECTION not in profile.sections and rp.exists():
        shas["reflections"] = file_sha(rp)
    return shas


def combined_sha(shas: dict) -> str:
    key = (f"profile:{shas.get('profile') or ''}|transcript:{shas.get('transcript') or ''}"
           f"|reflections:{shas.get('reflections') or ''}")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def source_counts(chunks) -> dict[str, int]:
    counts = {s: 0 for s in SOURCES}
    for c in chunks:
        counts[_source(c)] = counts.get(_source(c), 0) + 1
    return counts


# ---------------------------------------------------------------------------
# containment (leak) check: gold Eval answers vs transcript chunks
# ---------------------------------------------------------------------------
def _containment_pairs(profile: Profile, chunks) -> list[tuple[str, str, float]]:
    from .pipelines import evals  # lazy: evals imports this module

    gold = [(q.qid, evals.lexical_words(q.answer)) for q in profile.eval]
    gold = [(qid, words) for qid, words in gold if words]
    out: list[tuple[str, str, float]] = []
    for c in chunks:
        if _source(c) != "transcript":
            continue
        words = evals.lexical_words(_text(c))
        for qid, gw in gold:
            out.append((qid, _id(c), evals.containment(gw, words)))
    return out


def check_containment(profile: Profile, chunks, threshold: float = CONTAINMENT_THRESHOLD) -> list[tuple[str, str, float]]:
    """(qid, chunk_id, score) for every transcript chunk that contains more than `threshold` of a gold Eval
    answer's words (evals.containment over evals.lexical_words). Empty list = no leak."""
    return [(qid, cid, s) for qid, cid, s in _containment_pairs(profile, chunks) if s > threshold]


def max_containment(profile: Profile, chunks) -> float:
    return max((s for _, _, s in _containment_pairs(profile, chunks)), default=0.0)


def _leak_message(offenders: list[tuple[str, str, float]]) -> str:
    top = sorted(offenders, key=lambda x: -x[2])[:10]
    items = ", ".join(f"{qid} vs {cid} ({s:.2f})" for qid, cid, s in top)
    more = f" and {len(offenders) - len(top)} more" if len(offenders) > len(top) else ""
    return (f"containment check failed: {len(offenders)} transcript chunk(s) contain more than "
            f"{CONTAINMENT_THRESHOLD:.0%} of a gold Eval answer's words: {items}{more}. Move those turns into an "
            "excluded block (exclude_blocks in the transcript frontmatter) or reword the answer, then rebuild.")


# ---------------------------------------------------------------------------
# build / load
# ---------------------------------------------------------------------------
def build_index(index_key: str, profile: Profile, tab: str = "index", corpus=None) -> Path:
    """Embed the corpus into data/index_<key>.npz. `corpus` = (chunks, shas) from collect_chunks; None means
    profile-only (the profile's chunks, transcript/reflections shas "")."""
    key = INDEX_KEYS[index_key]
    chunks, shas = corpus if corpus is not None else _profile_corpus(profile)
    texts = [doc_text(index_key, c) for c in chunks]
    vecs = _normalise(embed_texts(index_key, texts, tab=tab))
    ids = np.array([_id(c) for c in chunks])
    source = np.array([_source(c) for c in chunks])
    out = index_path(index_key)
    np.savez(out, vectors=vecs, ids=ids, embedder=np.array(spec(key).name), sha=np.array(profile.sha),
             source=source, combined_sha=np.array(combined_sha(shas)))
    return out


def write_chunks(profile: Profile, corpus=None) -> Path:
    chunks, shas = corpus if corpus is not None else _profile_corpus(profile)
    payload = {
        "sha": profile.sha,
        "path": profile.path,
        "chunks": [_chunk_dict(c) for c in chunks],
        "shas": dict(shas),
        "combined_sha": combined_sha(shas),
    }
    CHUNKS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CHUNKS_PATH


def load_index(index_key: str) -> Index:
    with np.load(index_path(index_key), allow_pickle=False) as z:
        ids = [str(x) for x in z["ids"].tolist()]
        sha = str(z["sha"])
        keys = set(z.files)
        source = [str(x) for x in z["source"].tolist()] if "source" in keys else ["profile"] * len(ids)
        if len(source) != len(ids):
            source = [infer_source(i) for i in ids]
        combined = str(z["combined_sha"]) if "combined_sha" in keys else sha
        return Index(
            vectors=np.asarray(z["vectors"], dtype=np.float32),
            ids=ids,
            embedder=str(z["embedder"]),
            sha=sha,
            source=source,
            combined_sha=combined,
        )


def is_stale(index_key: str, profile: Profile) -> bool:
    p = index_path(index_key)
    if not p.exists():
        return True
    try:
        return load_index(index_key).sha != profile.sha
    except Exception:  # noqa: BLE001
        return True


def is_stale_sources(index_key: str, profile: Profile | None = None, transcript_path=None,
                     no_transcript: bool = False, reflections_path=None) -> bool:
    """True when the index file is missing or its combined_sha differs from the combined sha of the sources
    collect_chunks would use now (files only, no embedding). A real transcript without an up-to-date redacted
    copy counts as stale. `no_transcript=True` skips resolve_transcript_source's Mara-example fallback (for a
    persona that was deliberately built with no transcript at all)."""
    if not index_path(index_key).exists():
        return True
    try:
        idx = load_index(index_key)
        prof = profile if profile is not None else load_profile()
        if transcript_path:
            tp = Path(transcript_path)
        elif no_transcript:
            tp = None
        else:
            tp = resolve_transcript_source(quiet=True)
    except Exception:  # noqa: BLE001  (RedactionRequired, unreadable files)
        return True
    return idx.combined_sha != combined_sha(source_shas(prof, transcript_path=tp, reflections_path=reflections_path))


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def _sources_set(sources) -> set[str] | None:
    if sources is None:
        return None
    parts = [p.strip().lower() for p in sources.split(",")] if isinstance(sources, str) else list(sources)
    out = {str(p).strip().lower() for p in parts if str(p).strip()}
    bad = out - set(SOURCES)
    if bad:
        raise ValueError(f"unknown source(s) {sorted(bad)}; expected {SOURCES}")
    return out


def search(index_key: str, query: str, k: int = 5, boost: dict[str, float] | None = None,
           tab: str = "", sources=None) -> list[tuple[str, float]]:
    """Top-k (chunk_id, score). `boost` adds per-section offsets; `sources` (set/list/comma string of
    profile|transcript|reflection) masks every other row to -inf before the top-k, so only matching rows return."""
    allowed = _sources_set(sources)
    idx = load_index(index_key)
    q = _normalise(embed_texts(index_key, [query_text(index_key, query)], tab=tab))[0]
    scores = np.asarray(idx.vectors @ q, dtype=np.float32)
    if boost:
        for i, cid in enumerate(idx.ids):
            sec = cid.split("/", 1)[0]
            if sec in boost:
                scores[i] += boost[sec]
    if allowed is not None:
        mask = np.array([s not in allowed for s in idx.source], dtype=bool)
        if mask.shape[0] == scores.shape[0]:
            scores[mask] = -np.inf
    n = len(idx.ids)
    k = max(0, min(k, n))
    if k == 0:
        return []
    if k < n:
        top = np.argpartition(-scores, k - 1)[:k]
    else:
        top = np.arange(n)
    top = top[np.argsort(-scores[top])]
    return [(idx.ids[i], float(scores[i])) for i in top if np.isfinite(scores[i])]


def chunk_lookup() -> dict[str, dict]:
    if not CHUNKS_PATH.exists():
        return {}
    data = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data.get("chunks", [])}


def search_chunks(index_key: str, query: str, k: int = 5, boost=None, tab: str = "", sources=None) -> list[dict]:
    lookup = chunk_lookup()
    out = []
    for cid, score in search(index_key, query, k=k, boost=boost, tab=tab, sources=sources):
        c = dict(lookup.get(cid, {"id": cid, "section": cid.split("/")[0], "subsection": "", "title": cid, "text": ""}))
        c["source"] = c.get("source") or infer_source(cid)
        c["score"] = score
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# build all
# ---------------------------------------------------------------------------
def _stop_all_ollama() -> None:
    try:
        for e in clients.ollama.ps():
            name = e.get("name") or e.get("model")
            if name:
                try:
                    clients.ollama.stop(name)
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass


def _resolve_transcript(transcript_path, no_redact: bool, no_transcript: bool = False) -> Path | None:
    """`--transcript PATH` overrides the source, except that the raw real transcript (TRANSCRIPT_PATH) still goes
    through resolve_transcript_source, so it is never indexed unredacted without --no-redact.
    `no_transcript=True` means this persona has no transcript at all: skip resolve_transcript_source entirely so
    its Mara-example fallback never fires (it exists for the Mara demo profile, not for every profile)."""
    if no_transcript:
        print("transcript: none (no_transcript)")
        return None
    tp = Path(transcript_path) if transcript_path else None
    if tp is not None and TRANSCRIPT_PATH.exists() and _same_file(tp, TRANSCRIPT_PATH):
        tp = resolve_transcript_source(no_redact=no_redact)
    elif tp is None:
        tp = resolve_transcript_source(no_redact=no_redact)
    print(f"transcript: {tp}" if tp else "transcript: none")
    return tp


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _precheck_leaks(profile: Profile, tp: Path | None) -> None:
    """Containment check on the transcript chunks alone, run BEFORE the transcript reaches any model (the
    reflection pass), so a leaked Eval answer aborts the build before qwen3 sees it."""
    if tp is None:
        return
    chunks = transcript_mod.transcript_chunks(transcript_mod.load_transcript(tp))
    offenders = [p for p in _containment_pairs(profile, chunks) if p[2] > CONTAINMENT_THRESHOLD]
    if offenders:
        raise LeakError(_leak_message(offenders))


def _ensure_reflections(profile: Profile, tp: Path | None, force: bool) -> None:
    from .pipelines import reflect
    _precheck_leaks(profile, tp)
    text = reflect.transcript_text(transcript_mod.load_transcript(tp)) if tp else ""
    body = reflect.ensure_reflections(profile, text, force=force)
    print(f"reflections: {len(body)} chars ({', '.join(reflect.lenses_for(profile))}) -> {REFLECTIONS_PATH}")


def _checked_corpus(profile: Profile, tp: Path | None, reflections_path=None) -> tuple[list[Chunk], dict]:
    """collect_chunks + the containment check; raises LeakError before anything is embedded."""
    chunks, shas = collect_chunks(profile, transcript_path=tp, reflections_path=reflections_path)
    counts = source_counts(chunks)
    print(f"chunks: {len(chunks)} (profile {counts['profile']}, transcript {counts['transcript']}, "
          f"reflection {counts['reflection']})")
    pairs = _containment_pairs(profile, chunks)
    offenders = [p for p in pairs if p[2] > CONTAINMENT_THRESHOLD]
    if offenders:
        raise LeakError(_leak_message(offenders))
    if pairs:
        print(f"containment check: ok (max {max(s for _, _, s in pairs):.2f})")
    else:
        print("containment check: skipped (no transcript chunks)")
    return chunks, shas


def build_all(profile: Profile, with_digest: bool, force: bool = False, with_reflections: bool = False,
              transcript_path=None, no_redact: bool = False, no_transcript: bool = False,
              reflections_path=None) -> None:
    """Resolve the transcript -> (optionally) containment pre-check then draft the reflections with qwen3:8b ->
    collect chunks -> containment check (LeakError aborts before any embedding) -> build nomic, gemma, lms_nomic ->
    chunks.json -> (optionally) the digest. `force` rebuilds a cached digest/reflections. Every Ollama model is
    stopped afterwards. `no_transcript=True` skips the Mara-example transcript fallback for a persona that has
    none of its own; `reflections_path` redirects the "no Expert reflections section" draft fallback away from
    REFLECTIONS_PATH (which may hold another persona's draft) -- pass a nonexistent path to suppress it."""
    try:
        tp = _resolve_transcript(transcript_path, no_redact, no_transcript=no_transcript)
        if with_reflections:
            _ensure_reflections(profile, tp, force)
        corpus = _checked_corpus(profile, tp, reflections_path=reflections_path)
        for ik in ("nomic", "gemma", "lms_nomic"):
            p = build_index(ik, profile, corpus=corpus)
            print(f"built {ik}: {p}")
        print(f"wrote {write_chunks(profile, corpus)} ({len(corpus[0])} chunks)")
        if with_digest:
            from .pipelines.digest import ensure_digest
            d = ensure_digest(profile, force=force)
            print(f"digest: {len(d)} chars")
    finally:
        _stop_all_ollama()


def rebuild_digest(profile: Profile, force: bool = True) -> str:
    """Rebuild only the digest with qwen3:8b (force ignores a matching sha), then stop every Ollama model."""
    from .pipelines.digest import ensure_digest
    try:
        return ensure_digest(profile, force=force)
    finally:
        _stop_all_ollama()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m twin.index",
        description="Build or search the retrieval indexes over the profile, the redacted interview transcript "
                    "and the expert reflections.",
    )
    ap.add_argument("--build", choices=["all", "nomic", "gemma", "lms_nomic"],
                    help="build one index or all three (plus data/chunks.json)")
    ap.add_argument("--digest", action="store_true", help="also build the qwen3:8b digest (cached by profile sha)")
    ap.add_argument("--reflect", action="store_true",
                    help="also draft data/reflections.md with qwen3:8b, one call per lens (cached by profile + transcript sha)")
    ap.add_argument("--force", action="store_true", help="rebuild even when up to date (digest and reflections too)")
    ap.add_argument("--transcript", metavar="PATH",
                    help="transcript file to index (default: the redacted real transcript, else the example)")
    ap.add_argument("--no-redact", action="store_true",
                    help="index data/interview_transcript.md even without an up-to-date redacted copy")
    ap.add_argument("--search", metavar="QUERY", help="embed the query and print the top-k chunk ids")
    ap.add_argument("--index", default="nomic", choices=list(INDEX_KEYS), help="index to search (default nomic)")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--sources", metavar="LIST",
                    help="restrict --search to a comma list of profile,transcript,reflection")
    args = ap.parse_args(argv)
    try:
        sources = _sources_set(args.sources)
    except ValueError as e:
        ap.error(str(e))

    if args.build:
        profile = load_profile()
        print(f"profile: {profile.path} ({profile.name}, sha {profile.sha[:12]}, {len(profile.chunks)} chunks)")
        if args.build == "all":
            try:
                build_all(profile, with_digest=args.digest, force=args.force, with_reflections=args.reflect,
                          transcript_path=args.transcript, no_redact=args.no_redact)
            except (RedactionRequired, LeakError) as e:
                print(f"error: {e}")
                return 2
        else:
            try:
                tp = _resolve_transcript(args.transcript, args.no_redact)
                if args.reflect:
                    _ensure_reflections(profile, tp, args.force)
                corpus = _checked_corpus(profile, tp)
                if args.force or is_stale(args.build, profile) or is_stale_sources(args.build, profile, tp):
                    print(f"built {args.build}: {build_index(args.build, profile, corpus=corpus)}")
                else:
                    print(f"{args.build} up to date")
                write_chunks(profile, corpus)
                if args.digest:
                    from .pipelines.digest import ensure_digest
                    ensure_digest(profile, force=args.force)
            except (RedactionRequired, LeakError) as e:
                print(f"error: {e}")
                return 2
            finally:
                _stop_all_ollama()
    if args.search:
        lookup = chunk_lookup()
        try:
            hits = search(args.index, args.search, k=args.k, tab="cli", sources=sources)
            for rank, (cid, score) in enumerate(hits, 1):
                c = lookup.get(cid, {})
                print(f"{rank} {score:.4f} {cid} [{c.get('source') or infer_source(cid)}] | {c.get('title', cid)}")
            if not hits:
                print("no results" + (f" for sources {sorted(sources)}" if sources else ""))
        finally:
            _stop_all_ollama()
    if not args.build and not args.search:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
