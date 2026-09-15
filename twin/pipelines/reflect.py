"""Expert reflections (docs/PLAN_UNIFIED.md 3.3; docs/research/D2 '# Expert reflections'): one qwen3:8b call
(40960 ctx, keep_alive 0, think false: all from the `qwen3_long` spec) per lens over the profile minus Eval and
Changelog plus the redacted interview transcript, cached in data/reflections.md under a sha comment.

The draft is indexed as 'Reflections/<lens>' only while the profile has no '# Expert reflections' section; the
user reviews it and pastes it into the profile (D1 rule 4: synthesized, human-checked). Only the transcript's
INCLUDED turns reach the model (`transcript_text`): the excluded block holds the verbatim gold Eval answers.
The 'Political scientist' lens runs only when the profile has a 'Beliefs and attitudes/Society and politics'
chunk (politics stays out by decision).
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from .. import clients
from ..config import REFLECTIONS_PATH
from ..gpu import MANAGER
from ..profile import NO_CHUNK_SECTIONS, POLITICS_CHUNK_ID, Profile, load_profile
from ..transcript import Transcript, included_turns, load_transcript, turn_text

MODEL_KEY = "qwen3_long"
NUM_PREDICT = 400
LENSES = ("Psychologist", "Behavioral economist", "Political scientist", "Demographer")
POLITICAL_LENS = "Political scientist"
_SHA_PREFIX = "<!-- sha: "

LENS_FOCUS = {
    "Psychologist": "personality (the Big Five and their facets), emotion regulation, coping under stress, "
                    "motivation, attachment and how they relate to other people",
    "Behavioral economist": "risk attitude, loss aversion, time preference and patience, fairness and reciprocity, "
                            "trust, sunk costs, and how they weigh trade-offs and money",
    "Political scientist": "trust in institutions, civic participation, how they reason about collective problems "
                           "and fairness in society, and where their views sit, without labelling a party",
    "Demographer": "life stage, household and family situation, occupation and income pattern, housing and place, "
                   "mobility, education and social network, as far as the material shows them",
}


def lenses_for(profile: Profile) -> list[str]:
    """LENSES minus 'Political scientist' unless the profile has the Society and politics chunk."""
    has_politics = any(c.id == POLITICS_CHUNK_ID for c in profile.chunks)
    return [lens for lens in LENSES if lens != POLITICAL_LENS or has_politics]


def REFLECT_SYSTEM(lens: str, name: str) -> str:
    focus = LENS_FOCUS.get(lens, "the latent traits your discipline studies")
    return (
        f"You are an experienced {lens.lower()} writing latent-trait notes about {name} for a research profile, "
        f"the way an expert reflects on an interview. Focus on {focus}. Read the PROFILE and the INTERVIEW "
        "TRANSCRIPT and write 120-220 words in the third person as plain prose: no headings, no markdown, no "
        "bullet symbols, no preamble, no quotations. Infer stable dispositions and name the evidence for each in a "
        "few words; say where the material is thin instead of guessing. Ground every claim in the material only "
        f"and never invent facts, names, numbers or events. Write about {name} as a person, not about the "
        "interview format."
    )


def corpus_text(profile: Profile, transcript_text: str) -> str:
    """The profile's raw sections except Eval and Changelog, then the transcript."""
    parts = [f"PROFILE:\nname: {profile.name}\nupdated: {profile.updated}"]
    for sec, text in profile.sections.items():
        if sec in NO_CHUNK_SECTIONS:
            continue
        parts.append(f"# {sec}\n{text}")
    return "\n\n".join(parts) + "\n\nINTERVIEW TRANSCRIPT:\n" + (transcript_text or "")


def transcript_text(t: Transcript) -> str:
    """The transcript's included turns rendered as blocks and 'Q:/A:' turns; excluded blocks (the gold Eval
    answers) never reach the reflections."""
    lines: list[str] = []
    block = None
    for turn in included_turns(t):
        if turn.block != block:
            block = turn.block
            lines.append(f"# Block {block}: {t.block_titles.get(block, '')}".rstrip(": "))
        lines.append(f"## {turn.id}\n{turn_text(turn)}\n")
    return "\n".join(lines).strip()


