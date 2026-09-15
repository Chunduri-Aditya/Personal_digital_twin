"""Hermetic tests for twin.index v2: sources, combined sha, transcript resolution, the containment (leak) check,
npz/chunks.json layout, source masking in search, staleness, build_all ordering and the CLI.

`index.embed_texts` is replaced by a deterministic fake (no model is ever loaded), `_stop_all_ollama` by a
recorder, and every data path by a tmp file, so data/ is never written. No network, no GPU.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from twin import clients, gpu, index
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH, EXAMPLE_TRANSCRIPT_PATH
from twin.pipelines import digest, reflect
from twin.profile import Chunk, load_profile

FOUR = ("Psychologist", "Behavioral economist", "Political scientist", "Demographer")


class _Forbidden:
    """Any attribute access means a real HTTP call was attempted."""

    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via clients.{name}")


def _vec(text: str, dim: int) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    return np.random.default_rng(seed).standard_normal(dim).astype(np.float32)


class FakeEmbed:
    """Stands in for index.embed_texts: deterministic vectors per text, records every call."""

    def __init__(self, dim: int = 8, log: list | None = None):
        self.calls: list[dict] = []
        self.dim = dim
        self.query_vec = None
        self.log = log

    def __call__(self, index_key, texts, tab=""):
        self.calls.append({"index_key": index_key, "texts": list(texts), "tab": tab})
        if self.log is not None:
            self.log.append(("embed", index_key))
        if self.query_vec is not None and len(texts) == 1:
            return np.array([self.query_vec], dtype=np.float32)
        return np.stack([_vec(t, self.dim) for t in texts])


@pytest.fixture(scope="module")
def mara():
    return load_profile(EXAMPLE_PROFILE_V2_PATH)


@pytest.fixture(scope="module")
def ari():
    return load_profile(EXAMPLE_PROFILE_PATH)


@pytest.fixture
def env(monkeypatch, tmp_path: Path, mara, ari):
    fake = FakeEmbed()
    stops: list[int] = []
    monkeypatch.setattr(index, "embed_texts", fake)
    monkeypatch.setattr(index, "_stop_all_ollama", lambda: stops.append(1))
    monkeypatch.setattr(index, "DATA_DIR", tmp_path)
    monkeypatch.setattr(index, "CHUNKS_PATH", tmp_path / "chunks.json")
    monkeypatch.setattr(index, "REFLECTIONS_PATH", tmp_path / "reflections.md")
    monkeypatch.setattr(index, "TRANSCRIPT_PATH", tmp_path / "interview_transcript.md")
    monkeypatch.setattr(index, "REDACTED_TRANSCRIPT_PATH", tmp_path / "interview_transcript.redacted.md")
    monkeypatch.setattr(index, "EXAMPLE_TRANSCRIPT_PATH", tmp_path / "interview_transcript.example.md")
    monkeypatch.setattr(index, "EXAMPLE_REDACTED_TRANSCRIPT_PATH",
                        tmp_path / "interview_transcript.example.redacted.md")
    monkeypatch.setattr(clients, "ollama", _Forbidden())
    monkeypatch.setattr(clients, "lms", _Forbidden())
    example = tmp_path / "example_copy.md"
    shutil.copy(EXAMPLE_TRANSCRIPT_PATH, example)
    return SimpleNamespace(embed=fake, stops=stops, tmp=tmp_path, example=example, mara=mara, ari=ari,
                           real=tmp_path / "interview_transcript.md",
                           redacted=tmp_path / "interview_transcript.redacted.md",
                           ex=tmp_path / "interview_transcript.example.md",
                           ex_redacted=tmp_path / "interview_transcript.example.redacted.md",
                           reflections=tmp_path / "reflections.md", chunks_json=tmp_path / "chunks.json")


def _redacted_copy(src: Path, dst: Path, sha: str | None = None) -> None:
    text = src.read_text(encoding="utf-8")
    sha = sha or hashlib.sha256(src.read_bytes()).hexdigest()
    dst.write_text(text.replace("---\n", f"---\nredacted: true\nsource_sha: {sha}\n", 1), encoding="utf-8")


def _leak_transcript(profile) -> str:
    gold = {q.qid: q for q in profile.eval}
    return ("---\nname: Mara Ellison\ndate: 2026-09-14\nblocks: 2\nexclude_blocks: [2]\n---\n"
            "# Block 1: Leak\n"
            f"## T-001\nQ: {gold['Q-01'].question}\nA: {gold['Q-01'].answer}\n"
            "## T-002\nQ: what else?\nA: nothing that overlaps, just rain and coffee and a grumpy cat.\n"
            "# Block 2: Gold\n"
            f"## T-003\nQ: {gold['Q-02'].question}\nA: {gold['Q-02'].answer}\n")


def _write_npz(key, ids, sources, vectors, sha="profsha", combined="comb", embedder="nomic-embed-text"):
    np.savez(index.index_path(key), vectors=np.asarray(vectors, dtype=np.float32), ids=np.array(ids),
             embedder=np.array(embedder), sha=np.array(sha), source=np.array(sources), combined_sha=np.array(combined))


# ---------------------------------------------------------------------------
# constants and helpers
# ---------------------------------------------------------------------------

def test_constants_and_error_types():
    assert index.INDEX_KEYS == {"nomic": "nomic_ollama", "gemma": "embeddinggemma", "lms_nomic": "nomic_lms"}
    assert index.SOURCES == ("profile", "transcript", "reflection")
    assert index.CONTAINMENT_THRESHOLD == 0.6
    assert index.REFLECTION_SECTION == "Expert reflections" and index.DRAFT_SECTION == "Reflections"
    assert issubclass(index.LeakError, RuntimeError) and issubclass(index.RedactionRequired, RuntimeError)


def test_infer_source_and_chunk_dict():
    assert index.infer_source("Identity") == "profile"
    assert index.infer_source("Interview/T-012a") == "transcript"
    assert index.infer_source("Expert reflections/Psychologist") == "reflection"
    assert index.infer_source("Reflections/Demographer") == "reflection"
    assert index.infer_source("") == "profile"
    c = Chunk("Interview/T-001", "Interview", "T-001", "T-001: x", "Q: q\nA: a", "transcript")
    assert index._chunk_dict(c) == {"id": "Interview/T-001", "section": "Interview", "subsection": "T-001",
                                    "title": "T-001: x", "text": "Q: q\nA: a", "source": "transcript"}
    assert index._chunk_dict({"id": "Interview/T-002", "text": "t"})["source"] == "transcript"
    assert index._source({"id": "Identity", "source": "reflection"}) == "reflection"
    assert index.source_counts([c, {"id": "Identity"}]) == {"profile": 1, "transcript": 1, "reflection": 0}


def test_normalise_unit_rows_and_zero_rows():
    v = index._normalise(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert v.dtype == np.float32
    assert v[0].tolist() == pytest.approx([0.6, 0.8]) and v[1].tolist() == [0.0, 0.0]


# ---------------------------------------------------------------------------
# collect_chunks, shas
# ---------------------------------------------------------------------------

def test_collect_chunks_profile_only_tags_expert_reflections(env):
    chunks, shas = index.collect_chunks(env.mara)
    assert index.source_counts(chunks) == {"profile": 57, "transcript": 0, "reflection": 4}
    assert shas == {"profile": env.mara.sha, "transcript": "", "reflections": ""}
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.source == ("reflection" if c.section == "Expert reflections" else "profile"), c.id
    assert [c.id for c in chunks] == [c.id for c in env.mara.chunks]
    assert all(c.source == "profile" for c in env.mara.chunks), "the profile's own chunks are not mutated"
    assert not [c for c in chunks if c.id.startswith("Reflections/")]
    assert index.combined_sha(shas) == index.combined_sha({"profile": env.mara.sha})


def test_collect_chunks_with_transcript_prints_excluded_count(env, capsys):
    chunks, shas = index.collect_chunks(env.mara, transcript_path=env.example)
    assert "excluded blocks: 1 (turns skipped: 22)" in capsys.readouterr().out
    assert index.source_counts(chunks) == {"profile": 57, "transcript": 40, "reflection": 4}
    assert shas["profile"] == env.mara.sha
    assert shas["transcript"] == hashlib.sha256(env.example.read_bytes()).hexdigest()
    assert shas["reflections"] == ""
    tr = [c for c in chunks if c.source == "transcript"]
    assert all(c.id.startswith("Interview/T-0") and c.section == "Interview" for c in tr)
    assert not [c for c in tr if int(c.subsection[2:5]) >= 39], "block 7 turns never become chunks"
    assert index.source_shas(env.mara, transcript_path=env.example) == shas


def test_reflections_draft_indexed_only_when_profile_lacks_the_section(env):
    env.reflections.write_text("<!-- sha: k -->\n## Psychologist\ndraft one\n\n## Demographer\ndraft two\n",
                               encoding="utf-8")
    chunks, shas = index.collect_chunks(env.ari)
    drafts = [c for c in chunks if c.section == "Reflections"]
    assert [c.id for c in drafts] == ["Reflections/Psychologist", "Reflections/Demographer"]
    assert all(c.source == "reflection" for c in drafts)
    assert drafts[0].subsection == "Psychologist" and drafts[0].title == "Psychologist" and drafts[0].text == "draft one"
    assert index.source_counts(chunks) == {"profile": 42, "transcript": 0, "reflection": 2}
    assert shas["reflections"] == hashlib.sha256(env.reflections.read_bytes()).hexdigest()
    assert index.source_shas(env.ari) == shas
    # the Mara profile has '# Expert reflections' (D2 wins): the draft is ignored and its sha stays ""
    chunks_m, shas_m = index.collect_chunks(env.mara)
    assert not [c for c in chunks_m if c.section == "Reflections"] and shas_m["reflections"] == ""
    # an explicit reflections_path wins over REFLECTIONS_PATH
    other = env.tmp / "other.md"
    other.write_text("<!-- sha: z -->\n## Behavioral economist\nbe\n", encoding="utf-8")
    chunks_o, shas_o = index.collect_chunks(env.ari, reflections_path=other)
    assert [c.id for c in chunks_o if c.section == "Reflections"] == ["Reflections/Behavioral economist"]
    assert shas_o["reflections"] == hashlib.sha256(other.read_bytes()).hexdigest()
    # a missing draft file contributes nothing
    env.reflections.unlink()
    assert index.collect_chunks(env.ari)[1]["reflections"] == ""


def test_combined_sha_formula():
    shas = {"profile": "p" * 64, "transcript": "t" * 64, "reflections": "r" * 64}
    want = hashlib.sha256(f"profile:{'p' * 64}|transcript:{'t' * 64}|reflections:{'r' * 64}".encode()).hexdigest()
    assert index.combined_sha(shas) == want
    assert index.combined_sha({"profile": "p"}) == hashlib.sha256(b"profile:p|transcript:|reflections:").hexdigest()
    assert index.combined_sha({"profile": "p", "transcript": None}) == index.combined_sha({"profile": "p"})
    assert index.combined_sha({"profile": "p"}) != index.combined_sha({"profile": "p", "transcript": "t"})
    assert index.file_sha(None) == "" and index.file_sha("Z:/definitely/missing.md") == ""


# ---------------------------------------------------------------------------
# resolve_transcript_source
# ---------------------------------------------------------------------------

def test_resolve_real_transcript_requires_a_matching_redacted_copy(env):
    shutil.copy(env.example, env.real)
    with pytest.raises(index.RedactionRequired, match="run python -m twin.redact data/interview_transcript.md first"):
        index.resolve_transcript_source()
    assert index.resolve_transcript_source(no_redact=True) == env.real
    # a redacted copy whose source_sha does not match the real bytes is stale -> still required
    _redacted_copy(env.example, env.redacted, sha="0" * 64)
    with pytest.raises(index.RedactionRequired, match="out of date"):
        index.resolve_transcript_source()
    assert index.resolve_transcript_source(no_redact=True) == env.real
    # matching source_sha -> the redacted file, whatever no_redact says
    _redacted_copy(env.real, env.redacted)
    assert index.resolve_transcript_source() == env.redacted
    assert index.resolve_transcript_source(no_redact=True) == env.redacted
    # editing the real file invalidates the copy again
    env.real.write_text(env.real.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(index.RedactionRequired):
        index.resolve_transcript_source()


def test_resolve_example_fallbacks(env, capsys):
    assert index.resolve_transcript_source() is None
    shutil.copy(env.example, env.ex)
    assert index.resolve_transcript_source() == env.ex
    assert "example transcript (synthetic), unredacted" in capsys.readouterr().out
    index.resolve_transcript_source(quiet=True)
    assert capsys.readouterr().out == ""
    _redacted_copy(env.ex, env.ex_redacted, sha="f" * 64)     # stale copy -> the example itself
    assert index.resolve_transcript_source() == env.ex
    _redacted_copy(env.ex, env.ex_redacted)
    assert index.resolve_transcript_source() == env.ex_redacted
    assert capsys.readouterr().out.count("unredacted") == 1


# ---------------------------------------------------------------------------
# containment
# ---------------------------------------------------------------------------

def test_check_containment_flags_a_planted_leak(env):
    leak = env.tmp / "leak.md"
    leak.write_text(_leak_transcript(env.mara), encoding="utf-8")
    chunks, _ = index.collect_chunks(env.mara, transcript_path=leak)
    ids = [c.id for c in chunks if c.source == "transcript"]
    assert ids == ["Interview/T-001", "Interview/T-002"], "block 2 (gold) is excluded"
    offenders = index.check_containment(env.mara, chunks)
    assert ("Q-01", "Interview/T-001", 1.0) in offenders
    assert all(cid == "Interview/T-001" for _, cid, _ in offenders)
    assert all(s > 0.6 for _, _, s in offenders)
    assert index.max_containment(env.mara, chunks) == 1.0
    assert index.check_containment(env.mara, chunks, threshold=1.0) == []
    msg = index._leak_message(offenders)
    assert "Q-01 vs Interview/T-001 (1.00)" in msg and "exclude_blocks" in msg
    # profile-only corpora have nothing to check
    assert index.check_containment(env.mara, env.mara.chunks) == []
    assert index.max_containment(env.mara, env.mara.chunks) == 0.0


def test_check_containment_passes_the_example(env):
    chunks, _ = index.collect_chunks(env.mara, transcript_path=env.example)
    assert index.check_containment(env.mara, chunks) == []
    m = index.max_containment(env.mara, chunks)
    assert 0.0 < m <= 0.6
    assert m == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# build_index / write_chunks / load_index
# ---------------------------------------------------------------------------

def test_build_index_with_corpus_writes_source_and_combined_sha(env):
    corpus = index.collect_chunks(env.mara, transcript_path=env.example)
    chunks, shas = corpus
    out = index.build_index("nomic", env.mara, tab="index", corpus=corpus)
    assert out == env.tmp / "index_nomic.npz" and out.exists()
    assert len(env.embed.calls) == 1
    call = env.embed.calls[0]
    assert call["index_key"] == "nomic" and call["tab"] == "index" and len(call["texts"]) == 101
    assert call["texts"] == [f"search_document: {c.text}" for c in chunks]
    with np.load(out, allow_pickle=False) as z:
        assert set(z.files) == {"vectors", "ids", "embedder", "sha", "source", "combined_sha"}
        assert z["vectors"].shape == (101, 8) and z["vectors"].dtype == np.float32
        assert np.allclose(np.linalg.norm(z["vectors"], axis=1), 1.0, atol=1e-5)
        assert z["ids"].tolist() == [c.id for c in chunks]
        assert z["source"].tolist() == [c.source for c in chunks]
        assert str(z["sha"]) == env.mara.sha
        assert str(z["combined_sha"]) == index.combined_sha(shas)
        assert str(z["embedder"]) == "nomic-embed-text"
    idx = index.load_index("nomic")
    assert idx.ids == [c.id for c in chunks] and idx.source == [c.source for c in chunks]
    assert idx.sha == env.mara.sha and idx.combined_sha == index.combined_sha(shas)
    assert idx.embedder == "nomic-embed-text" and idx.vectors.shape == (101, 8)
    assert idx.source.count("transcript") == 40 and idx.source.count("reflection") == 4
    # gemma and lms_nomic use their own doc prefixes and embedder names
    index.build_index("gemma", env.mara, corpus=corpus)
    index.build_index("lms_nomic", env.mara, corpus=corpus)
    assert env.embed.calls[1]["texts"][0].startswith("title: Identity | text: ")
    assert env.embed.calls[2]["texts"][0].startswith("search_document: ")
    assert index.load_index("gemma").embedder == "embeddinggemma:300m-qat-q4_0"
    assert index.load_index("lms_nomic").embedder == "text-embedding-nomic-embed-text-v1.5"


def test_build_index_profile_only_default_keeps_phase_one_shape(env):
    out = index.build_index("nomic", env.mara)
    idx = index.load_index("nomic")
    assert out.exists() and len(idx.ids) == 61 and idx.ids == [c.id for c in env.mara.chunks]
    assert idx.source.count("profile") == 57 and idx.source.count("reflection") == 4
    assert idx.combined_sha == index.combined_sha({"profile": env.mara.sha, "transcript": "", "reflections": ""})
    assert idx.sha == env.mara.sha
    ari_idx_path = index.build_index("gemma", env.ari)
    a = index.load_index("gemma")
    assert ari_idx_path.exists() and len(a.ids) == 42 and a.source == ["profile"] * 42


def test_load_index_defaults_for_old_npz_without_source_or_combined_sha(env):
    np.savez(index.index_path("gemma"), vectors=np.eye(2, dtype=np.float32), ids=np.array(["Identity", "Values"]),
             embedder=np.array("embeddinggemma:300m-qat-q4_0"), sha=np.array("abc"))
    idx = index.load_index("gemma")
    assert isinstance(idx, index.Index)
    assert idx.ids == ["Identity", "Values"] and idx.sha == "abc"
    assert idx.source == ["profile", "profile"]
    assert idx.combined_sha == "abc", "old files: combined_sha defaults to the profile sha"
    assert idx.embedder == "embeddinggemma:300m-qat-q4_0" and idx.vectors.dtype == np.float32
    # a source array of the wrong length is replaced by ids-based inference
    np.savez(index.index_path("nomic"), vectors=np.eye(2, dtype=np.float32),
             ids=np.array(["Identity", "Interview/T-001"]), embedder=np.array("nomic-embed-text"),
             sha=np.array("abc"), source=np.array(["profile"]))
    assert index.load_index("nomic").source == ["profile", "transcript"]
    with pytest.raises(FileNotFoundError):
        index.load_index("lms_nomic")


def test_write_chunks_and_chunk_lookup(env):
    corpus = index.collect_chunks(env.mara, transcript_path=env.example)
    chunks, shas = corpus
    p = index.write_chunks(env.mara, corpus)
    assert p == env.chunks_json and p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert set(data) == {"sha", "path", "chunks", "shas", "combined_sha"}
    assert data["sha"] == env.mara.sha and data["path"] == env.mara.path
    assert data["shas"] == shas and data["combined_sha"] == index.combined_sha(shas)
    assert len(data["chunks"]) == 101
    for d, c in zip(data["chunks"], chunks):
        assert set(d) == {"id", "section", "subsection", "title", "text", "source"}
        assert d["id"] == c.id and d["source"] == c.source and d["text"] == c.text
    lookup = index.chunk_lookup()
    assert lookup["Interview/T-004a"]["source"] == "transcript"
    assert lookup["Expert reflections/Psychologist"]["source"] == "reflection"
    assert lookup["Identity"]["source"] == "profile"
    # profile-only default
    index.write_chunks(env.ari)
    data2 = json.loads(env.chunks_json.read_text(encoding="utf-8"))
    assert len(data2["chunks"]) == 42 and data2["shas"] == {"profile": env.ari.sha, "transcript": "", "reflections": ""}
    env.chunks_json.unlink()
    assert index.chunk_lookup() == {}


# ---------------------------------------------------------------------------
# search with source masking
# ---------------------------------------------------------------------------

@pytest.fixture
def small_index(env):
    ids = ["Identity", "Interview/T-001", "Expert reflections/Psychologist", "Decisions/D-01"]
    sources = ["profile", "transcript", "reflection", "profile"]
    _write_npz("nomic", ids, sources, np.eye(4), sha=env.mara.sha)
    _write_npz("gemma", ids, sources, np.eye(4), sha=env.mara.sha, embedder="embeddinggemma:300m-qat-q4_0")
    env.embed.query_vec = np.array([0.2, 1.0, 0.5, 0.1], dtype=np.float32)
    index.write_chunks(env.mara, ([
        Chunk("Identity", "Identity", "", "Identity", "id text", "profile"),
        Chunk("Expert reflections/Psychologist", "Expert reflections", "Psychologist", "Psychologist", "psy", "reflection"),
        Chunk("Decisions/D-01", "Decisions", "D-01", "D-01: Quit", "quit", "profile"),
    ], {"profile": env.mara.sha, "transcript": "", "reflections": ""}))
    return SimpleNamespace(ids=ids, sources=sources)


def test_search_masks_sources_before_top_k(env, small_index):
    allv = index.search("nomic", "what phone", k=4)
    assert [cid for cid, _ in allv] == ["Interview/T-001", "Expert reflections/Psychologist", "Identity", "Decisions/D-01"]
    assert allv[0][1] == pytest.approx(1.0 / np.linalg.norm([0.2, 1.0, 0.5, 0.1]), abs=1e-5)
    assert env.embed.calls[-1]["texts"] == ["search_query: what phone"] and env.embed.calls[-1]["tab"] == ""
    # k=1 with a source filter must return the best PROFILE row: masking happens before the top-k cut
    assert [cid for cid, _ in index.search("nomic", "q", k=1, sources={"profile"})] == ["Identity"]
    assert [cid for cid, _ in index.search("nomic", "q", k=5, sources={"profile"})] == ["Identity", "Decisions/D-01"]
    assert [cid for cid, _ in index.search("nomic", "q", k=5, sources=["transcript"])] == ["Interview/T-001"]
    assert [cid for cid, _ in index.search("nomic", "q", k=5, sources="transcript, reflection")] == [
        "Interview/T-001", "Expert reflections/Psychologist"]
    assert [cid for cid, _ in index.search("nomic", "q", k=5, sources=("reflection",))] == [
        "Expert reflections/Psychologist"]
    assert index.search("nomic", "q", k=0) == []
    assert all(np.isfinite(s) for _, s in index.search("nomic", "q", k=4, sources={"profile"}))
    # boost still applies on top of the mask
    boosted = index.search("nomic", "q", k=5, boost={"Decisions": 5.0}, sources={"profile"})
    assert [cid for cid, _ in boosted] == ["Decisions/D-01", "Identity"]
    assert [cid for cid, _ in index.search("nomic", "q", k=5, boost={"Decisions": 5.0})][0] == "Decisions/D-01"
    # gemma gets its own query prefix
    index.search("gemma", "what phone", k=1, tab="cli")
    assert env.embed.calls[-1]["texts"] == ["task: search result | query: what phone"]
    assert env.embed.calls[-1]["index_key"] == "gemma" and env.embed.calls[-1]["tab"] == "cli"


def test_search_rejects_unknown_sources(env, small_index):
    with pytest.raises(ValueError, match="unknown source"):
        index.search("nomic", "q", sources={"profile", "bogus"})
    with pytest.raises(ValueError):
        index._sources_set("transcripts")
    assert index._sources_set(None) is None
    assert index._sources_set("Profile, TRANSCRIPT,") == {"profile", "transcript"}
    assert env.embed.calls == [], "validation happens before any embedding"


def test_search_chunks_carries_source_and_passes_the_filter(env, small_index):
    rows = index.search_chunks("nomic", "q", k=4)
    assert [r["id"] for r in rows] == ["Interview/T-001", "Expert reflections/Psychologist", "Identity", "Decisions/D-01"]
    assert [r["source"] for r in rows] == ["transcript", "reflection", "profile", "profile"]
    assert rows[0]["title"] == "Interview/T-001" and rows[0]["text"] == "", "unknown id: inferred source, empty text"
    assert rows[2]["text"] == "id text" and "score" in rows[2]
    only = index.search_chunks("nomic", "q", k=4, sources={"reflection"}, tab="decide")
    assert [r["id"] for r in only] == ["Expert reflections/Psychologist"] and only[0]["source"] == "reflection"
    assert env.embed.calls[-1]["tab"] == "decide"


# ---------------------------------------------------------------------------
# staleness
# ---------------------------------------------------------------------------

def test_is_stale_and_is_stale_sources(env):
    assert index.is_stale("nomic", env.ari) is True
    assert index.is_stale_sources("nomic", env.ari) is True
    index.build_index("nomic", env.ari)
    assert index.is_stale("nomic", env.ari) is False and index.is_stale("nomic", env.mara) is True
    assert index.is_stale_sources("nomic", env.ari) is False
    assert index.is_stale_sources("nomic", env.mara) is True
    # a new reflections draft (Ari has no '# Expert reflections') changes the combined sha
    env.reflections.write_text("<!-- sha: k -->\n## Psychologist\nx\n", encoding="utf-8")
    assert index.is_stale_sources("nomic", env.ari) is True
    env.reflections.unlink()
    assert index.is_stale_sources("nomic", env.ari) is False
    # a transcript that the build did not include
    assert index.is_stale_sources("nomic", env.ari, transcript_path=env.example) is True
    corpus = index.collect_chunks(env.ari, transcript_path=env.example)
    index.build_index("nomic", env.ari, corpus=corpus)
    assert index.is_stale_sources("nomic", env.ari, transcript_path=env.example) is False
    assert index.is_stale_sources("nomic", env.ari) is True
    # a real transcript without an up-to-date redacted copy counts as stale (RedactionRequired inside)
    shutil.copy(env.example, env.real)
    assert index.is_stale_sources("nomic", env.ari) is True
    _redacted_copy(env.real, env.redacted)
    assert index.is_stale_sources("nomic", env.ari) is True   # the redacted bytes differ from the example copy
    corpus = index.collect_chunks(env.ari, transcript_path=env.redacted)
    index.build_index("nomic", env.ari, corpus=corpus)
    assert index.is_stale_sources("nomic", env.ari) is False
    # a corrupt file is stale, not an exception
    index.index_path("nomic").write_bytes(b"garbage")
    assert index.is_stale("nomic", env.ari) is True and index.is_stale_sources("nomic", env.ari) is True


# ---------------------------------------------------------------------------
# build_all
# ---------------------------------------------------------------------------

def test_build_all_leak_aborts_before_any_embedding(env, capsys):
    leak = env.tmp / "leak.md"
    leak.write_text(_leak_transcript(env.mara), encoding="utf-8")
    with pytest.raises(index.LeakError, match="containment check failed") as e:
        index.build_all(env.mara, with_digest=False, transcript_path=leak)
    assert "Q-01 vs Interview/T-001 (1.00)" in str(e.value)
    assert env.embed.calls == [], "nothing may be embedded once a leak is found"
    assert env.stops == [1], "_stop_all_ollama runs in the finally block"
    assert not index.index_path("nomic").exists() and not env.chunks_json.exists()
    out = capsys.readouterr().out
    assert f"transcript: {leak}" in out and "excluded blocks: 1 (turns skipped: 1)" in out
    assert "chunks: 63 (profile 57, transcript 2, reflection 4)" in out
    assert "containment check: ok" not in out


def test_build_all_redaction_required_aborts_before_any_embedding(env):
    shutil.copy(env.example, env.real)
    with pytest.raises(index.RedactionRequired):
        index.build_all(env.mara, with_digest=False)
    assert env.embed.calls == [] and env.stops == [1]
    # --no-redact reads the real file
    index.build_all(env.mara, with_digest=False, no_redact=True)
    assert [c["index_key"] for c in env.embed.calls] == ["nomic", "gemma", "lms_nomic"] and env.stops == [1, 1]


def test_build_all_happy_path_prints_counts_and_containment(env, capsys):
    index.build_all(env.mara, with_digest=False, transcript_path=env.example)
    out = capsys.readouterr().out
    assert f"transcript: {env.example}" in out
    assert "excluded blocks: 1 (turns skipped: 22)" in out
    assert "chunks: 101 (profile 57, transcript 40, reflection 4)" in out
    assert "containment check: ok (max 0.50)" in out
    for ik in ("nomic", "gemma", "lms_nomic"):
        assert f"built {ik}: {index.index_path(ik)}" in out
        assert index.load_index(ik).source.count("transcript") == 40
    assert f"wrote {env.chunks_json} (101 chunks)" in out
    assert "digest" not in out
    assert [c["index_key"] for c in env.embed.calls] == ["nomic", "gemma", "lms_nomic"]
    assert all(len(c["texts"]) == 101 and c["tab"] == "index" for c in env.embed.calls)
    assert env.stops == [1]
    data = json.loads(env.chunks_json.read_text(encoding="utf-8"))
    assert data["combined_sha"] == index.load_index("nomic").combined_sha
    assert data["shas"]["transcript"] == hashlib.sha256(env.example.read_bytes()).hexdigest()


def test_build_all_reflect_then_embed_then_digest_in_order(env, monkeypatch, capsys):
    log: list = []
    env.embed.log = log

    draft = "## Psychologist\ndraft\n\n## Demographer\nd2"

    def fake_ensure_reflections(profile, text, force=False):
        log.append(("reflect", profile.name, text, force))
        env.reflections.write_text(f"<!-- sha: k -->\n{draft}\n", encoding="utf-8")
        return draft

    monkeypatch.setattr(reflect, "ensure_reflections", fake_ensure_reflections)
    monkeypatch.setattr(digest, "ensure_digest", lambda profile, force=False: log.append(("digest", force)) or "dig")
    index.build_all(env.ari, with_digest=True, force=True, with_reflections=True)
    assert log == [("reflect", "Ari", "", True), ("embed", "nomic"), ("embed", "gemma"), ("embed", "lms_nomic"),
                   ("digest", True)]
    out = capsys.readouterr().out
    assert "transcript: none" in out
    assert f"reflections: {len(draft)} chars (Psychologist, Behavioral economist, Demographer) -> {env.reflections}" in out
    assert "chunks: 44 (profile 42, transcript 0, reflection 2)" in out
    assert "containment check: skipped (no transcript chunks)" in out
    assert "digest: 3 chars" in out
    idx = index.load_index("nomic")
    assert idx.ids[-2:] == ["Reflections/Psychologist", "Reflections/Demographer"]
    assert idx.source[-2:] == ["reflection", "reflection"]
    assert idx.combined_sha == index.combined_sha({"profile": env.ari.sha, "transcript": "",
                                                   "reflections": index.file_sha(env.reflections)})
    assert env.stops == [1]


def test_build_all_reflections_receive_included_turns_only(env, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(reflect, "ensure_reflections", lambda profile, text, force=False: seen.append(text) or "")
    index.build_all(env.mara, with_digest=False, with_reflections=True, transcript_path=env.example)
    assert len(seen) == 1
    assert "## T-001" in seen[0] and "## T-038" in seen[0] and "## T-039" not in seen[0]
    assert seen[0] == reflect.transcript_text(__import__("twin.transcript", fromlist=["x"]).load_transcript(env.example))


def test_build_all_leak_aborts_before_reflections_see_the_transcript(env, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(reflect, "ensure_reflections", lambda profile, text, force=False: seen.append(text) or "")
    leak = env.tmp / "leak.md"
    leak.write_text(_leak_transcript(env.mara), encoding="utf-8")
    with pytest.raises(index.LeakError, match="Q-01 vs Interview/T-001"):
        index.build_all(env.mara, with_digest=False, with_reflections=True, transcript_path=leak)
    assert seen == [], "the reflection model must not receive a transcript that leaks an Eval answer"
    assert env.embed.calls == [] and env.stops == [1]


def test_transcript_override_of_the_real_file_still_requires_redaction(env):
    shutil.copy(env.example, env.real)
    with pytest.raises(index.RedactionRequired):
        index.build_all(env.mara, with_digest=False, transcript_path=str(env.real))
    assert env.embed.calls == []
    index.build_all(env.mara, with_digest=False, transcript_path=str(env.real), no_redact=True)
    assert [c["index_key"] for c in env.embed.calls] == ["nomic", "gemma", "lms_nomic"]
    _redacted_copy(env.real, env.redacted)
    env.embed.calls.clear()
    index.build_all(env.mara, with_digest=False, transcript_path=str(env.real))
    data = json.loads(env.chunks_json.read_text(encoding="utf-8"))
    assert data["shas"]["transcript"] == hashlib.sha256(env.redacted.read_bytes()).hexdigest()


def test_build_all_no_transcript_skips_the_example_fallback(env, capsys):
    """A persona with no transcript of its own (twin.personas) must never pick up Mara's example transcript just
    because it happens to sit at EXAMPLE_TRANSCRIPT_PATH: no_transcript=True skips resolve_transcript_source
    entirely. Without it, the default fallback still fires (documenting the behaviour no_transcript opts out of)."""
    shutil.copy(env.example, env.ex)
    index.build_all(env.ari, with_digest=False)
    assert "example transcript (synthetic), unredacted" in capsys.readouterr().out
    assert index.load_index("nomic").source.count("transcript") > 0

    index.build_all(env.ari, with_digest=False, no_transcript=True)
    assert "transcript: none (no_transcript)" in capsys.readouterr().out
    assert index.load_index("nomic").source.count("transcript") == 0


def test_build_all_reflections_path_redirects_the_draft_fallback(env):
    """reflections_path lets build_all read a DIFFERENT (or no) reflections draft instead of always
    REFLECTIONS_PATH: the other half of the same contamination bug, where a persona with no "Expert reflections"
    section would otherwise silently pick up another persona's stale data/reflections.md draft."""
    env.reflections.write_text("<!-- sha: abc -->\n## Psychologist\nanother persona's draft\n", encoding="utf-8")
    index.build_all(env.ari, with_digest=False)
    assert index.load_index("nomic").source.count("reflection") == 1

    other = env.tmp / "does_not_exist.md"
    index.build_all(env.ari, with_digest=False, reflections_path=other)
    assert index.load_index("nomic").source.count("reflection") == 0


