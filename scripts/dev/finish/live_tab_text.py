"""P5 Live helper for stage 7.5 and 7.6 (docs/PLAN_FINISH.md P5, docs/PLAN_UNIFIED.md section 5 stage 7): a
REAL-TIME headless capture of one tab of the demo app, with the gpu note and the status strip read as DOM text.

Why: scripts/screenshot_tabs.ps1 uses --virtual-time-budget, which captures the status strip at its boot-time value
(the 5 s gr.Timer does not tick inside the budget) and model tabs with the pre-warm still pending
(docs/EVIDENCE2.md "Notes for later workflows"; docs/PLAN_FINISH.md "Traps"). This helper waits in real time and
records what the page actually shows, so the strip can be compared with the /api/ps and lms ps bodies.

Scope: scripts/dev/finish/cdp_shot.py refuses ports 7861-7870 on purpose (UI agents). This helper belongs to the P5
Live agent only: it accepts only the port recorded in scripts/dev/demo/app.port (the app scripts/demo_prep.ps1
started) and only two tabs: act (opening it fires hermes3's pre-warm, which 7.5 checks) and status (its select hook
only reports; it loads nothing). It calls no endpoint itself.

Usage (project root, PYTHONUTF8=1; run as a file, never via `python -`):
  python scripts/dev/finish/live_tab_text.py --tab act|status --out-dir DIR --json FILE [--wait 90]
         [--theme light] [--width 1440] [--height 1000]
act:    polls the gpu note once a second until it reads "Pre-warmed", "Pre-warm of", "No model to pre-warm" or
        "Pre-warm skipped" (or --wait runs out), then waits 6 s more so the strip ticks, then captures.
status: samples for --wait seconds (use at least 11 s: two timer ticks), then captures.
Writes <out-dir>/<theme>_<width>_<tab>.png and the JSON (texts, note and strip changes over time, timings); refuses
to overwrite either. Exit 0 when the PNG and the texts were captured, 1 otherwise, 2 on a setup error.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp_shot  # noqa: E402  (same folder: WebSocket, find_chrome, free_port, get_json, ROOT)

ROOT = cdp_shot.ROOT
PORT_FILE = ROOT / "scripts" / "dev" / "demo" / "app.port"
TABS = ("act", "status")
NOTE_DONE = re.compile(r"Pre-warmed|Pre-warm of|No model to pre-warm|Pre-warm skipped")
TEXT_JS = r"""
(() => {
  const txt = (sel) => { const el = document.querySelector(sel); return el ? el.innerText : null; };
  const sel = document.querySelector('button[role="tab"][aria-selected="true"]');
  return {gpu_note: txt('#gpu-note'),
          status_strip: txt('#status-strip') ?? txt('[id^="status-strip"]'),
          selectedTab: sel ? sel.textContent.trim() : null,
          dark: document.body ? document.body.classList.contains('dark') : null,
          innerWidth: window.innerWidth, title: document.title};
})()
"""


def evaluate(page, expr: str) -> dict:
    return page.call("Runtime.evaluate", {"expression": expr, "returnByValue": True}).get("result", {}).get("value") or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tab", required=True, choices=TABS)
    ap.add_argument("--port", type=int, help="must equal scripts/dev/demo/app.port (default: that port)")
    ap.add_argument("--theme", choices=("light", "dark"), default="light")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--wait", type=float, default=90.0)
    a = ap.parse_args()

    try:
        recorded = int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print(f"FAIL {PORT_FILE} is missing or unreadable: start the app with scripts\\demo_prep.ps1 first")
        return 2
    port = a.port or recorded
    if port != recorded:
        print(f"refusing port {port}: this helper drives only the app recorded in scripts/dev/demo/app.port ({recorded})")
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{a.theme}_{a.width}_{a.tab}.png"
    jp = Path(a.json) if Path(a.json).is_absolute() else ROOT / a.json
    for p in (png, jp):
        if p.exists():
            print(f"refusing to overwrite {p}")
            return 2

    dport = cdp_shot.free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_live_{port}_")
    proc = subprocess.Popen([cdp_shot.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             "--no-first-run", "--no-default-browser-check", f"--remote-debugging-port={dport}",
                             f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page = None
    row: dict = {"tab": a.tab, "port": port, "theme": a.theme, "viewport": {"width": a.width, "height": a.height},
                 "wait_s": a.wait}
    ok = False
    try:
        target = None
        for _ in range(100):
            try:
                target = next((t for t in cdp_shot.get_json(f"http://127.0.0.1:{dport}/json/list")
                               if t.get("type") == "page"), None)
            except OSError:
                target = None
            if target:
                break
            time.sleep(0.2)
        if not target:
            print("FAIL no DevTools page target")
            return 2
        page = cdp_shot.WebSocket(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Emulation.setDeviceMetricsOverride",
                  {"width": a.width, "height": a.height, "deviceScaleFactor": 1, "mobile": False})
        url = f"http://127.0.0.1:{port}/?tab={a.tab}&__theme={a.theme}&nomotion=1"
        row["url"] = url
        row["navigated_at"] = datetime.now().isoformat(timespec="seconds")
        t0 = time.time()
        page.events.clear()
        page.call("Page.navigate", {"url": url})
        row["load_event"] = page.wait_event("Page.loadEventFired", timeout=45) is not None
        row["load_s"] = round(time.time() - t0, 1)
        note_changes: list = []
        strip_changes: list = []

        def sample() -> dict:
            v = evaluate(page, TEXT_JS)
            now = round(time.time() - t0, 1)
            note = v.get("gpu_note")
            strip = v.get("status_strip")
            if not note_changes or note_changes[-1][1] != note:
                note_changes.append([now, note])
            if not strip_changes or strip_changes[-1][1] != strip:
                strip_changes.append([now, strip])
            return v

        deadline = t0 + a.wait
        if a.tab == "act":
            row["note_done_s"] = None
            while time.time() < deadline:
                v = sample()
                if NOTE_DONE.search(v.get("gpu_note") or ""):
                    row["note_done_s"] = round(time.time() - t0, 1)
                    break
                time.sleep(1.0)
            settle = time.time() + 6.0
            while time.time() < settle:
                sample()
                time.sleep(1.0)
        else:
            while time.time() < deadline:
                sample()
                time.sleep(1.0)
        value = sample()
        row["captured_at"] = datetime.now().isoformat(timespec="seconds")
        row["captured_s"] = round(time.time() - t0, 1)
        shot = page.call("Page.captureScreenshot", {"format": "png"})
        png.write_bytes(base64.b64decode(shot["data"]))
        row.update({"png": str(png.relative_to(ROOT)) if str(png).startswith(str(ROOT)) else str(png),
                    "png_bytes": png.stat().st_size, "selectedTab": value.get("selectedTab"),
                    "dark": value.get("dark"), "innerWidth": value.get("innerWidth"),
                    "gpu_note": value.get("gpu_note"), "status_strip": value.get("status_strip"),
                    "note_changes": note_changes, "strip_changes": strip_changes})
        ok = value.get("gpu_note") is not None and png.stat().st_size > 5000
        print(f"{a.tab}: load_event={row['load_event']} load {row['load_s']} s, captured at {row['captured_at']} "
              f"(+{row['captured_s']} s), selected={row['selectedTab']!r}, png {row['png']} ({row['png_bytes']} bytes)")
        if a.tab == "act":
            print(f"note reached a final state after: {row.get('note_done_s')} s")
        print("gpu_note changes:")
        for t, n in note_changes:
            print(f"  +{t} s: {n!r}")
        print("status_strip changes:")
        for t, s in strip_changes:
            print(f"  +{t} s: {s!r}")
        print(f"final gpu_note: {row['gpu_note']!r}")
        print(f"final status_strip: {row['status_strip']!r}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {type(e).__name__}: {e}")
        row["error"] = f"{type(e).__name__}: {e}"
        ok = False
    finally:
        if page is not None:
            page.close()
        try:
            browser = cdp_shot.WebSocket(cdp_shot.get_json(f"http://127.0.0.1:{dport}/json/version")["webSocketDebuggerUrl"],
                                         timeout=5)
            browser.call("Browser.close", timeout=5)
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    row["ok"] = ok
    jp.write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
