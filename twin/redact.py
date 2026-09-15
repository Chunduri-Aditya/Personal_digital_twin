"""Redaction for interview transcripts (docs/PLAN_UNIFIED.md 3.2): regex rules, a deterministic name
heuristic, and an optional qwen3_8k pass that names third parties so they can become role tags.

Removed strings (names, emails, numbers) are NEVER written to any report file; the CLI may print them to the
console so the user can check the pass. The index reads only the redacted file (see twin.index).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from . import clients
from . import profile as profile_mod
from .config import REDACTED_TRANSCRIPT_PATH, REDACTION_REPORT_PATH, TRANSCRIPT_PATH
from .gpu import MANAGER
from .transcript import Transcript, Turn, parse_transcript, turn_text

LLM_KEY = "qwen3_8k"
LLM_TAB = "redact"
DEFAULT_ROLE = "a person"

NAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
                "required": ["name", "role"],
            },
        }
    },
    "required": ["names"],
}

NAMES_SYSTEM = (
    "You find the personal names of OTHER people inside one interview turn so they can be replaced by role tags. "
    "Answer with JSON only: {\"names\": [{\"name\": \"<the name exactly as written>\", \"role\": \"<one of the "
    "ROLES>\"}]}. Include first names, full names and nicknames of third parties. Never include the interviewee's "
    "own name, company or product names, places, band names or ordinary words. When the role is unclear use "
    "\"a person\". Return an empty list when the turn names nobody."
)

# ---------------------------------------------------------------------------
# regex layer (applied in this order: emails before URLs; phones before id numbers, but a phone never starts
# where a bare 9+-digit id number would match, so pure digit runs and 4-4-4-4 card groups stay id numbers)
# ---------------------------------------------------------------------------
_ID_NUMBER = r"\d(?:[ -]?\d){8,}(?![\w-])"
REGEX_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("email",
     # not when the local part is the userinfo of a URL (scheme://user@host), which is a profile-url
     re.compile(r"(?<![A-Za-z0-9._%+/-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
     "[email]"),
    ("profile-url",
     re.compile(
         r"(?:https?://)?(?:[\w-]+\.)*(?:twitter|x|instagram|github|facebook|tiktok)\.com/@?[\w.-]{2,}/?"
         r"|https?://[^\s/]+(?:/\S*?)?/(?:u|in)/[\w.-]+/?"
         r"|https?://[^\s/@]+@[^\s/]+\S*",
         re.I),
     "[profile-url]"),
    ("phone",
     re.compile(
         # international form: leading + and 7..15 digits with separators
         r"(?<![\w/.-])\+(?=(?:[\s().-]*\d){7,15}(?![\s().-]*\d))\(?\d[\d\s().-]{5,18}\d(?![\w-])"
         # local form: 7+ digits with separators, not a date, not where an id number starts
         r"|(?<![\w/.-])(?<!\d[ -])(?!" + _ID_NUMBER + r")(?=(?:[\s().-]*\d){7})(?!\d{4}-\d{2}-\d{2}(?![\d-]))"
         r"\(?\d[\d\s().-]{5,18}\d(?![\w-])"),
     "[phone]"),
    ("id-number",
     re.compile(r"(?<![\w-])" + _ID_NUMBER),
     "[id-number]"),
    ("address",
     re.compile(r"\b\d{1,5}[A-Za-z]?\s+(?:[A-Za-z]+\s+){0,3}(?:st|street|ave|avenue|rd|road|blvd|lane|ln|drive|dr)\b\.?",
                re.I),
     "[address]"),
]
RULE_NAMES = [name for name, _, _ in REGEX_RULES]

# ---------------------------------------------------------------------------
# deterministic name heuristic
# ---------------------------------------------------------------------------
_CAP_RUN_RE = re.compile(r"\b[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+\b")
_CAP_SINGLE_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
_LOWER_WORD_RE = re.compile(r"\b[a-z]{2,}\b")
_SENTENCE_END = set(".!?:;\"'“”‘’()[]{}\n")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
             "Mon", "Tue", "Tues", "Wed", "Thu", "Thur", "Thurs", "Fri", "Sat", "Sun")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec")
COMMON_CAPS = frozenset((
    "I", "Ok", "Okay", "Omg", "Ngl", "Tbh", "Idk", "Honestly", "Q", "A", "Block", "The", "And", "But", "Also", "Yes",
    "No", "Not", "Well", "Like", "Just", "Then", "Because", "Maybe", "Sure", "Wait", "Lol", "Yeah", "Nah", "Btw",
    "Fyi", "Hmm", "Anyway", "Same", "Right", "True", "Nope", "Thanks", "Sorry", "Please", "Hey", "Hello", "Hi",
    "God", "Christmas", "Easter", "Catholic", "Internet", "English", "Question", "Answer",
) + _WEEKDAYS + _MONTHS)


def _allowlist(own_name: str, corpus: str | None, text: str) -> set[str]:
    """Lowercased words the heuristic never treats as names."""
    allow = {w.lower() for w in COMMON_CAPS}
    allow.update(w.lower() for w in re.findall(r"[A-Za-z]+", own_name or ""))
    allow.update(_LOWER_WORD_RE.findall(corpus if corpus is not None else text))
    return allow


def _sentence_initial(text: str, pos: int) -> bool:
    before = text[:pos].rstrip(" \t")
    return not before or before[-1] in _SENTENCE_END


def find_names_heuristic(text: str, own_name: str = "", corpus: str | None = None) -> list[str]:
    """Deterministic third-party name candidates: runs of two or more capitalised words anywhere, plus single
    capitalised words ([A-Z][a-z]{2,}) that are not sentence-initial; minus the allowlist (I, the subject's
    own name, weekday/month names, common capitalised words, any word that also appears lowercase in the text)."""
    allow = _allowlist(own_name, corpus, text)
    found: list[str] = []

    def add(s: str) -> None:
        if s and s not in found:
            found.append(s)

    for m in _CAP_RUN_RE.finditer(text):
        toks = m.group(0).split()
        while toks and toks[0].lower() in allow:
            toks.pop(0)
        while toks and toks[-1].lower() in allow:
            toks.pop()
        if toks:
            add(" ".join(toks))
    for m in _CAP_SINGLE_RE.finditer(text):
        w = m.group(0)
        if w.lower() in allow or _sentence_initial(text, m.start()):
            continue
        add(w)
    return found


NAME_HEURISTIC = find_names_heuristic

# ---------------------------------------------------------------------------
# roles from the profile's People section
# ---------------------------------------------------------------------------
_ROLE_STOP = frozenset("""
is was are were be been being who whom whose and or but that which when where while to in on by with has have had
if so as because i we he she they it its not the a an for me you your will would can could does did do keeps keep
gets get gave give said says tells told calls call still also just then than very who's it's that's
""".split())
_ROLE_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_ROLE_MAX_WORDS = 6


def roles_from_people(people_text: str) -> list[str]:
    """Phrases starting with 'my ' in the People section ('my older brother', 'my best friend from art school'),
    plus 'i have a <role>' -> 'my <role>'; cut at punctuation, function words and adverbs, at most six words.
    'a person' is always appended last."""
    roles: list[str] = []

    def add(words: list[str]) -> None:
        kept: list[str] = []
        for w in words[:_ROLE_MAX_WORDS]:
            if w in _ROLE_STOP or (w.endswith("ly") and len(w) > 4):
                break
            kept.append(w)
        if kept:
            role = "my " + " ".join(kept)
            if role not in roles:
                roles.append(role)

    for line in (people_text or "").lower().splitlines():
        for seg in re.split(r"[,.;:()\[\]\n]", line):
            toks = _ROLE_TOKEN_RE.findall(seg)
            for i, tok in enumerate(toks):
                if tok == "my":
                    add(toks[i + 1:])
                elif tok == "i" and toks[i + 1:i + 3] and toks[i + 1] == "have" and toks[i + 2] in ("a", "an"):
                    add(toks[i + 3:])
    if DEFAULT_ROLE not in roles:
        roles.append(DEFAULT_ROLE)
    return roles


def roles_from_profile(profile) -> list[str]:
    return roles_from_people(getattr(profile, "people", "") or "")


def coerce_role(role, roles: list[str]) -> str:
    r = (role or "").strip().lower()
    for cand in roles:
        if r == cand.lower():
            return cand
    return DEFAULT_ROLE


# ---------------------------------------------------------------------------
# qwen3_8k pass (one call per TURN; tests replace twin.clients.ollama with a fake)
# ---------------------------------------------------------------------------
def find_names_llm(text: str, roles: list[str], tab: str = LLM_TAB) -> list[dict]:
    """Ask qwen3_8k which third-party names the text contains and which role each one is; one retry on invalid
    JSON. Roles are coerced to one of `roles`, else 'a person'."""
    roles = list(roles or [])
    if DEFAULT_ROLE not in roles:
        roles.append(DEFAULT_ROLE)
    messages = [
        {"role": "system", "content": NAMES_SYSTEM},
        {"role": "user", "content": "ROLES: " + "; ".join(roles) + "\n\nTURN:\n" + text},
    ]
    with MANAGER.session(LLM_KEY, tab=tab):
        for _attempt in range(2):
            resp = clients.ollama.chat(LLM_KEY, messages, format=NAMES_SCHEMA, options={"temperature": 0},
                                       num_predict=200, tab=tab)
            content = ((resp.get("message") or {}).get("content") or "") if isinstance(resp, dict) else ""
            try:
                data = json.loads(content)
                items = data["names"]
                if not isinstance(items, list):
                    raise TypeError("names is not a list")
            except (ValueError, KeyError, TypeError):
                continue
            out: list[dict] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or "").strip()
                if len(name) >= 2:
                    out.append({"name": name, "role": coerce_role(it.get("role"), roles)})
            return out
    return []


# ---------------------------------------------------------------------------
# text redaction
# ---------------------------------------------------------------------------
def _own_tokens(own_name: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]+", own_name or "")} | {(own_name or "").strip().lower()}


def _replace_all(text: str, needle: str, tag: str, ignore_case: bool) -> tuple[str, int]:
    pat = re.compile(r"(?<![\w\[])" + re.escape(needle) + r"(?![\w\]])", re.I if ignore_case else 0)
    return pat.subn(tag, text)


_NAME_TOKEN_RE = re.compile(r"[A-Z][a-z]+")


def plausible_name(name: str, allow: set[str]) -> bool:
    """Whether an LLM candidate looks like a personal name as written: at least one token with a capitalised
    word ([A-Z][a-z]+, so 'Tobias Wren', 'Sam', "O'Brien") whose lowercase form is not on the heuristic's
    allowlist. qwen3 regularly returns pronouns, role phrases, common nouns and acronyms ('you', 'she',
    'my grandmother', 'the cat', 'AI'); replacing those with '[a person]' mangled the text ("when [a person]'re
    lying"), so they are left alone (the live run of 2026-09-14 returned 28 such items in 60 turns)."""
    for tok in (name or "").split():
        if _NAME_TOKEN_RE.search(tok) and tok.lower().strip("'\".,;:()[]") not in allow:
            return True
    return False


def _redact_detail(text: str, *, use_llm: bool, roles: list[str] | None, own_name: str,
                   corpus: str | None) -> tuple[str, dict, list[str]]:
    roles = list(roles or [])
    if DEFAULT_ROLE not in roles:
        roles.append(DEFAULT_ROLE)
    counts: dict[str, int] = {name: 0 for name in RULE_NAMES}
    counts["names_heuristic"] = 0
    counts["names_llm"] = 0
    replacements: list[str] = []
    removed: list[str] = []

    for name, pat, tag in REGEX_RULES:
        hits = [m.group(0) for m in pat.finditer(text)]
        if not hits:
            continue
        text = pat.sub(tag, text)
        counts[name] += len(hits)
        replacements.extend([tag] * len(hits))
        removed.extend(hits)

    own = _own_tokens(own_name)
    if use_llm:
        names = find_names_llm(text, roles)
        allow = _allowlist(own_name, corpus, text)
        for item in sorted(names, key=lambda d: -len(d["name"])):
            nm = item["name"]
            if nm.lower() in own or not plausible_name(nm, allow):
                continue
            tag = f"[{item['role']}]"
            text, n = _replace_all(text, nm, tag, ignore_case=True)
            if n:
                counts["names_llm"] += n
                replacements.extend([tag] * n)
                removed.append(nm)

    for cand in sorted(find_names_heuristic(text, own_name=own_name, corpus=corpus), key=len, reverse=True):
        tag = f"[{DEFAULT_ROLE}]"
        text, n = _replace_all(text, cand, tag, ignore_case=False)
        if n:
            counts["names_heuristic"] += n
            replacements.extend([tag] * n)
            removed.append(cand)

    return text, {"counts": counts, "replacements": replacements}, removed


def redact_text(text: str, *, use_llm: bool = True, roles: list[str] | None = None, own_name: str = "",
                corpus: str | None = None) -> tuple[str, dict]:
    """(redacted_text, report). report = {"counts": {rule: n, "names_heuristic": n, "names_llm": n},
    "replacements": [tags only]}. `corpus` (optional) is the whole file, used for the heuristic's
    'appears lowercase elsewhere' allowlist."""
    red, report, _removed = _redact_detail(text, use_llm=use_llm, roles=roles, own_name=own_name, corpus=corpus)
    return red, report


# ---------------------------------------------------------------------------
# whole transcript
# ---------------------------------------------------------------------------
def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def default_output_path(src: Path) -> Path:
    src = Path(src)
    if _same_path(src, TRANSCRIPT_PATH):
        return REDACTED_TRANSCRIPT_PATH
    return src.with_name(src.stem + ".redacted.md")


def _split_qa(red: str) -> tuple[str, str]:
    body = red[2:].lstrip() if red.startswith("Q:") else red
    if "\nA:" in body:
        q, a = body.split("\nA:", 1)
        return q.strip(), a.strip()
    return body.strip(), ""


def render_transcript(t: Transcript, turns: list[tuple[Turn, str, str]], extra_meta: dict[str, str]) -> str:
    meta = dict(t.meta)
    meta.setdefault("name", t.name)
    meta.setdefault("date", t.date)
    meta.setdefault("blocks", str(t.blocks))
    meta["exclude_blocks"] = "[" + ", ".join(str(b) for b in t.exclude_blocks) + "]"
    for k, v in extra_meta.items():
        meta[k] = v
    lines = ["---"] + [f"{k}: {v}" for k, v in meta.items()] + ["---"]
    current_block: int | None = None
    for turn, q, a in turns:
        if turn.block != current_block:
            current_block = turn.block
            lines.append("")
            lines.append(f"# Block {turn.block}: {t.block_titles.get(turn.block, '')}".rstrip(": "))
        lines.append("")
        lines.append(f"## {turn.id}")
        lines.append(f"Q: {q}")
        lines.append(f"A: {a}")
    return "\n".join(lines) + "\n"


def redact_transcript(src: Path, dst: Path | None = None, *, use_llm: bool = True, profile=None,
                      on_removed=None) -> dict:
    """Redact every turn of `src` (one qwen3_8k call per turn when use_llm) and write the redacted transcript
    (frontmatter gains redacted: true, source_sha, redacted_at) plus REDACTION_REPORT_PATH. Returns the report.
    `on_removed(list[str])`, when given, receives the removed strings for a console check; they are never
    written to a file."""
    src = Path(src)
    raw = src.read_bytes()
    text = raw.decode("utf-8-sig")
    source_sha = hashlib.sha256(raw).hexdigest()
    t = parse_transcript(text, str(src))
    dst = Path(dst) if dst else default_output_path(src)

    if profile is None:
        try:
            profile = profile_mod.load_profile()
        except Exception:  # noqa: BLE001
            profile = None
    roles = roles_from_profile(profile) if profile is not None else [DEFAULT_ROLE]
    own_name = t.name or (getattr(profile, "name", "") if profile is not None else "")

    counts: dict[str, int] = {name: 0 for name in RULE_NAMES}
    counts["names_heuristic"] = 0
    counts["names_llm"] = 0
    replacements: list[str] = []
    removed: list[str] = []
    out_turns: list[tuple[Turn, str, str]] = []
    for turn in t.turns:
        red, rep, rem = _redact_detail(turn_text(turn), use_llm=use_llm, roles=roles, own_name=own_name, corpus=text)
        for k, v in rep["counts"].items():
            counts[k] = counts.get(k, 0) + v
        replacements.extend(rep["replacements"])
        removed.extend(x for x in rem if x not in removed)
        q, a = _split_qa(red)
        out_turns.append((turn, q, a))

    redacted_at = datetime.now().astimezone().isoformat(timespec="seconds")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render_transcript(t, out_turns, {"redacted": "true", "source_sha": source_sha,
                                                     "redacted_at": redacted_at}), encoding="utf-8")
    report = {
        "source": str(src), "source_sha": source_sha, "output": str(dst), "turns": len(t.turns),
        "llm": bool(use_llm), "counts": counts, "replacements": replacements, "redacted_at": redacted_at,
    }
    REDACTION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REDACTION_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if on_removed is not None:
        on_removed(removed)
    return report