def test_is_stale_sources_no_transcript_matches_no_transcript_build(env):
    """is_stale_sources(no_transcript=True) must agree with what no_transcript=True actually built, even while an
    example transcript sits at the fallback path (the same bug's staleness-reporting half)."""
    shutil.copy(env.example, env.ex)
    index.build_all(env.ari, with_digest=False, no_transcript=True)
    assert index.is_stale_sources("nomic", env.ari, no_transcript=True) is False
    assert index.is_stale_sources("nomic", env.ari) is True  # default resolution disagrees: that mismatch is the bug


def test_rebuild_digest_stops_ollama(env, monkeypatch):
    monkeypatch.setattr(digest, "ensure_digest", lambda profile, force=False: f"digest force={force}")
    assert index.rebuild_digest(env.mara) == "digest force=True"
    assert index.rebuild_digest(env.mara, force=False) == "digest force=False"
    assert env.stops == [1, 1]


# ---------------------------------------------------------------------------
# embed_texts routing (the real function, with fake clients)
# ---------------------------------------------------------------------------

def test_embed_texts_routes_to_runtime_inside_manager_session(monkeypatch):
    log: list = []

    def make(runtime):
        def embed(key, texts, tab=""):
            log.append((runtime, key, list(texts), tab))
            return np.ones((len(texts), 2), dtype=np.float32)
        return SimpleNamespace(embed=embed)

    monkeypatch.setattr(clients, "ollama", make("ollama"))
    monkeypatch.setattr(clients, "lms", make("lms"))
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: log.append(("ensure", key)))
    assert index.embed_texts("nomic", ["a", "b"], tab="index").shape == (2, 2)
    index.embed_texts("gemma", ["c"])
    index.embed_texts("lms_nomic", ["d"], tab="act")
    assert log == [("ensure", "nomic_ollama"), ("ollama", "nomic_ollama", ["a", "b"], "index"),
                   ("ensure", "embeddinggemma"), ("ollama", "embeddinggemma", ["c"], ""),
                   ("ensure", "nomic_lms"), ("lms", "nomic_lms", ["d"], "act")]
    assert gpu.MANAGER.lock.acquire(blocking=False)
    gpu.MANAGER.lock.release()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_build_all_passes_reflect_no_redact_transcript_and_force(env, monkeypatch, capsys):
    seen: list[dict] = []

    def fake_build_all(profile, with_digest, force=False, with_reflections=False, transcript_path=None,
                       no_redact=False):
        seen.append({"profile": profile.name, "with_digest": with_digest, "force": force,
                     "with_reflections": with_reflections, "transcript_path": transcript_path, "no_redact": no_redact})

    monkeypatch.setattr(index, "build_all", fake_build_all)
    monkeypatch.setattr(index, "load_profile", lambda path=None: env.mara)
    assert index.main(["--build", "all", "--digest", "--reflect", "--no-redact", "--transcript", "x/t.md",
                       "--force"]) == 0
    assert seen == [{"profile": "Mara Ellison", "with_digest": True, "force": True, "with_reflections": True,
                     "transcript_path": "x/t.md", "no_redact": True}]
    assert index.main(["--build", "all"]) == 0
    assert seen[1] == {"profile": "Mara Ellison", "with_digest": False, "force": False, "with_reflections": False,
                       "transcript_path": None, "no_redact": False}
    out = capsys.readouterr().out
    assert "profile: " in out and "Mara Ellison" in out and "61 chunks" in out
    assert env.embed.calls == []


