"""P5 critic 3 (correctness), read-only scratch helper: does every bold label quoted in docs/DEMO.md sections 3-4,
every quoted "Point at" fragment and every docs/demo/beats.json expect string still have a source in the code?

Sources searched: twin/**/*.py, app.py, scripts/dev/live_drive.py (the rehearsal's output headers).
Strings with an ellipsis are split at the ellipsis and each fragment is searched on its own.
Prints FOUND / NOT FOUND per string; nothing is written.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "docs" / "DEMO.md"
BEATS = ROOT / "docs" / "demo" / "beats.json"


def corpus() -> str:
    parts = []
    for p in list((ROOT / "twin").rglob("*.py")) + [ROOT / "app.py", ROOT / "scripts" / "dev" / "live_drive.py"]:
        if "__pycache__" in p.parts:
            continue
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def section(text: str, start: str, end: str) -> str:
    a = text.index(start)
    b = text.index(end, a)
    return text[a:b]


def fragments(s: str) -> list[str]:
    out = []
    for piece in re.split(r"…|\.\.\.(?=\s|$)", s):
        piece = piece.strip().strip("\"'`").strip()
        if len(piece) >= 3:
            out.append(piece)
    return out


def main() -> int:
    code = corpus()
    code_nomd = code.replace("\\n", "\n")
    demo = DEMO.read_text(encoding="utf-8")
    body = section(demo, "## 3. Never click live", "### Inputs to paste")
    bold = sorted(set(re.findall(r"\*\*([^*\n]+?)\*\*", body)))
    missing = []
    print(f"== bold labels in DEMO.md sections 3-4: {len(bold)}")
    for label in bold:
        frs = fragments(label) or [label]
        hit = all((f in code) or (f in code_nomd) for f in frs)
        print(f"  {'FOUND    ' if hit else 'NOT FOUND'} **{label}**")
        if not hit:
            missing.append(("bold", label))
    # double-quoted fragments in the Point at column of the beat table (and the gpu note sentence in section 2)
    table = section(demo, "## 4. Beat table", "**P-02 is not part")
    quotes = []
    for line in table.splitlines():
        if not line.startswith("| B"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 6:
            quotes.extend(re.findall(r"\"([^\"]+)\"", cells[5]))
    quotes.append("GPU: idle. Select a tab to pre-warm its model.")
    print(f"== quoted Point at fragments: {len(quotes)}")
    for q in quotes:
        frs = fragments(q.replace("**", ""))
        if not frs:
            continue
        found = [f for f in frs if (f in code) or (f in code_nomd)]
        status = "FOUND    " if len(found) == len(frs) else ("PARTIAL  " if found else "NOT FOUND")
        print(f"  {status} \"{q}\"  fragments={frs} missing={[f for f in frs if f not in found]}")
        if status != "FOUND    ":
            missing.append(("quote", q))
    beats = json.loads(BEATS.read_text(encoding="utf-8"))
    exp = set()
    for b in beats:
        e = b.get("expect") or {}
        for k in ("contains_all", "contains_any"):
            exp.update(e.get(k) or [])
    print(f"== beats.json expect strings (contains_all + contains_any): {len(exp)}")
    for s in sorted(exp):
        hit = s in code
        print(f"  {'FOUND    ' if hit else 'NOT FOUND'} {s!r}")
        if not hit:
            missing.append(("expect", s))
    print(f"== not found or partial: {len(missing)}")
    for kind, s in missing:
        print(f"  {kind}: {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
