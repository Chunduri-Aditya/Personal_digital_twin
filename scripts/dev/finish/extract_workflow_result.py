"""Save a finished workflow's result object from its task output file and print a short summary (run as a file).

Usage (project root): python scripts/dev/finish/extract_workflow_result.py <task-output-file> <out.json>
"""
import json
import sys


def short(v, n=300):
    return json.dumps(v, ensure_ascii=False)[:n]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    res = data.get("result", data)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print("saved", sys.argv[2])
    for line in data.get("logs", []):
        print("log:", line)
    print("status:", res.get("status"), "| unresolved_must_fix:", res.get("unresolved_must_fix"))
    for key in ("reviews", "fixes", "rounds"):
        if key in res:
            print(f"{key}:", short(res[key], 600))
    fc = res.get("frame_contract")
    if fc:
        print(f"frame_contract: {len(fc.get('css_variables', []))} variables, {len(fc.get('classes', []))} classes, {len(fc.get('rules', []))} rules")
        print("  classes:", ", ".join(c.get("name", "?") for c in fc.get("classes", [])))
    if "demo_impact" in res:
        print("demo_impact:", len(res["demo_impact"]))
        for d in res["demo_impact"]:
            print("  -", short(d, 400))
    if "frame_requests" in res:
        print("frame_requests:", len(res["frame_requests"]))
        for d in res["frame_requests"]:
            print("  -", short(d, 300))
    lanes = res.get("lanes")
    if isinstance(lanes, dict):
        for key, lane in lanes.items():
            print(f"lane {key}: status={lane.get('status')} r1={short(lane.get('review_r1'), 220)} "
                  f"r2={short(lane.get('review_r2'), 120)} unresolved={lane.get('unresolved_must_fix')} "
                  f"files={len(lane.get('files_written') or [])} open_issues={len(lane.get('open_issues') or [])}")
            for s in lane.get("final_should_fix") or []:
                print("    should_fix:", s.get("file"), "-", (s.get("problem") or "")[:160])
    fin = res.get("final")
    if isinstance(fin, dict):
        print("final: go", fin.get("go"), "| must_fix", len(fin.get("must_fix", [])), "| should_fix", len(fin.get("should_fix", [])),
              "| view_api_equal", fin.get("view_api_equal"), "| scroll_width_400", fin.get("scroll_width_400"))
        print("  pytest:", fin.get("pytest_summary"))
        print("  web_design_guidelines:", str(fin.get("web_design_guidelines"))[:300])
        for s in fin.get("should_fix", []):
            print("  should_fix:", s.get("file"), "-", (s.get("problem") or "")[:200])
    live = res.get("live")
    if isinstance(live, dict):
        checks = live.get("checks") or []
        not_pass = [f"{c.get('stage')} {(c.get('check') or '')[:70]} -> {c.get('result')}" for c in checks if c.get("result") != "pass"]
        print(f"live: {len(checks)} checks; not pass: {not_pass}")
        for c in checks:
            print(f"  [{c.get('result')}] {c.get('stage')} {(c.get('check') or '')[:90]} | {(c.get('output_excerpt') or '')[:220]}")
        for k in ("runs_used", "act_drafts", "gpu_freed", "app_pid_stopped", "api_ps_after", "gpu_mib_after", "scores_sha_after",
                  "items_restored", "data_files_match", "live_snapshot", "driver_log", "code_issues", "blocked"):
            print(f"  live.{k}:", short(live.get(k), 500))
        print("  live.notes:", (live.get("notes") or "")[:1500])
    critics = res.get("critics")
    if isinstance(critics, dict):
        for k, v in critics.items():
            print(f"critic {k}: go={v.get('go')} must_fix={len(v.get('must_fix') or [])} should_fix={len(v.get('should_fix') or [])}")
            for m in v.get("must_fix") or []:
                print("   MUST", m.get("file"), "-", (m.get("problem") or "")[:220])
    fix = res.get("fix")
    if isinstance(fix, dict) and "pytest_summary" in fix:
        print(f"fix: applied {len(fix.get('applied') or [])}, skipped {len(fix.get('skipped') or [])}, "
              f"unresolved {fix.get('unresolved_must_fix')}, demo_impact {len(fix.get('demo_impact') or [])}")
        print("  fix.pytest:", fix.get("pytest_summary"))
        print("  fix.boot_check:", (fix.get("boot_check") or "")[:700])
        print("  fix.files_written:", short(fix.get("files_written"), 800))
        for s in fix.get("skipped") or []:
            print("  skipped:", s[:220])
    if isinstance(res.get("restyle"), dict):
        print("restyle open_issues:", short(res["restyle"].get("open_issues"), 800))
    return 0


if __name__ == "__main__":
    sys.exit(main())
