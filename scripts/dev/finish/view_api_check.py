"""PLAN_FINISH DEMO CONTRACT check for a running app (view_api only; calls no model).

1. The api_names equal scripts/dev/view_api_baseline.json plus twin.ui.frame.NEW_API_NAMES (the six new names).
2. Every baseline endpoint keeps its parameter names; the four CONDITION_ENDPOINTS carry exactly one trailing
   `condition` (the same rule as scripts/dev/evidence/stage2_view_api_check.py, which this never overwrites).
3. With --snapshot: every endpoint's parameters (name, component, default) and returns (count, component) equal
   the snapshot taken from the pre-restyle app. Label changes are reported as warnings.

Usage (from the project root):
  python scripts/dev/finish/view_api_check.py <port> <out.json> [--snapshot PATH] [--save-snapshot PATH]
Exit 0 when every check passes, 1 when any fails, 2 on a usage or connection error.
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _arg(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def _params(ep):
    return [(p.get("parameter_name"), p.get("component"), json.dumps(p.get("parameter_default"), sort_keys=True))
            for p in ep.get("parameters", [])]


def _returns(ep):
    return [r.get("component") for r in ep.get("returns", [])]


def _labels(ep):
    return ([p.get("label") for p in ep.get("parameters", [])], [r.get("label") for r in ep.get("returns", [])])


def main():
    positional = [a for i, a in enumerate(sys.argv[1:], 1)
                  if not a.startswith("--") and sys.argv[i - 1] not in ("--snapshot", "--save-snapshot")]
    if len(positional) < 2:
        print(__doc__)
        return 2
    port = int(positional[0])
    out_path = os.path.join(ROOT, positional[1]) if not os.path.isabs(positional[1]) else positional[1]
    snap_path = _arg("--snapshot")
    save_path = _arg("--save-snapshot")

    from gradio_client import Client
    from twin.ui import frame

    try:
        client = Client(f"http://127.0.0.1:{port}", verbose=False)
        info = client.view_api(return_format="dict", print_info=False)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL could not read view_api on port {port}: {type(e).__name__}: {e}")
        return 2
    live = info.get("named_endpoints", {})
    names = sorted(live.keys())

    base = json.load(open(os.path.join(ROOT, "scripts", "dev", "view_api_baseline.json"), encoding="utf-8"))
    baseline = sorted(base["api_names"])
    expected = sorted(set(baseline) | {f"/{n}" for n in frame.NEW_API_NAMES})
    errors, warnings = [], []

    names_equal = names == expected
    print("api_names == baseline + six new names:", "EQUAL" if names_equal else "DIFF")
    if not names_equal:
        errors.append({"check": "names", "missing": sorted(set(expected) - set(names)),
                       "extra": sorted(set(names) - set(expected))})
        print("  missing:", sorted(set(expected) - set(names)), " extra:", sorted(set(names) - set(expected)))

    for name in baseline:
        b = [p.get("parameter_name") for p in base["endpoints"].get(name, {}).get("parameters", [])]
        l = [p.get("parameter_name") for p in live.get(name, {}).get("parameters", [])]
        want = b + ["condition"] if name.lstrip("/") in frame.CONDITION_ENDPOINTS else b
        if l != want:
            errors.append({"check": "baseline_params", "endpoint": name, "expected": want, "live": l})
    print("baseline parameter names (condition endpoints + trailing condition):",
          "OK" if not any(e["check"] == "baseline_params" for e in errors) else "DIFF")

    snapshot_result = None
    if snap_path:
        sp = snap_path if os.path.isabs(snap_path) else os.path.join(ROOT, snap_path)
        snap = json.load(open(sp, encoding="utf-8")).get("named_endpoints", {})
        diffs = []
        for name, ep in sorted(snap.items()):
            if name not in live:
                diffs.append({"endpoint": name, "problem": "missing in live app"})
                continue
            if _params(ep) != _params(live[name]):
                diffs.append({"endpoint": name, "problem": "parameters differ", "snapshot": _params(ep),
                              "live": _params(live[name])})
            if _returns(ep) != _returns(live[name]):
                diffs.append({"endpoint": name, "problem": "returns differ", "snapshot": _returns(ep),
                              "live": _returns(live[name])})
            if _labels(ep) != _labels(live[name]):
                warnings.append({"endpoint": name, "problem": "labels differ", "snapshot": _labels(ep),
                                 "live": _labels(live[name])})
        for name in sorted(set(live) - set(snap)):
            diffs.append({"endpoint": name, "problem": "not in snapshot"})
        errors.extend({"check": "snapshot", **d} for d in diffs)
        snapshot_result = {"path": snap_path, "diffs": diffs}
        print(f"parameters and returns == snapshot {snap_path}:", "EQUAL" if not diffs else f"DIFF ({len(diffs)})")
        for d in diffs:
            print("  ", json.dumps(d)[:400])
        for w in warnings:
            print("  warning:", json.dumps(w)[:400])

    if save_path:
        sp = save_path if os.path.isabs(save_path) else os.path.join(ROOT, save_path)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=1)
        print("saved snapshot", save_path)

    report = {"port": port, "api_names": names, "expected": expected, "names_equal": names_equal,
              "errors": errors, "warnings": warnings, "snapshot": snapshot_result, "ok": not errors}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("view_api check:", "PASS" if not errors else f"FAIL ({len(errors)} errors)", "->", positional[1])
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
