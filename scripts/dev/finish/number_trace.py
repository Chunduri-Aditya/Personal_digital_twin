"""PLAN_DEMO Verification 6 helper (run as a file): every number in a client-facing doc must turn up in a text search of
docs/EVIDENCE2.md, the source JSON (data/items/scores.json, data/eval_results.json, data/probes.json) or
scripts/dev/demo/rehearsal.md. Prints the numbers not found, with their line numbers, for a human to judge.

Skipped: inline code spans (paths and line citations), heading and list numbering, beat and item ids (B4.1, P-02,
D-08, Q-12, T-004a, GOLD_Q-12). A decimal in the doc also matches a longer source value that rounds to it
(0.88 matches 0.8823).

Usage (project root): python scripts/dev/finish/number_trace.py [docs/CLIENT_TALKING_POINTS.md] [--out report.json]
"""
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SOURCES = ["docs/EVIDENCE2.md", "data/items/scores.json", "data/eval_results.json", "data/probes.json",
           "scripts/dev/demo/rehearsal.md"]
NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")
IDS = re.compile(r"\b(?:B\d+(?:\.\d+)?|P-\d+|D-\d+|Q-\d+|T-\d+[a-z]?|GOLD_Q-\d+|IPIP_[A-Z]\d+|run\d+)\b")


def source_numbers():
    exact, floats = set(), []
    for rel in SOURCES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        for m in NUM.finditer(text):
            s = m.group(1)
            exact.add(s)
            if "." in s:
                try:
                    floats.append(float(s))
                except ValueError:
                    pass
    return exact, floats


def found(s, exact, floats):
    if s in exact:
        return True
    if "." in s:
        k = len(s.split(".")[1])
        v = float(s)
        return any(round(f, k) == v for f in floats)
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    doc = args[0] if args else "docs/CLIENT_TALKING_POINTS.md"
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    exact, floats = source_numbers()
    missing, total = [], 0
    in_fence = False
    for i, line in enumerate(open(os.path.join(ROOT, doc), encoding="utf-8").read().splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        text = re.sub(r"`[^`]*`", " ", line)
        text = re.sub(r"^\s*#+\s*\d+(\.\d+)*\.?", " ", text)
        text = re.sub(r"^\s*\d+\.\s", " ", text)
        text = IDS.sub(" ", text)
        text = re.sub(r"\([^)]*\.(md|json|py|ps1|txt|log)[^)]*\)", " ", text)
        for m in NUM.finditer(text):
            total += 1
            s = m.group(1)
            if not found(s, exact, floats):
                missing.append({"line": i, "number": s, "text": line.strip()[:220]})
    print(f"{doc}: {total} numbers checked, {len(missing)} not found in {', '.join(SOURCES)}")
    for item in missing:
        print(f"  line {item['line']}: {item['number']}  | {item['text']}")
    if out:
        with open(os.path.join(ROOT, out), "w", encoding="utf-8") as f:
            json.dump({"doc": doc, "sources": SOURCES, "checked": total, "missing": missing}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
