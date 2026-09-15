"""P5 Live helper for stage 7.7 (docs/PLAN_FINISH.md P5 step 4; docs/PLAN_UNIFIED.md section 5 stage 7): run Items
once through the UI endpoints with gradio_client, against the demo app that scripts/demo_prep.ps1 started.

Usage (project root, PYTHONUTF8=1; run as a file, never via `python -`):
  python scripts/dev/finish/items_run_ui.py [--port 7861] [--condition interview]

Calls /items_run (the Items "Run twin" button: api_name items_run, gpu queue) with the condition, then
/items_score (the "Score (no model)" button). Prints, under "=== label ===" headers: start time, elapsed time and
the returned note of each call; the score rows (count and a sample) and the decision line; the SHA-256 of
data/items/twin_answers.json and data/items/scores.json before, after the run and after the score; and the
data/telemetry.jsonl and data/audit.jsonl lines appended during each call, so the evidence shows whether the run
called models or reused cached cells.
Both calls REWRITE the two items files. This script does not restore them: scripts/dev/finish/live_p5.ps1 backs
them up to scripts/dev/finish/items_backup/ first and restores them afterwards.
Exit 0 when both calls returned without an exception, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from gradio_client import Client

ROOT = Path(__file__).resolve().parents[3]
ITEMS_DIR = ROOT / "data" / "items"
ITEM_FILES = ("twin_answers.json", "scores.json")
TELEMETRY = ROOT / "data" / "telemetry.jsonl"
AUDIT = ROOT / "data" / "audit.jsonl"


def show(label, value) -> None:
    print(f"=== {label} ===")
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=1, default=str))
    else:
        print(value)
    sys.stdout.flush()


def sha256(path: Path) -> str:
    if not path.exists():
        return "missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def item_shas() -> dict:
    return {name: sha256(ITEMS_DIR / name) for name in ITEM_FILES}


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def lines_since(path: Path, start: int) -> list:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < start or not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"unparsed": line.strip()[:300]})
    return out


def hhmmss(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S") if isinstance(ts, (int, float)) else str(ts)


def compact(r: dict) -> dict:
    return {"time": hhmmss(r.get("ts")), "tab": r.get("tab"), "model": r.get("model"), "runtime": r.get("runtime"),
            "load_ms": round(r.get("load_ms") or 0, 1), "wall_ms": round(r.get("wall_ms") or 0),
            "ok": r.get("ok"), "error": (r.get("error") or "")[:200]}


def telemetry_summary(rows: list) -> dict:
    return {"rows": len(rows),
            "per_tab_model": dict(Counter(f"{r.get('tab')} | {r.get('model')}" for r in rows)),
            "rows_with_tab_items": sum(1 for r in rows if r.get("tab") == "items"),
            "load_rows_over_1000_ms": [compact(r) for r in rows if (r.get("load_ms") or 0) > 1000]}


def table_summary(value) -> dict:
    if isinstance(value, dict):
        headers, data = value.get("headers"), value.get("data") or []
    elif isinstance(value, list):
        headers, data = None, value
    else:
        return {"type": type(value).__name__, "repr": repr(value)[:500]}
    return {"headers": headers, "rows": len(data), "sample": data[:4]}


def timed_call(client: Client, label: str, *args, api_name: str):
    tel0, aud0 = line_count(TELEMETRY), line_count(AUDIT)
    show(f"{label} started", datetime.now().isoformat(timespec="seconds"))
    t0 = time.perf_counter()
    err = None
    try:
        result = client.predict(*args, api_name=api_name)
    except Exception as e:  # noqa: BLE001
        result, err = None, f"{type(e).__name__}: {e}"
    show(f"{label} elapsed_s", round(time.perf_counter() - t0, 1))
    show(f"{label} ended", datetime.now().isoformat(timespec="seconds"))
    if err:
        show(f"{label} EXCEPTION", err)
    tel = lines_since(TELEMETRY, tel0)
    aud = lines_since(AUDIT, aud0)
    return result, err, tel, aud


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7861)
    ap.add_argument("--condition", default="interview", choices=("demographic", "persona", "interview", "all"))
    a = ap.parse_args()
    url = f"http://127.0.0.1:{a.port}"
    show("app", url)
    show("sha256 before", item_shas())
    client = Client(url, verbose=False)
    ok = True

    result, err, tel, aud = timed_call(client, "items_run", a.condition, api_name="/items_run")
    if err:
        ok = False
    else:
        note, rows = result
        show("items_run note", note)
        show("items_run score rows", table_summary(rows))
    show("sha256 after items_run", item_shas())
    show("telemetry during items_run", telemetry_summary(tel))
    show("telemetry rows with tab=items during items_run (first 40)", [compact(r) for r in tel if r.get("tab") == "items"][:40])
    show("audit lines during items_run", aud)

    result, err, tel, aud = timed_call(client, "items_score", api_name="/items_score")
    if err:
        ok = False
    else:
        rows, decision = result
        show("items_score rows", table_summary(rows))
        show("items_score decision", decision)
    show("sha256 after items_score", item_shas())
    show("telemetry during items_score", telemetry_summary(tel))
    show("audit lines during items_score", aud)
    show("result", "both calls returned" if ok else "an exception was raised (see EXCEPTION above)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
