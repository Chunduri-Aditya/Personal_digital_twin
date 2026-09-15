"""Parser and chunking tests for twin.transcript (docs/PLAN_UNIFIED.md 3.2).

No network, no subprocess, no GPU: string parsing on synthetic transcripts and on
data/interview_transcript.example.md.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from twin import transcript as tr
from twin.config import EXAMPLE_TRANSCRIPT_PATH
from twin.profile import Chunk, approx_tokens
from twin.transcript import (Transcript, Turn, excluded_turns, included_turns, load_transcript, parse_transcript,
                             transcript_chunks)

SMALL = """---
name: Zed Example
date: 2030-01-02
blocks: 2
---
# Block 1: Opening
## T-001
Q: First question?
A: first answer line one.
line two of the answer.

still the same answer after a blank line.
## T-002
Q: Second question?
A: short.
# Block 2: Closing
## T-003
Q: Third?
A: third answer.
"""


def _with_meta(text: str, line: str) -> str:
    """Insert one frontmatter line after 'blocks: 2'."""
    return text.replace("blocks: 2\n", f"blocks: 2\n{line}\n", 1)


@pytest.fixture(scope="module")
def example() -> Transcript:
    return load_transcript(EXAMPLE_TRANSCRIPT_PATH)


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------

def test_frontmatter_fields_and_default_exclude_blocks():
    t = parse_transcript(SMALL)
    assert isinstance(t, Transcript)
    assert t.name == "Zed Example" and t.date == "2030-01-02" and t.blocks == 2
    assert t.exclude_blocks == [7], "exclude_blocks must default to [7] when absent"
    assert t.path == "" and t.sha == hashlib.sha256(SMALL.encode("utf-8")).hexdigest()
    assert t.meta["name"] == "Zed Example" and t.meta["blocks"] == "2"


@pytest.mark.parametrize("raw,want", [("[2]", [2]), ("2", [2]), ("[6, 7]", [6, 7]), ("[]", [])])
def test_exclude_blocks_parsed_from_frontmatter(raw, want):
    t = parse_transcript(_with_meta(SMALL, f"exclude_blocks: {raw}"))
    assert t.exclude_blocks == want


def test_meta_carries_every_frontmatter_key():
    t = parse_transcript(_with_meta(SMALL, "source_sha: abc123\nredacted: true"))
    assert t.meta["source_sha"] == "abc123" and t.meta["redacted"] == "true"
    assert t.name == "Zed Example"


def test_missing_frontmatter_infers_blocks_from_headings():
    body = SMALL.split("---\n", 2)[2]
    t = parse_transcript(body)
    assert t.name == "" and t.date == ""
    assert t.blocks == 2 and t.exclude_blocks == [7]
    assert [x.id for x in t.turns] == ["T-001", "T-002", "T-003"]


# ---------------------------------------------------------------------------
# blocks, turns, answers
# ---------------------------------------------------------------------------

def test_turn_ids_blocks_and_titles():
    t = parse_transcript(SMALL)
    assert [x.id for x in t.turns] == ["T-001", "T-002", "T-003"]
    assert [x.block for x in t.turns] == [1, 1, 2]
    assert t.block_titles == {1: "Opening", 2: "Closing"}
    assert all(isinstance(x, Turn) for x in t.turns)


def test_multiline_answer_is_preserved_up_to_next_heading():
    t = parse_transcript(SMALL)
    first = t.turns[0]
    assert first.question == "First question?"
    assert first.answer == "first answer line one.\nline two of the answer.\n\nstill the same answer after a blank line."
    assert t.turns[1].answer == "short."
    assert t.turns[2].question == "Third?" and t.turns[2].answer == "third answer."
    for x in t.turns:
        assert not x.question.startswith("Q:") and not x.answer.startswith("A:")
        assert "## " not in x.answer and "# Block" not in x.answer


def test_question_continuation_line_before_answer():
    text = "# Block 1: X\n## T-001\nQ: first half of the question\nsecond half?\nA: yes.\n"
    t = parse_transcript(text)
    assert t.turns[0].question == "first half of the question second half?"
    assert t.turns[0].answer == "yes."


def test_crlf_and_bom_parse_like_lf(tmp_path: Path):
    a = parse_transcript(SMALL)
    b = parse_transcript(SMALL.replace("\n", "\r\n"))
    assert [(x.id, x.block, x.question, x.answer) for x in b.turns] == [(x.id, x.block, x.question, x.answer) for x in a.turns]
    f = tmp_path / "bom.md"
    f.write_bytes(b"\xef\xbb\xbf" + SMALL.encode("utf-8"))
    t = load_transcript(f)
    assert t.name == "Zed Example" and t.path == str(f)
    assert t.sha == hashlib.sha256(f.read_bytes()).hexdigest()


def test_load_transcript_accepts_str_path(tmp_path: Path):
    f = tmp_path / "t.md"
    f.write_text(SMALL, encoding="utf-8")
    assert load_transcript(str(f)).name == "Zed Example"


# ---------------------------------------------------------------------------
# excluded turns and chunk shape
# ---------------------------------------------------------------------------

def test_excluded_turns_are_parsed_but_never_chunked():
    t = parse_transcript(_with_meta(SMALL, "exclude_blocks: [2]"))
    assert [x.id for x in excluded_turns(t)] == ["T-003"]
    assert [x.id for x in included_turns(t)] == ["T-001", "T-002"]
    assert len(t.turns) == 3
    chunks = transcript_chunks(t)
    assert [c.id for c in chunks] == ["Interview/T-001", "Interview/T-002"]
    assert all("third answer" not in c.text for c in chunks)


def test_chunk_id_title_text_source_shape():
    t = parse_transcript(SMALL)
    c = transcript_chunks(t)[0]
    assert isinstance(c, Chunk)
    assert c.id == "Interview/T-001" and c.section == "Interview" and c.subsection == "T-001"
    assert c.title == "T-001: Opening"
    assert c.text == "Q: First question?\nA: " + t.turns[0].answer
    assert c.source == "transcript"
    c3 = transcript_chunks(t)[2]
    assert c3.id == "Interview/T-003" and c3.title == "T-003: Closing"


def test_turn_text_helper():
    assert tr.turn_text(Turn("T-009", 2, "q?", "a.")) == "Q: q?\nA: a."


# ---------------------------------------------------------------------------
# a/b split above 300 approx tokens
# ---------------------------------------------------------------------------

def _long_transcript(n_sentences: int = 48) -> tuple[str, list[str]]:
    sentences = [f"sentence number {i} ends right here." for i in range(1, n_sentences + 1)]
    text = "# Block 1: Long\n## T-001\nQ: Tell me everything?\nA: " + " ".join(sentences) + "\n"
    return text, sentences


def test_long_answer_splits_at_sentence_boundaries_with_q_line_repeated():
    text, sentences = _long_transcript()
    t = parse_transcript(text)
    whole = tr.turn_text(t.turns[0])
    assert approx_tokens(whole) > 300
    chunks = transcript_chunks(t)
    assert len(chunks) >= 2
    assert [c.id for c in chunks][:2] == ["Interview/T-001a", "Interview/T-001b"]
    assert [c.subsection for c in chunks][:2] == ["T-001a", "T-001b"]
    joined: list[str] = []
    for c in chunks:
        assert c.section == "Interview" and c.source == "transcript"
        assert c.title == "T-001: Long"
        assert c.text.startswith("Q: Tell me everything?\nA: "), c.id
        assert approx_tokens(c.text) <= 300, (c.id, approx_tokens(c.text))
        body = c.text.split("\nA: ", 1)[1]
        assert body.endswith("."), "part must end at a sentence boundary"
        joined.extend(s.strip() for s in body.split(". ") if s.strip())
    joined = [s if s.endswith(".") else s + "." for s in joined]
    assert joined == sentences, "the parts must cover every sentence exactly once, in order"


def test_no_split_at_or_under_the_budget():
    text, _ = _long_transcript(10)
    t = parse_transcript(text)
    assert approx_tokens(tr.turn_text(t.turns[0])) <= 300
    chunks = transcript_chunks(t)
    assert [c.id for c in chunks] == ["Interview/T-001"]
    assert chunks[0].subsection == "T-001"


def test_custom_max_tokens_makes_more_parts():
    text, _ = _long_transcript(24)
    t = parse_transcript(text)
    small = transcript_chunks(t, max_tokens=60)
    assert len(small) >= 3
    assert [c.subsection for c in small][:3] == ["T-001a", "T-001b", "T-001c"]
    for c in small:
        assert c.text.startswith("Q: Tell me everything?\nA: ")


def test_newline_is_a_sentence_boundary():
    lines = [f"line {i} has no punctuation at all and keeps going for a while" for i in range(1, 30)]
    text = "# Block 1: Lines\n## T-001\nQ: q?\nA: " + "\n".join(lines) + "\n"
    t = parse_transcript(text)
    chunks = transcript_chunks(t)
    assert len(chunks) >= 2
    parts = [c.text.split("\nA: ", 1)[1] for c in chunks]
    for ln in lines:
        assert sum(ln in p for p in parts) == 1, ln
    for p in parts:
        assert approx_tokens("Q: q?\nA: " + p) <= 300


def test_single_oversized_sentence_is_never_cut():
    one = "word " * 1400
    text = "# Block 1: X\n## T-001\nQ: q?\nA: " + one.strip() + "\n"
    chunks = transcript_chunks(parse_transcript(text))
    assert [c.id for c in chunks] == ["Interview/T-001"]
    assert one.strip() in chunks[0].text


def test_split_answer_helper_direct():
    parts = tr.split_answer("q?", "a. b. c.", max_tokens=1000)
    assert parts == ["a. b. c."]
    assert tr.split_answer("q?", "", 300) == [""]


# ---------------------------------------------------------------------------
# the shipped example transcript (Mara)
# ---------------------------------------------------------------------------

def test_example_transcript_exists_and_parses(example: Transcript):
    assert EXAMPLE_TRANSCRIPT_PATH.exists()
    assert example.name == "Mara Ellison" and example.date == "2026-09-14"
    assert example.blocks == 7 and example.exclude_blocks == [7]
    assert example.path == str(EXAMPLE_TRANSCRIPT_PATH)
    assert example.sha == hashlib.sha256(EXAMPLE_TRANSCRIPT_PATH.read_bytes()).hexdigest()
    assert example.meta.get("source_sha") is None


def test_example_has_about_sixty_continuous_turns(example: Transcript):
    ids = [x.id for x in example.turns]
    assert 55 <= len(ids) <= 65
    assert ids == [f"T-{i:03d}" for i in range(1, len(ids) + 1)], "turn ids must be continuous across blocks"
    assert sorted(example.block_titles) == [1, 2, 3, 4, 5, 6, 7]
    assert set(x.block for x in example.turns) == set(range(1, 8))
    for x in example.turns:
        assert x.question.strip() and x.answer.strip(), x.id


def test_example_block_seven_is_excluded_and_never_chunked(example: Transcript):
    ex = excluded_turns(example)
    assert ex and all(x.block == 7 for x in ex)
    assert len(ex) == tr.per_block_counts(example)[7]
    chunks = transcript_chunks(example)
    chunk_ids = {c.id for c in chunks}
    for x in ex:
        assert f"Interview/{x.id}" not in chunk_ids
        assert not any(c.subsection.startswith(x.id) for c in chunks)
    gold = [x.answer for x in ex if len(x.answer) > 20]
    for c in chunks:
        for g in gold:
            assert g not in c.text, (c.id, g[:40])
    parents = {c.subsection.rstrip("abcdefghijklmnopqrstuvwxyz") for c in chunks}
    assert parents == {x.id for x in included_turns(example)}, "every included turn chunks, nothing else does"


def test_example_chunks_shape_and_splits(example: Transcript):
    chunks = transcript_chunks(example)
    assert all(c.source == "transcript" and c.section == "Interview" for c in chunks)
    assert all(c.id == f"Interview/{c.subsection}" for c in chunks)
    assert all(approx_tokens(c.text) <= 300 for c in chunks), [(c.id, approx_tokens(c.text)) for c in chunks
                                                              if approx_tokens(c.text) > 300]
    split = [c.id for c in chunks if c.subsection[-1].isalpha()]
    assert split == ["Interview/T-001a", "Interview/T-001b", "Interview/T-004a", "Interview/T-004b"]
    t004 = [c for c in chunks if c.subsection.startswith("T-004")]
    assert all(c.text.startswith("Q: What did you learn from quitting the agency job?\nA: ") for c in t004)
    assert all(c.title == "T-004: Life story & future" for c in t004)
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------

def test_resolve_transcript_path_order(tmp_path: Path, monkeypatch):
    real = tmp_path / "interview_transcript.md"
    example = tmp_path / "interview_transcript.example.md"
    monkeypatch.setattr(tr, "TRANSCRIPT_PATH", real)
    monkeypatch.setattr(tr, "EXAMPLE_TRANSCRIPT_PATH", example)
    assert tr.resolve_transcript_path() is None
    with pytest.raises(FileNotFoundError):
        load_transcript()
    example.write_text(SMALL, encoding="utf-8")
    assert tr.resolve_transcript_path() == example
    assert load_transcript().path == str(example)
    real.write_text(SMALL.replace("Zed Example", "Real Person"), encoding="utf-8")
    assert tr.resolve_transcript_path() == real
    assert load_transcript().name == "Real Person"


def test_cli_prints_counts_without_models(capsys, tmp_path: Path):
    f = tmp_path / "t.md"
    f.write_text(_with_meta(SMALL, "exclude_blocks: [2]"), encoding="utf-8")
    assert tr.main([str(f)]) == 0
    out = capsys.readouterr().out
    assert "blocks 2, exclude [2]" in out and "block 2: 1 turns, Closing (excluded)" in out
    assert "turns: 3 (excluded 1: T-003..T-003)" in out and "chunks: 2" in out
    assert tr.main([str(tmp_path / "missing.md")]) == 2
