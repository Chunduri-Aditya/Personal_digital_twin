"""P5 critic 3, read-only scratch helper: unified diff of project files against scripts/dev/finish/backup_pre_c.
Usage: python scripts/dev/finish/critic3_p5_filediff.py tests/test_theme.py static/twin.css ...
Prints the diff only; nothing is written."""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BAK = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"


def main(argv: list[str]) -> int:
    for rel in argv:
        cur, bak = ROOT / rel, BAK / rel
        if not cur.exists() or not bak.exists():
            print(f"== {rel}: current={cur.exists()} backup={bak.exists()}")
            continue
        diff = list(difflib.unified_diff(bak.read_text(encoding="utf-8").splitlines(),
                                         cur.read_text(encoding="utf-8").splitlines(),
                                         f"backup/{rel}", f"current/{rel}", lineterm="", n=1))
        print(f"== {rel}: {len(diff)} diff lines")
        print("\n".join(diff))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