@pytest.mark.parametrize("exc", [index.LeakError("containment check failed: x"),
                                 index.RedactionRequired("run python -m twin.redact first")])
def test_cli_build_all_errors_return_2(env, monkeypatch, capsys, exc):
    monkeypatch.setattr(index, "load_profile", lambda path=None: env.mara)
    monkeypatch.setattr(index, "build_all", lambda *a, **k: (_ for _ in ()).throw(exc))
    assert index.main(["--build", "all", "--reflect"]) == 2
    assert f"error: {exc}" in capsys.readouterr().out


def test_cli_build_single_index_reports_up_to_date(env, monkeypatch, capsys):
    monkeypatch.setattr(index, "load_profile", lambda path=None: env.mara)
    assert index.main(["--build", "nomic", "--transcript", str(env.example)]) == 0
    out = capsys.readouterr().out
    assert f"built nomic: {index.index_path('nomic')}" in out and "containment check: ok (max 0.50)" in out
    assert len(env.embed.calls) == 1 and env.stops == [1]
    assert index.main(["--build", "nomic", "--transcript", str(env.example)]) == 0
    assert "nomic up to date" in capsys.readouterr().out
    assert len(env.embed.calls) == 1 and env.stops == [1, 1]
    assert index.main(["--build", "nomic", "--transcript", str(env.example), "--force"]) == 0
    assert len(env.embed.calls) == 2 and env.stops == [1, 1, 1]
    leak = env.tmp / "leak.md"
    leak.write_text(_leak_transcript(env.mara), encoding="utf-8")
    assert index.main(["--build", "gemma", "--transcript", str(leak)]) == 2
    assert "error: containment check failed" in capsys.readouterr().out
    assert len(env.embed.calls) == 2 and env.stops == [1, 1, 1, 1]


