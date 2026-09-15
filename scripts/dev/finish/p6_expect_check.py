"""P6 (docs mode) read-only re-check of every docs/demo/beats.json expect against one rehearsal run's files, written
separately from scripts/demo_rehearse.py's checker so the two can be compared. Also checks BX.1's expect against P5's
scripts/dev/evidence/stage7_see.txt (a live_drive see call, not a rehearsal step) and prints the waits each file records.
Writes nothing.

    $env:PYTHONUTF8='1'; python scripts/dev/finish/p6_expect_check.py 12
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "scripts" / "dev" / "demo"
LABEL_RE = re.compile(r"^(?:\[\+[\d.]+ s\] )?=== (.*) ===\s*$")
PREFIX_RE = re.compile(r"^\[\+[\d.]+ s\] ")


def parse(path: Path) -> tuple[str, dict[str, str], list[str]]:
    """(scanned text without '# ' header lines or '[+x s] ' prefixes, sections by label, header lines)."""
    raw = path.read_text(encoding="utf-8")
    body, head = [], []
    secs: dict[str, list[str]] = {}
    cur = None
    for line in raw.splitlines():
        if line.startswith("# "):
            head.append(line)
            continue
        m = LABEL_RE.match(line)
        body.append(PREFIX_RE.sub("", line))
        if m:
            cur = m.group(1)
            secs.setdefault(cur, [])
            continue
        if cur is not None:
            secs[cur].append(line)
    return "\n".join(body), {k: "\n".join(v) for k, v in secs.items()}, head


def check(expect: dict, text: str, secs: dict[str, str]) -> list[str]:
    notes = []
    for s in expect.get("contains_all") or []:
        if s not in text:
            notes.append(f"contains_all missing {s!r}")
    any_of = expect.get("contains_any") or []
    if any_of and not any(s in text for s in any_of):
        notes.append(f"contains_any: none of {any_of!r}")
    for s in expect.get("not_contains") or []:
        if s in text:
            notes.append(f"not_contains found {s!r}")
    if expect.get("reply_nonempty"):
        r = secs.get("reply_text")
        if r is None or not r.strip():
            notes.append("reply_nonempty: reply_text missing or empty")
    bans = expect.get("answer_not_contains") or []
    if bans:
        a = secs.get("answer")
        if a is None:
            notes.append("answer_not_contains: no answer block")
        else:
            notes += [f"answer_not_contains found {s!r}" for s in bans if s in a]
    return notes


def waits(text: str, head: list[str], raw_path: Path) -> str:
    parts = []
    m = re.search(r"wall (\d+) ms", " ".join(head))
    if m:
        parts.append(f"machine {int(m.group(1)) / 1000:.2f} s")
    m = re.search(r"=== wall ([\d.]+) s ===", text)
    if m:
        parts.append(f"live_drive wall {m.group(1)} s")
    m = re.search(r"ready in ([\d.]+) s", text)
    if m:
        parts.append(f"warm note {m.group(1)} s")
    m = re.search(r"^- total ([\d.]+) (m?s)$", text, re.M)
    if m:
        parts.append(f"trace total {m.group(1)} {m.group(2)}")
    m = re.search(r'"timing_ms": ([\d.]+)', text)
    if m:
        parts.append(f"decide timing {float(m.group(1)) / 1000:.2f} s")
    stamps = dict(re.findall(r"^\[\+([\d.]+) s\] === (result_md|say_it) ===", raw_path.read_text(encoding="utf-8"), re.M)[::-1] and
                  [(k, v) for v, k in re.findall(r"^\[\+([\d.]+) s\] === (result_md|say_it) ===",
                                                 raw_path.read_text(encoding="utf-8"), re.M)])
    if "result_md" in stamps:
        parts.append(f"to verdict {stamps['result_md']} s")
    if "result_md" in stamps and "say_it" in stamps:
        parts.append(f"say_it segment {float(stamps['say_it']) - float(stamps['result_md']):.2f} s")
    return "; ".join(parts)


def main() -> int:
    run = sys.argv[1] if len(sys.argv) > 1 else "12"
    beats = json.loads((ROOT / "docs" / "demo" / "beats.json").read_text(encoding="utf-8"))
    checked = failed = 0
    for b in beats:
        sid = b["id"]
        if b.get("forbidden"):
            continue
        f = DEMO / f"run{run}_{sid}.txt"
        tag = "optional" if b.get("optional") else "main"
        if not f.exists():
            print(f"{sid:5} [{tag}] no run{run} file ({'view-only' if not b.get('live_drive_args') else 'not run'})")
            continue
        text, secs, head = parse(f)
        exp = b.get("expect")
        if not exp:
            print(f"{sid:5} [{tag}] file present, no expect (view-only)")
            continue
        notes = check(exp, text, secs)
        checked += 1
        failed += bool(notes)
        n_keys = sum(len(exp.get(k) or []) for k in ("contains_all", "contains_any", "not_contains", "answer_not_contains"))
        print(f"{sid:5} [{tag}] {'OK' if not notes else 'FAIL'} ({n_keys} strings"
              f"{', reply_nonempty' if exp.get('reply_nonempty') else ''}) | {waits(text, head, f)}")
        for n in notes:
            print(f"        {n}")
    see = ROOT / "scripts" / "dev" / "evidence" / "stage7_see.txt"
    bx1 = next((b for b in beats if b["id"] == "BX.1"), None)
    if see.exists() and bx1 and bx1.get("expect"):
        text, secs, head = parse(see)
        notes = check(bx1["expect"], text, secs)
        print(f"BX.1  vs stage7_see.txt (P5 7.3, live_drive see without the BX.0 pre-warm): "
              f"{'OK' if not notes else 'FAIL'} | {waits(text, head, see)}")
        for n in notes:
            print(f"        {n}")
    print(f"run {run}: {checked} steps with expect checked, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
