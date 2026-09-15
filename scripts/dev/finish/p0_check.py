"""PLAN_FINISH P0 preflight checks that need file walking (run as a file, never via `python -`).

Usage: python scripts/dev/finish/p0_check.py <snapshot.json> [--out <report.json>]

Compares the data/ file list with scripts/dev/demo/data_files_before.txt, the scores.json SHA
with the snapshot, and the last-write times of twin/, tests/, static/ and app.py with the
snapshot's code_last_write_utc. Prints a short report and optionally writes it as JSON.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def rel(p):
    return os.path.relpath(p, ROOT).replace("/", "\\")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def code_files():
    out = {}
    for top in ("twin", "tests", "static"):
        base = os.path.join(ROOT, top)
        for d, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".pytest_cache")]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                p = os.path.join(d, name)
                out[rel(p)] = p
    out["app.py"] = os.path.join(ROOT, "app.py")
    return out


def utc_iso(path):
    ts = os.path.getmtime(path)
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc)


def parse_iso(s):
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?Z", s)
    base = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
    frac = float(m.group(2)) if m.group(2) else 0.0
    return base + dt.timedelta(seconds=frac)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    snap_path = os.path.join(ROOT, sys.argv[1])
    out_path = None
    if "--out" in sys.argv:
        out_path = os.path.join(ROOT, sys.argv[sys.argv.index("--out") + 1])
    with open(snap_path, encoding="utf-8-sig") as f:
        snap = json.load(f)

    report = {"snapshot": rel(snap_path)}

    # data/ file list
    with open(os.path.join(ROOT, "scripts", "dev", "demo", "data_files_before.txt"), encoding="utf-8-sig") as f:
        before = sorted(line.strip() for line in f if line.strip())
    now = []
    for d, dirs, files in os.walk(os.path.join(ROOT, "data")):
        for name in files:
            now.append(rel(os.path.join(d, name)))
    now.sort()
    report["data_files_match"] = before == now
    report["data_files_added"] = sorted(set(now) - set(before))
    report["data_files_removed"] = sorted(set(before) - set(now))
    report["act_answer_absent"] = not os.path.exists(os.path.join(ROOT, "data", "act_answer.txt"))

    # scores SHA
    sha = sha256(os.path.join(ROOT, "data", "items", "scores.json"))
    report["scores_sha"] = sha
    report["scores_sha_match"] = sha == snap.get("scores_json_sha256", "").upper()

    # code write times
    pinned = snap.get("code_last_write_utc", {})
    files = code_files()
    changed, added = [], []
    for r, p in sorted(files.items()):
        t = utc_iso(p)
        if r not in pinned:
            added.append({"file": r, "utc": t.isoformat()})
            continue
        if abs((t - parse_iso(pinned[r])).total_seconds()) > 1.0:
            changed.append({"file": r, "pinned": pinned[r], "now": t.isoformat()})
    removed = sorted(set(pinned) - set(files))
    report["code_changed"] = changed
    report["code_added"] = added
    report["code_removed"] = removed
    report["code_match"] = not (changed or added or removed)

    # rehearsal runs
    nums = []
    for name in os.listdir(os.path.join(ROOT, "scripts", "dev", "demo")):
        m = re.match(r"rehearsal_run(\d+)\.log$", name)
        if m:
            nums.append(int(m.group(1)))
    report["highest_run"] = max(nums) if nums else 0
    report["next_run"] = report["highest_run"] + 1

    # deliverable write times (for the launch state)
    docs = ["docs/DEMO.md", "docs/demo/beats.json", "docs/ARCHITECTURE.md", "docs/CLIENT_TALKING_POINTS.md",
            "scripts/demo_prep.ps1", "scripts/demo_rehearse.py", "scripts/dev/demo/rehearsal.md", "docs/PLAN_DEMO.md"]
    report["deliverables_utc"] = {}
    for d in docs:
        p = os.path.join(ROOT, d)
        report["deliverables_utc"][d] = utc_iso(p).isoformat() if os.path.exists(p) else None

    text = json.dumps(report, indent=1)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