def test_cli_search_passes_sources_and_prints_source_tags(env, monkeypatch, capsys):
    calls: list[dict] = []

    def fake_search(index_key, query, k=5, boost=None, tab="", sources=None):
        calls.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab, "sources": sources})
        return [("Identity", 0.5), ("Interview/T-001", 0.25)]

    monkeypatch.setattr(index, "search", fake_search)
    monkeypatch.setattr(index, "chunk_lookup", lambda: {"Identity": {"id": "Identity", "title": "Identity",
                                                                     "source": "profile"}})
    assert index.main(["--search", "who are you", "--sources", "profile, transcript", "--k", "2", "--index",
                       "gemma"]) == 0
    assert calls == [{"index_key": "gemma", "query": "who are you", "k": 2, "boost": None, "tab": "cli",
                      "sources": {"profile", "transcript"}}]
    out = capsys.readouterr().out
    assert "1 0.5000 Identity [profile] | Identity" in out
    assert "2 0.2500 Interview/T-001 [transcript] | Interview/T-001" in out
    assert env.stops == [1]
    assert index.main(["--search", "q"]) == 0
    assert calls[1]["sources"] is None and calls[1]["index_key"] == "nomic" and calls[1]["k"] == 3
    monkeypatch.setattr(index, "search", lambda *a, **k: [])
    assert index.main(["--search", "q", "--sources", "reflection"]) == 0
    assert "no results for sources ['reflection']" in capsys.readouterr().out
    assert env.stops == [1, 1, 1]


def test_cli_rejects_unknown_sources_and_prints_help_without_args(env, capsys):
    with pytest.raises(SystemExit) as e:
        index.main(["--search", "q", "--sources", "bogus"])
    assert e.value.code == 2
    assert "unknown source(s) ['bogus']" in capsys.readouterr().err
    assert index.main([]) == 0
    assert "--reflect" in capsys.readouterr().out
    assert env.embed.calls == [] and env.stops == []