def load_report() -> dict | None:
    try:
        data = json.loads(REDACTION_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def report_lines(report: dict) -> list[str]:
    tags: dict[str, int] = {}
    for tag in report.get("replacements", []):
        tags[tag] = tags.get(tag, 0) + 1
    counts = report.get("counts", {})
    return [
        f"redacted {report.get('source')} -> {report.get('output')}",
        f"turns: {report.get('turns')}, llm pass: {'yes' if report.get('llm') else 'no (--no-llm)'}, "
        f"source sha {str(report.get('source_sha', ''))[:12]}, at {report.get('redacted_at')}",
        "counts: " + ", ".join(f"{k} {v}" for k, v in counts.items()),
        "tags used: " + (", ".join(f"{k} x{v}" for k, v in tags.items()) or "none"),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m twin.redact")
    ap.add_argument("path", help="transcript to redact (data/interview_transcript.md or the example)")
    ap.add_argument("--out", help="output path (default: data/interview_transcript.redacted.md for the real file, "
                                  "<name>.redacted.md next to any other file)")
    ap.add_argument("--no-llm", action="store_true", help="regex + name heuristic only (no qwen3_8k call)")
    args = ap.parse_args(argv)
    removed: list[str] = []
    try:
        report = redact_transcript(Path(args.path), Path(args.out) if args.out else None, use_llm=not args.no_llm,
                                   on_removed=removed.extend)
    except FileNotFoundError as e:
        print(f"error: {e}")
        return 2
    finally:
        if not args.no_llm:
            try:
                for e in clients.ollama.ps():
                    name = e.get("name") or e.get("model")
                    if name:
                        clients.ollama.stop(name)
            except Exception:  # noqa: BLE001
                pass
    for ln in report_lines(report):
        print(ln)
    print(f"report: {REDACTION_REPORT_PATH}")
    print("removed (console only, never written to a file): " + ("; ".join(removed) if removed else "nothing"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
