"""Review helper (read-only): every bold string quoted in docs/DEMO.md sections 3-4 that appears in the pre-restyle
twin/ui/evals.py or twin/ui/status.py must still appear in the current files; also lists the bold labels found in
neither lane file (they belong to other tabs or to pipeline output). Also checks the beats.json expect strings of
the B7 and B8 beats against the current twin/ and app.py sources. Writes nothing but stdout."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts" / "dev" / "finish" / "backup_pre_c"
LANE = ["twin/ui/evals.py", "twin/ui/status.py"]

demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
m3 = demo.index("\n## 3.")
m5 = demo.index("\n## 5.")
section = demo[m3:m5]
bold = sorted(set(re.findall(r"\*\*([^*\n]+?)\*\*", section)))


def src(paths, base):
    return "\n".join((base / p).read_text(encoding="utf-8") for p in paths)


old = src(LANE, BACKUP)
new = src(LANE, ROOT)
all_new = "\n".join(p.read_text(encoding="utf-8") for p in list((ROOT / "twin").rglob("*.py")) + [ROOT / "app.py"])


def present(label: str, text: str) -> bool:
    variants = {label, label.rstrip(":"), label.replace("\\", "\\\\")}
    return any(v and v in text for v in variants)


in_lane_before = [b for b in bold if present(b, old)]
lost = [b for b in in_lane_before if not present(b, new)]
elsewhere = [b for b in bold if not present(b, old)]
print(f"bold strings in DEMO.md sections 3-4: {len(bold)}")
print(f"present in the pre-restyle lane files: {len(in_lane_before)} -> {in_lane_before}")
print(f"missing from the current lane files: {lost}")
print(f"not in the lane files (other tabs or pipeline output): {len(elsewhere)}; "
      f"of those missing from all current twin/ + app.py: {[b for b in elsewhere if not present(b, all_new)]}")

beats = json.loads((ROOT / "docs" / "demo" / "beats.json").read_text(encoding="utf-8"))
items = beats if isinstance(beats, list) else beats.get("beats") or beats.get("steps") or []
checked = 0
for b in items:
    bid = str(b.get("id", ""))
    if not (bid.startswith("B7") or bid.startswith("B8") or bid.startswith("BX.2")):
        continue
    exp = b.get("expect")
    strings = []
    if isinstance(exp, str):
        strings = [exp]
    elif isinstance(exp, list):
        strings = [e if isinstance(e, str) else json.dumps(e) for e in exp]
    elif isinstance(exp, dict):
        for v in exp.values():
            strings += v if isinstance(v, list) else [v]
    print(f"{bid}: expect={json.dumps(exp)[:300]}")
    checked += 1
print(f"B7/B8/BX.2 beats listed: {checked}")
sys.exit(1 if lost else 0)
