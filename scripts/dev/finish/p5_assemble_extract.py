"""P5 assemble helper (read-only): per-lane summary from c_results.json and p3_results.json."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
c = json.loads((ROOT / "scripts/dev/finish/c_results.json").read_text(encoding="utf-8"))
p3 = json.loads((ROOT / "scripts/dev/finish/p3_results.json").read_text(encoding="utf-8"))
print("c_results top keys:", list(c.keys()))
for k, v in c.items():
    if k != "lanes":
        s = json.dumps(v, ensure_ascii=False)
        print(f"  {k}: {s[:600]}")
print("P3 frame reviews:", p3.get("reviews"), "fixes:", len(p3.get("fixes") or []),
      "final go:", p3["final"]["go"], "must_fix:", len(p3["final"]["must_fix"]),
      "should_fix:", len(p3["final"]["should_fix"]))
print("P3 wdg:", p3["final"]["checks_run"][0][:300])
for key, lane in c["lanes"].items():
    print("=" * 80)
    print("LANE", key, "status", lane.get("status"), "port", lane.get("port"), "tabs", lane.get("tabs"))
    print("  keys:", list(lane.keys()))
    for r in ("review_r1", "review_r2"):
        print(f"  {r}:", lane.get(r))
    print("  final_must_fix:", len(lane.get("final_must_fix") or []), "unresolved:", len(lane.get("unresolved_must_fix") or []),
          "final_should_fix:", len(lane.get("final_should_fix") or []))
    for fk in ("demo_impact", "frame_requests", "fixes", "fix_r1"):
        if fk in lane:
            v = lane[fk]
            print(f"  {fk}: {len(v) if isinstance(v, list) else json.dumps(v)[:200]}")
    fcr = lane.get("final_checks_run") or []
    for line in fcr:
        if "web-design-guidelines" in line[:80]:
            print("  WDG:", line[:400])
        if "pytest" in line[:120]:
            print("  PYTEST:", line[:200])
    # checks that mention scrollWidth / scope
    for line in (lane.get("checks") or []):
        if re.search(r"ui_check\.ps1", line):
            print("  UICHECK:", line[:350])
            break
    # private events
    blob = json.dumps(lane, ensure_ascii=False)
    ev = sorted(set(re.findall(r"api_name=False[^\"]{0,80}", blob)))
    for e in ev[:6]:
        print("  EVENT:", e)
