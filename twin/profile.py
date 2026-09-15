"""Parse data/twin_profile.md (schema v1 "Ari" or v2 "Mara") into sections, chunks, decisions and eval Q/A.

v2 additions (docs/PLAN_UNIFIED.md 3.1, docs/research/D2): frontmatter `schema_version`, `embedder`,
`eval_frozen`, optional `consent`; sections Beliefs and attitudes, Routines, Life events, Self-ratings,
Interview highlights, Expert reflections; `Changelog` is stored in `sections` but, like `Eval`, never chunked.
`python -m twin.profile --lint [path]` reports chunk sizes, prefix budget, word count, missing sections.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import DIGEST_PATH, EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH, PROFILE_PATH

_CODE_RE = re.compile(r"^([DQ]-\d+)\b")
_SPLIT_LIMIT = 1500

# Sections that are parsed and kept in `Profile.sections` but never become chunks (D1 rules 14 and 25).
NO_CHUNK_SECTIONS = ("Eval", "Changelog")

# docs/research/D2 section order; `lint` reports the ones a profile lacks.
D2_SECTIONS = (
    "Identity", "Voice", "Values", "Beliefs and attitudes", "Preferences", "Routines", "People", "Decisions",
    "Life events", "Self-ratings", "Interview highlights", "Expert reflections", "Goals", "Boundaries", "Eval",
    "Changelog",
)

CHUNK_TOKENS_MAX = 300
CHUNK_TOKENS_MIN = 80
PREFIX_BUDGET = 1500
WORD_BAND = (4000, 7000)
# Chunk ids exempt from the 80-token floor (short by design: voice samples, one-paragraph anchors).
UNDER_EXEMPT_PREFIXES = ("Voice/Sample", "Identity", "Boundaries", "Goals", "Self-ratings")
POLITICS_CHUNK_ID = "Beliefs and attitudes/Society and politics"


@dataclass
class Chunk:
    id: str
    section: str
    subsection: str
    title: str
    text: str
    source: str = "profile"      # "profile" | "transcript" | "reflection" (index.collect_chunks re-tags)


@dataclass
class Decision:
    id: str
    title: str
    situation: str
    options: list[str]
    choice: str
    why: str
    outcome: str


@dataclass
class EvalQA:
    qid: str
    question: str
    answer: str


@dataclass
class Profile:
    name: str
    updated: str
    sha: str
    path: str
    sections: dict[str, str] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    eval: list[EvalQA] = field(default_factory=list)
    style_rules: str = ""
    samples: list[str] = field(default_factory=list)
    identity: str = ""
    boundaries: str = ""
    values: str = ""
    goals: str = ""
    people: str = ""
    preferences: dict[str, str] = field(default_factory=dict)
    # ---- schema v2 -------------------------------------------------------
    schema_version: str = ""
    embedder: str = ""
    eval_frozen: bool = False
    consent: str = ""
    reflections: dict[str, str] = field(default_factory=dict)     # "## <lens>" under "# Expert reflections"
    self_ratings: str = ""
    beliefs: dict[str, str] = field(default_factory=dict)         # "## <topic>" under "# Beliefs and attitudes"
    routines: dict[str, str] = field(default_factory=dict)        # "## Weekday" / "## Weekend"
    life_events: dict[str, str] = field(default_factory=dict)     # "## <title>" under "# Life events"
    highlights: dict[str, str] = field(default_factory=dict)      # "## <topic>" under "# Interview highlights"


def resolve_profile_path() -> Path:
    """Real profile > v2 example (Mara) > v1 example (Ari). Phase-1 tests pin the Ari path explicitly."""
    if PROFILE_PATH.exists():
        return PROFILE_PATH
    if EXAMPLE_PROFILE_V2_PATH.exists():
        return EXAMPLE_PROFILE_V2_PATH
    return EXAMPLE_PROFILE_PATH


def approx_tokens(text: str) -> int:
    """Cheap token estimate (4 chars per token) shared by lint and transcript chunking; never 0."""
    return max(1, round(len(text or "") / 4))


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for ln in lines[1:i]:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        meta[k.strip().lower()] = v.strip()
                return meta, "\n".join(lines[i + 1:])
    return meta, text


def _split_headings(body: str, prefix: str) -> tuple[str, list[tuple[str, str]]]:
    """Split on lines starting with `prefix` (e.g. '# '). Returns (pre_text, [(heading, text)])."""
    pre: list[str] = []
    parts: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for ln in body.splitlines():
        if ln.startswith(prefix) and not ln.startswith(prefix.rstrip() + "#"):
            parts.append((ln[len(prefix):].strip(), []))
            cur = parts[-1][1]
        elif cur is None:
            pre.append(ln)
        else:
            cur.append(ln)
    return "\n".join(pre).strip("\n"), [(h, "\n".join(b).strip("\n")) for h, b in parts]


def _field(text: str, label: str) -> str:
    m = re.search(r"^" + re.escape(label) + r":\s*(.*?)$", text, re.M)
    return m.group(1).strip() if m else ""


def _multiline_field(text: str, label: str, labels: list[str]) -> str:
    """Field value that may run to the next labelled line."""
    lines = text.splitlines()
    out: list[str] = []
    grab = False
    for ln in lines:
        head = ln.split(":", 1)[0].strip() if ":" in ln else None
        if head in labels:
            if grab:
                break
            if head == label:
                grab = True
                out.append(ln.split(":", 1)[1].strip())
            continue
        if grab:
            out.append(ln.strip())
    return " ".join(x for x in out if x).strip()


def _bool(v: str) -> bool:
    return (v or "").strip().lower() in ("true", "yes", "1", "on")


_DEC_LABELS = ["Situation", "Options", "Choice", "Why", "Outcome"]
_EVAL_LABELS = ["Question", "Answer"]
_SUB_DICT_SECTIONS = {
    "Beliefs and attitudes": "beliefs",
    "Routines": "routines",
    "Life events": "life_events",
    "Interview highlights": "highlights",
    "Expert reflections": "reflections",
}


def parse_profile(text: str, path: str = "") -> Profile:
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    meta, body = _split_frontmatter(text.lstrip("﻿"))
    prof = Profile(
        name=meta.get("name", ""), updated=meta.get("updated", ""), sha=sha, path=str(path),
        schema_version=meta.get("schema_version", ""), embedder=meta.get("embedder", ""),
        eval_frozen=_bool(meta.get("eval_frozen", "")), consent=meta.get("consent", ""),
    )

    _, sections = _split_headings(body, "# ")
    for sec_name, sec_text in sections:
        prof.sections[sec_name] = sec_text
        intro, subs = _split_headings(sec_text, "## ")

        if sec_name == "Eval":
            for h, t in subs:
                m = _CODE_RE.match(h)
                qid = m.group(1) if m else h
                prof.eval.append(EvalQA(
                    qid=qid,
                    question=_multiline_field(t, "Question", _EVAL_LABELS),
                    answer=_multiline_field(t, "Answer", _EVAL_LABELS),
                ))
            continue
        if sec_name == "Changelog":
            continue

        if not subs:
            if len(sec_text) > _SPLIT_LIMIT:
                paras = [p.strip() for p in re.split(r"\n\s*\n", sec_text) if p.strip()]
                for i, p in enumerate(paras, 1):
                    prof.chunks.append(Chunk(f"{sec_name}/{i}", sec_name, "", sec_name, p))
            elif sec_text.strip():
                prof.chunks.append(Chunk(sec_name, sec_name, "", sec_name, sec_text.strip()))
        else:
            if intro.strip():
                prof.chunks.append(Chunk(f"{sec_name}/intro", sec_name, "intro", sec_name, intro.strip()))
            for h, t in subs:
                m = _CODE_RE.match(h)
                sub = m.group(1) if m else h
                if t.strip():
                    prof.chunks.append(Chunk(f"{sec_name}/{sub}", sec_name, sub, h, t.strip()))
                if sec_name == "Decisions":
                    title = h.split(":", 1)[1].strip() if m and ":" in h else h
                    opts = [o.strip() for o in _field(t, "Options").split("|") if o.strip()]
                    prof.decisions.append(Decision(
                        id=sub, title=title,
                        situation=_multiline_field(t, "Situation", _DEC_LABELS),
                        options=opts,
                        choice=_multiline_field(t, "Choice", _DEC_LABELS),
                        why=_multiline_field(t, "Why", _DEC_LABELS),
                        outcome=_multiline_field(t, "Outcome", _DEC_LABELS),
                    ))
                if sec_name == "Voice":
                    if h.lower() == "style rules":
                        prof.style_rules = t.strip()
                    elif h.lower().startswith("sample"):
                        prof.samples.append(t.strip())
                if sec_name == "Preferences":
                    prof.preferences[h] = t.strip()
                attr = _SUB_DICT_SECTIONS.get(sec_name)
                if attr:
                    getattr(prof, attr)[h] = t.strip()

    prof.identity = prof.sections.get("Identity", "").strip()
    prof.boundaries = prof.sections.get("Boundaries", "").strip()
    prof.values = prof.sections.get("Values", "").strip()
    prof.goals = prof.sections.get("Goals", "").strip()
    prof.people = prof.sections.get("People", "").strip()
    prof.self_ratings = prof.sections.get("Self-ratings", "").strip()
    return prof


def load_profile(path: Path | None = None) -> Profile:
    p = Path(path) if path else resolve_profile_path()
    data = p.read_bytes()
    prof = parse_profile(data.decode("utf-8-sig"), str(p))
    prof.sha = hashlib.sha256(data).hexdigest()
    return prof


def chunk_ids(profile: Profile) -> list[str]:
    return [c.id for c in profile.chunks]


# ---------------------------------------------------------------------------
# lint (docs/research/D1 rules 6-8, 14, 25; docs/PLAN_UNIFIED.md 3.1)
# ---------------------------------------------------------------------------

_WORD_COUNT_RE = re.compile(r"\S*[A-Za-z0-9]\S*")


def substantive_words(profile: Profile) -> int:
    """Word count of every section except Eval and Changelog (heading markers dropped)."""
    n = 0
    for sec, text in profile.sections.items():
        if sec in NO_CHUNK_SECTIONS:
            continue
        for ln in text.splitlines():
            if ln.startswith("## "):
                ln = ln[3:]
            n += len(_WORD_COUNT_RE.findall(ln))
    return n


def lint(profile: Profile, digest_text: str | None = None) -> dict:
    """Pure report (no I/O): chunk-size outliers, prefix budget, word band, missing D2 sections, warnings."""
    from .prompts import build_voice_prefix  # local import: prompts.py never imports profile, but keep this module light

    sizes = [(c.id, approx_tokens(c.text)) for c in profile.chunks]
    chunks_over = [(cid, n) for cid, n in sizes if n > CHUNK_TOKENS_MAX]
    chunks_under = [(cid, n) for cid, n in sizes
                    if n < CHUNK_TOKENS_MIN and not cid.startswith(UNDER_EXEMPT_PREFIXES)]
    prefix_tokens = approx_tokens(build_voice_prefix(profile, digest_text or ""))
    words = substantive_words(profile)
    missing = [s for s in D2_SECTIONS if s not in profile.sections]
    eval_chunks = sum(1 for c in profile.chunks if c.section == "Eval")
    changelog_chunks = sum(1 for c in profile.chunks if c.section == "Changelog")

    warnings: list[str] = []
    if any(c.id == POLITICS_CHUNK_ID for c in profile.chunks):
        warnings.append(f"chunk '{POLITICS_CHUNK_ID}' present: politics stays out of the twin by decision "
                        "(the section may be omitted; the twin deflects politics in chat)")
    if eval_chunks:
        warnings.append(f"{eval_chunks} Eval chunk(s) would be indexed (gold answers must never be retrievable)")
    if changelog_chunks:
        warnings.append(f"{changelog_chunks} Changelog chunk(s) would be indexed")
    if prefix_tokens > PREFIX_BUDGET:
        warnings.append(f"static prefix {prefix_tokens} tokens exceeds the {PREFIX_BUDGET} budget")
    if words < WORD_BAND[0]:
        warnings.append(f"{words} substantive words is under the {WORD_BAND[0]}-{WORD_BAND[1]} band")
    elif words > WORD_BAND[1]:
        warnings.append(f"{words} substantive words is over the {WORD_BAND[0]}-{WORD_BAND[1]} band")
    if chunks_over:
        warnings.append(f"{len(chunks_over)} chunk(s) over {CHUNK_TOKENS_MAX} tokens")
    if len(profile.eval) != 20:
        warnings.append(f"{len(profile.eval)} Eval items (expected 20)")
    if len(profile.samples) != 15:
        warnings.append(f"{len(profile.samples)} Voice samples (expected 15)")
    if not profile.schema_version:
        warnings.append("frontmatter has no schema_version (v1 file)")
    if not profile.embedder:
        warnings.append("frontmatter has no embedder (D1 rule 23)")

    return {
        "chunks_over": chunks_over,
        "chunks_under": chunks_under,
        "prefix_tokens": prefix_tokens,
        "prefix_budget": PREFIX_BUDGET,
        "words": words,
        "word_band": WORD_BAND,
        "missing_sections": missing,
        "warnings": warnings,
        "eval_chunks": eval_chunks,
        "changelog_chunks": changelog_chunks,
    }


def _digest_for(profile: Profile) -> tuple[str, str]:
    """(digest text, state) from data/digest.md: state is present | stale | missing. Read-only, never builds."""
    try:
        lines = Path(DIGEST_PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", "missing"
    if not lines or not lines[0].startswith("<!-- sha:"):
        return "", "missing"
    sha = lines[0][len("<!-- sha:"):].split("-->", 1)[0].strip()
    text = "\n".join(lines[1:]).strip()
    if sha != profile.sha or not text:
        return "", "stale"
    return text, "present"


def _fmt_pairs(pairs: list[tuple[str, int]]) -> str:
    return "none" if not pairs else ", ".join(f"{cid} ({n})" for cid, n in pairs)


def lint_lines(profile: Profile, report: dict, digest_state: str) -> list[str]:
    lines = [
        f"profile: {profile.path or '(text)'} ({profile.name or '?'}, schema {profile.schema_version or 'v1'}, "
        f"sha {profile.sha[:12]}, {len(profile.chunks)} chunks, {len(profile.decisions)} decisions, "
        f"{len(profile.eval)} eval items)",
        f"changelog chunks: {report['changelog_chunks']}",
        f"eval chunks: {report['eval_chunks']}",
        f"prefix: {report['prefix_tokens']} tokens of {report['prefix_budget']} budget (digest: {digest_state})",
        f"words: {report['words']} (band {report['word_band'][0]}-{report['word_band'][1]})",
        f"chunks over {CHUNK_TOKENS_MAX} tokens: {_fmt_pairs(report['chunks_over'])}",
        f"chunks under {CHUNK_TOKENS_MIN} tokens: {_fmt_pairs(report['chunks_under'])}",
        "missing sections: " + (", ".join(report["missing_sections"]) or "none"),
    ]
    lines += [f"WARNING: {w}" for w in report["warnings"]]
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m twin.profile")
    ap.add_argument("--lint", nargs="?", const="", metavar="PATH",
                    help="lint a profile (default: the resolved profile: real > v2 example > v1 example)")
    args = ap.parse_args(argv)
    if args.lint is None:
        ap.print_help()
        return 0
    try:
        profile = load_profile(args.lint or None)
    except Exception as e:  # noqa: BLE001
        print(f"parse failed: {e}", file=sys.stderr)
        return 2
    digest, state = _digest_for(profile)
    for ln in lint_lines(profile, lint(profile, digest), state):
        print(ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
