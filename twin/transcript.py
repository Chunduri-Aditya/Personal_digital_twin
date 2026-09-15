"""Parse data/interview_transcript*.md (docs/PLAN_UNIFIED.md 3.2) into turns and retrieval chunks.

File format:
    ---
    name: Mara Ellison
    date: 2026-09-14
    blocks: 7
    exclude_blocks: [7]
    ---
    # Block 1: <title>
    ## T-001
    Q: <one line>
    A: <one or more lines, up to the next '## ' or '# ' heading>

Turn ids run continuously across blocks. Turns in `exclude_blocks` (default [7]: the block that holds the
verbatim gold Eval answers) are parsed but NEVER chunked; `index.collect_chunks` prints how many were skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import EXAMPLE_TRANSCRIPT_PATH, TRANSCRIPT_PATH
from .profile import Chunk, _split_frontmatter, approx_tokens

DEFAULT_EXCLUDE_BLOCKS = [7]
CHUNK_SECTION = "Interview"
CHUNK_SOURCE = "transcript"

_BLOCK_RE = re.compile(r"^#\s+Block\s+(\d+)\s*[:.\-]?\s*(.*?)\s*$", re.I)
_TURN_RE = re.compile(r"^##\s+(T-\d+[a-z]?)\s*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Turn:
    id: str
    block: int
    question: str
    answer: str


@dataclass
class Transcript:
    name: str
    date: str
    blocks: int
    exclude_blocks: list[int]
    turns: list[Turn] = field(default_factory=list)
    block_titles: dict[int, str] = field(default_factory=dict)
    sha: str = ""
    path: str = ""
    meta: dict = field(default_factory=dict)


def _exclude_blocks(value: str | None) -> list[int]:
    """'[7]', '7', '[6, 7]' -> ints; '[]' -> none; absent -> the default [7]."""
    if value is None:
        return list(DEFAULT_EXCLUDE_BLOCKS)
    return [int(x) for x in re.findall(r"\d+", value)]


def resolve_transcript_path() -> Path | None:
    """Real transcript > example transcript > None. (The index resolves the REDACTED file separately.)"""
    if TRANSCRIPT_PATH.exists():
        return TRANSCRIPT_PATH
    if EXAMPLE_TRANSCRIPT_PATH.exists():
        return EXAMPLE_TRANSCRIPT_PATH
    return None


def parse_transcript(text: str, path: str = "") -> Transcript:
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta, body = _split_frontmatter(text.lstrip("﻿"))
    excl = _exclude_blocks(meta.get("exclude_blocks"))
    try:
        n_blocks = int(meta.get("blocks", "0") or 0)
    except ValueError:
        n_blocks = 0
    t = Transcript(name=meta.get("name", ""), date=meta.get("date", ""), blocks=n_blocks, exclude_blocks=excl,
                   sha=sha, path=str(path), meta=dict(meta))

    block = 0
    cur_id: str | None = None
    q_lines: list[str] = []
    a_lines: list[str] = []
    in_answer = False

    def flush():
        if cur_id is None:
            return
        question = " ".join(x.strip() for x in q_lines if x.strip()).strip()
        answer = "\n".join(a_lines).strip("\n").strip()
        t.turns.append(Turn(id=cur_id, block=block, question=question, answer=answer))

    for ln in body.splitlines():
        mb = _BLOCK_RE.match(ln)
        if mb:
            flush()
            cur_id, q_lines, a_lines, in_answer = None, [], [], False
            block = int(mb.group(1))
            t.block_titles[block] = mb.group(2).strip()
            continue
        if ln.startswith("# "):            # a non-block top-level heading ends the current turn
            flush()
            cur_id, q_lines, a_lines, in_answer = None, [], [], False
            continue
        mt = _TURN_RE.match(ln)
        if mt:
            flush()
            cur_id, q_lines, a_lines, in_answer = mt.group(1), [], [], False
            continue
        if cur_id is None:
            continue
        if not in_answer and ln.startswith("Q:"):
            q_lines.append(ln[2:])
            continue
        if not in_answer and ln.startswith("A:"):
            in_answer = True
            first = ln[2:].strip()
            if first:
                a_lines.append(first)
            continue
        if in_answer:
            a_lines.append(ln.rstrip())
        elif q_lines:
            q_lines.append(ln)          # question continuation line before the answer starts
    flush()
    if not t.blocks:
        t.blocks = max(t.block_titles) if t.block_titles else (max((x.block for x in t.turns), default=0))
    return t


def load_transcript(path: Path | None = None) -> Transcript:
    p = Path(path) if path else resolve_transcript_path()
    if p is None:
        raise FileNotFoundError(f"no transcript: neither {TRANSCRIPT_PATH} nor {EXAMPLE_TRANSCRIPT_PATH} exists")
    data = p.read_bytes()
    t = parse_transcript(data.decode("utf-8-sig"), str(p))
    t.sha = hashlib.sha256(data).hexdigest()
    return t


def excluded_turns(t: Transcript) -> list[Turn]:
    return [x for x in t.turns if x.block in t.exclude_blocks]


def included_turns(t: Transcript) -> list[Turn]:
    return [x for x in t.turns if x.block not in t.exclude_blocks]


def turn_text(turn: Turn) -> str:
    return f"Q: {turn.question}\nA: {turn.answer}"


def _sentences(answer: str) -> list[str]:
    """Split an answer at sentence boundaries (. ! ? or newline); pieces keep their punctuation."""
    out: list[str] = []
    for line in answer.splitlines():
        line = line.strip()
        if not line:
            continue
        out.extend(s for s in _SENTENCE_SPLIT_RE.split(line) if s.strip())
    return out


def _part_id(i: int) -> str:
    return chr(ord("a") + i) if i < 26 else str(i + 1)


def split_answer(question: str, answer: str, max_tokens: int) -> list[str]:
    """Answer parts such that 'Q: <q>\\nA: <part>' fits max_tokens where sentence boundaries allow it.
    A single sentence longer than the budget becomes its own part (never cut mid-sentence)."""
    head = f"Q: {question}\nA: "
    parts: list[str] = []
    cur: list[str] = []
    for s in _sentences(answer):
        trial = " ".join(cur + [s])
        if cur and approx_tokens(head + trial) > max_tokens:
            parts.append(" ".join(cur))
            cur = [s]
        else:
            cur.append(s)
    if cur:
        parts.append(" ".join(cur))
    return parts or [answer.strip()]


def transcript_chunks(t: Transcript, max_tokens: int = 300) -> list[Chunk]:
    """One Chunk per included turn (id 'Interview/T-012'); answers over `max_tokens` are split at sentence
    boundaries into 'Interview/T-012a', 'Interview/T-012b', ... each repeating the 'Q:' line."""
    chunks: list[Chunk] = []
    for turn in included_turns(t):
        title = f"{turn.id}: {t.block_titles.get(turn.block, f'Block {turn.block}')}"
        text = turn_text(turn)
        if approx_tokens(text) <= max_tokens:
            chunks.append(Chunk(f"{CHUNK_SECTION}/{turn.id}", CHUNK_SECTION, turn.id, title, text, CHUNK_SOURCE))
            continue
        parts = split_answer(turn.question, turn.answer, max_tokens)
        if len(parts) == 1:
            chunks.append(Chunk(f"{CHUNK_SECTION}/{turn.id}", CHUNK_SECTION, turn.id, title, text, CHUNK_SOURCE))
            continue
        for i, part in enumerate(parts):
            sub = f"{turn.id}{_part_id(i)}"
            chunks.append(Chunk(f"{CHUNK_SECTION}/{sub}", CHUNK_SECTION, sub, title,
                                f"Q: {turn.question}\nA: {part}", CHUNK_SOURCE))
    return chunks


def per_block_counts(t: Transcript) -> dict[int, int]:
    counts: dict[int, int] = {}
    for x in t.turns:
        counts[x.block] = counts.get(x.block, 0) + 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m twin.transcript")
    ap.add_argument("path", nargs="?", help="transcript file (default: real > example)")
    ap.add_argument("--max-tokens", type=int, default=300)
    args = ap.parse_args(argv)
    try:
        t = load_transcript(args.path)
    except Exception as e:  # noqa: BLE001
        print(f"parse failed: {e}")
        return 2
    print(f"transcript: {t.path} ({t.name}, {t.date}, blocks {t.blocks}, exclude {t.exclude_blocks}, sha {t.sha[:12]})")
    for b, n in sorted(per_block_counts(t).items()):
        tag = " (excluded)" if b in t.exclude_blocks else ""
        print(f"block {b}: {n} turns, {t.block_titles.get(b, '')}{tag}")
    ex = excluded_turns(t)
    chunks = transcript_chunks(t, max_tokens=args.max_tokens)
    print(f"turns: {len(t.turns)} (excluded {len(ex)}: {ex[0].id + '..' + ex[-1].id if ex else '-'})")
    split_ids = [c.id for c in chunks if c.subsection[-1].isalpha()]
    over = [(c.id, approx_tokens(c.text)) for c in chunks if approx_tokens(c.text) > args.max_tokens]
    print(f"chunks: {len(chunks)} (split: {', '.join(split_ids) or 'none'}; still over budget: {over or 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