def reflections_key(profile: Profile, transcript_text: str) -> str:
    t_sha = hashlib.sha256((transcript_text or "").encode("utf-8")).hexdigest()
    return hashlib.sha256(f"{profile.sha}|{t_sha}".encode("utf-8")).hexdigest()


_HEADING_RE = re.compile(r"^\s*#+\s*")


def _clean(text: str) -> str:
    """Model output as plain paragraphs: no '#' headings (they would split the ## <lens> blocks), no think tags."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    lines = [_HEADING_RE.sub("", ln).rstrip() for ln in text.splitlines()]
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def _path(path=None) -> Path:
    return Path(REFLECTIONS_PATH if path is None else path)


def build_reflections(profile: Profile, transcript_text: str, tab: str = "reflect") -> str:
    """One qwen3_long call per lens (num_predict 400, one retry on empty content) inside one manager session;
    writes REFLECTIONS_PATH as '<!-- sha: <key> -->' + '## <lens>' blocks and returns the body."""
    user = corpus_text(profile, transcript_text)
    blocks: list[str] = []
    with MANAGER.session(MODEL_KEY, tab=tab):
        for lens in lenses_for(profile):
            messages = [
                {"role": "system", "content": REFLECT_SYSTEM(lens, profile.name)},
                {"role": "user", "content": user},
            ]
            text = ""
            for _ in range(2):
                resp = clients.ollama.chat(MODEL_KEY, messages, num_predict=NUM_PREDICT, tab=tab)
                text = _clean((resp.get("message", {}).get("content") or "").strip())
                if text:
                    break
            blocks.append(f"## {lens}\n{text}")
    body = "\n\n".join(blocks)
    out = _path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{_SHA_PREFIX}{reflections_key(profile, transcript_text)} -->\n{body}\n", encoding="utf-8")
    return body


def reflections_sha(path=None) -> str | None:
    """Key on the file's first line ('<!-- sha: ... -->'); None when missing or malformed."""
    try:
        first = _path(path).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return None
    if first.startswith(_SHA_PREFIX) and first.rstrip().endswith("-->"):
        return first[len(_SHA_PREFIX):].rstrip()[:-3].strip()
    return None


def _body_lines(path=None) -> list[str]:
    try:
        lines = _path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if lines and lines[0].startswith(_SHA_PREFIX):
        lines = lines[1:]
    return lines


def load_body(path=None) -> str:
    return "\n".join(_body_lines(path)).strip()


def load_reflections(path=None) -> dict[str, str]:
    """{lens: text} from the '## <lens>' blocks (lenses with empty text are dropped); {} when missing."""
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for ln in _body_lines(path):
        if ln.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = ln[3:].strip(), []
        elif cur is not None:
            buf.append(ln)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return {k: v for k, v in out.items() if v}


def ensure_reflections(profile: Profile, transcript_text: str, force: bool = False) -> str:
    """Cached by the sha comment (profile sha + transcript text); `force` rebuilds."""
    if not force and reflections_sha() == reflections_key(profile, transcript_text):
        return load_body()
    return build_reflections(profile, transcript_text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m twin.pipelines.reflect",
        description="Draft data/reflections.md: expert latent-trait notes per lens with qwen3:8b over the profile "
                    "and the redacted interview transcript (cached; review and paste into '# Expert reflections').",
    )
    ap.add_argument("--force", action="store_true", help="rebuild even when the cached key matches")
    ap.add_argument("--no-redact", action="store_true",
                    help="read data/interview_transcript.md even without an up-to-date redacted copy")
    args = ap.parse_args(argv)
    from .. import index  # lazy: index imports this module lazily too

    profile = load_profile()
    print(f"profile: {profile.path} ({profile.name}, sha {profile.sha[:12]})")
    try:
        tp = index.resolve_transcript_source(no_redact=args.no_redact)
    except index.RedactionRequired as e:
        print(f"error: {e}")
        return 2
    text = transcript_text(load_transcript(tp)) if tp else ""
    print(f"transcript: {tp if tp else 'none'} ({len(text)} chars of included turns)")
    print("lenses: " + ", ".join(lenses_for(profile)))
    try:
        ensure_reflections(profile, text, force=args.force)
    finally:
        index._stop_all_ollama()
    for lens, body in load_reflections().items():
        print(f"{lens}: {len(body)} chars")
    print(f"wrote {_path()} (key {reflections_sha() or '?'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
