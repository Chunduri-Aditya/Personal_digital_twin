"""Review helper (P3 frame, round 1): every bold label quoted in docs/DEMO.md sections 3-4 must still appear in
twin/ui/*.py (or app.py / twin/ui/state.py for header text). Also diff static/twin.css against the pre-restyle
backup (stat only). Reads files only."""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def section_lines(text: str, start_pat: str, end_pat: str) -> list[str]:
    lines = text.splitlines()
    s = next(i for i, l in enumerate(lines) if re.match(start_pat, l))
    e = next(i for i, l in enumerate(lines) if i > s and re.match(end_pat, l))
    return lines[s:e]


def main() -> int:
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    sec = section_lines(demo, r"^## 3\.", r"^## 5\.")
    bolds: list[str] = []
    for l in sec:
        for m in re.finditer(r"\*\*(.+?)\*\*", l):
            b = m.group(1).strip()
            if b not in bolds:
                bolds.append(b)
    ui_src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "twin" / "ui").glob("*.py")))
    ui_src += "\n" + (ROOT / "app.py").read_text(encoding="utf-8")
    # also the pipelines' output text (labels such as trace lines are not labels, but report them)
    missing = []
    for b in bolds:
        plain = b.strip("`").rstrip(":").strip()
        found = plain in ui_src or plain.replace("'", "\\'") in ui_src
        if not found:
            missing.append(b)
        print(f"{'ok     ' if found else 'MISSING'} {b}")
    print(f"\n{len(bolds)} bold strings in DEMO.md sections 3-4; not found in twin/ui/*.py + app.py: {len(missing)}")
    for b in missing:
        print("   ", b)
    # compare to backup: were the missing ones also missing before the restyle?
    bk = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"
    bk_src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((bk / "twin" / "ui").glob("*.py")))
    bk_src += "\n" + (bk / "app.py").read_text(encoding="utf-8")
    regress = [b for b in missing if b.strip("`").rstrip(":").strip() in bk_src]
    print("missing now but present in backup_pre_c (a regression):", regress)
    print("\n==== static/twin.css vs backup_pre_c/static/twin.css ====")
    old = (bk / "static" / "twin.css").read_text(encoding="utf-8").splitlines(keepends=True)
    new = (ROOT / "static" / "twin.css").read_text(encoding="utf-8").splitlines(keepends=True)
    diff = list(difflib.unified_diff(old, new, "backup/twin.css", "twin.css", n=0))
    adds = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    dels = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    print(f"old {len(old)} lines, new {len(new)} lines, +{adds} -{dels}")
    print("removed selector lines:")
    for l in diff:
        if l.startswith("-") and not l.startswith("---") and "{" in l:
            print("   ", l.rstrip())
    print("backup static/tabs:", sorted(p.name for p in (bk / "static").rglob("*.css")))
    return 1 if regress else 0


if __name__ == "__main__":
    sys.exit(main())
