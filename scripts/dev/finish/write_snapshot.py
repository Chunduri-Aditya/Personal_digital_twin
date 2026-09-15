"""Write a PLAN_FINISH snapshot JSON (run as a file, never via `python -`).

Usage (project root):
  python scripts/dev/finish/write_snapshot.py <out.json> --reason "text" [--pytest "551 passed, 2 warnings in 25s"]

Records taken_at (local time), reason, pytest (summary plus parsed passed/failed), scores_json_sha256,
data_files_match_baseline (against scripts/dev/demo/data_files_before.txt, with added and removed lists),
act_answer_absent, and code_last_write_utc for every file under twin/, tests/ and static/ (no __pycache__ or .pyc)
plus app.py, in the same shape as scripts/dev/demo/post_fix_snapshot.json so p0_check.py can compare against it.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p0_check  # noqa: E402  (same folder: ROOT, code_files, sha256, rel, utc_iso)

ROOT = p0_check.ROOT


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        print(__doc__)
        return 2
    out = sys.argv[1]
    out_path = out if os.path.isabs(out) else os.path.join(ROOT, out)
    summary = _arg("--pytest", "")
    passed = re.search(r"(\d+) passed", summary or "")
    failed = re.search(r"(\d+) failed", summary or "")

    with open(os.path.join(ROOT, "scripts", "dev", "demo", "data_files_before.txt"), encoding="utf-8-sig") as f:
        before = sorted(line.strip() for line in f if line.strip())
    now = sorted(p0_check.rel(os.path.join(d, n)) for d, _, files in os.walk(os.path.join(ROOT, "data")) for n in files)

    snap = {
        "taken_at": dt.datetime.now().astimezone().isoformat(),
        "reason": _arg("--reason", ""),
        "pytest": {"summary": summary, "passed": int(passed.group(1)) if passed else None,
                   "failed": int(failed.group(1)) if failed else (0 if passed else None)},
        "scores_json_sha256": p0_check.sha256(os.path.join(ROOT, "data", "items", "scores.json")),
        "data_files_match_baseline": before == now,
        "data_files_added": sorted(set(now) - set(before)),
        "data_files_removed": sorted(set(before) - set(now)),
        "act_answer_absent": not os.path.exists(os.path.join(ROOT, "data", "act_answer.txt")),
        "code_last_write_utc": {r: p0_check.utc_iso(p).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                                for r, p in sorted(p0_check.code_files().items())},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1)
        f.write("\n")
    print(f"wrote {out}: {len(snap['code_last_write_utc'])} code files, scores {snap['scores_json_sha256'][:12]}..., "
          f"data match {snap['data_files_match_baseline']}, pytest '{summary}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
