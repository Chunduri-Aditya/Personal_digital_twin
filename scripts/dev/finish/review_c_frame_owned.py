"""Review helper (P3 frame, round 1): which files under twin/ui, static, tests and app.py differ from the pre-restyle
backup (scripts/dev/finish/backup_pre_c)? The frame agent owns only twin/ui/frame.py, twin/ui/theme.py,
static/twin.css, static/tabs/frame.css and tests/test_theme.py. Also lists twin/pipelines files newer than the backup."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BK = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"
OWNED = {"twin/ui/frame.py", "twin/ui/theme.py", "static/twin.css", "static/tabs/frame.css", "tests/test_theme.py"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def files(base: Path) -> set[str]:
    out = set()
    for sub in ("twin/ui", "static", "tests"):
        d = base / sub
        if d.exists():
            out |= {p.relative_to(base).as_posix() for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    if (base / "app.py").exists():
        out.add("app.py")
    return out


def main() -> int:
    old, new = files(BK), files(ROOT)
    changed = sorted(f for f in old & new if sha(BK / f) != sha(ROOT / f))
    added = sorted(new - old)
    removed = sorted(old - new)
    print("backup files:", len(old), "current files:", len(new))
    print("changed:", changed)
    print("added:", added)
    print("removed:", removed)
    bad = [f for f in changed + added + removed if f not in OWNED]
    print("changed/added/removed outside the frame agent's files:", bad)
    bk_time = min((BK / f).stat().st_mtime for f in old)
    newer = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "twin").rglob("*.py")
                   if "__pycache__" not in p.parts and not p.is_relative_to(ROOT / "twin" / "ui")
                   and p.stat().st_mtime > bk_time)
    print("twin/** (outside twin/ui) newer than the backup:", newer)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
