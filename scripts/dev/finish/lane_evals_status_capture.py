"""P4 evals_status lane helper (read-only, no GPU, standard library only; run as a file).

Waits until the app that scripts/dev/finish/ui_check.ps1 booted answers on a UI port, then, through headless Chrome's
DevTools protocol (the WebSocket client in cdp_shot.py), opens each tab through the ?tab= deep link at 1440 px,
grows the emulated viewport to the page height and saves the whole tab as 1000 px high PNG segments
(<theme>_1440_<tab>_p<N>.png). With --dump it also saves document.documentElement.outerHTML for the light theme
(<tab>.html), because Gradio mounts only the selected tab, so the P3 dumps hold no Eval or Status markup.
It never calls a model and refuses the demo ports 7861-7870. It does not boot or stop the app.

Usage (project root, while ui_check.ps1 runs on the same port):
  python scripts/dev/finish/lane_evals_status_capture.py --port 7875 --out-dir scripts/dev/shots/lane_evals_status/full
         [--tabs eval,status] [--themes light,dark] [--dump] [--wait 8] [--boot-timeout 240]
"""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp_shot import WebSocket, find_chrome, free_port, get_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
WIDTH = 1440
SEGMENT = 1000
MAX_HEIGHT = 9000

PROBE_JS = r"""
(() => {
  const q = (s) => document.querySelector(s);
  const cs = (el, p) => el ? getComputedStyle(el).getPropertyValue(p) : null;
  const sel = q('button[role="tab"][aria-selected="true"]');
  const out = {scrollHeight: document.documentElement.scrollHeight, innerWidth: window.innerWidth,
               scrollWidth: document.documentElement.scrollWidth,
               selectedTab: sel ? sel.textContent.trim() : null,
               dark: document.body ? document.body.classList.contains('dark') : null, probes: {}};
  const STYLE = [
    ['#eval-use-claude', ['border-top-width', 'padding-top', 'background-color']],
    ['#eval-options .form', ['border-top-width', 'background-color', 'box-shadow']],
    ['#eval-live-controls input', ['border-top-width']],
    ['#status-md td code', ['white-space', 'border-top-width']],
    ['#eval-summary [role="gridcell"]', ['font-family', 'font-variant-numeric', 'font-size', 'font-weight']],
    ['#eval-summary [role="columnheader"]', ['font-family', 'color', 'background-color']],
    ['#eval-probes table', ['padding-top', 'padding-left', 'border-spacing', 'border-top-width', 'display']],
    ['#eval-probes tbody tr:last-child > td', ['border-bottom-width']],
    ['#eval-probes thead', ['border-top-width', 'border-bottom-width']],
    ['#eval-probes tbody', ['border-top-width', 'border-bottom-width']],
    ['#eval-refresh', ['flex-basis', 'white-space', 'border-top-color', 'color', 'background-color']],
    ['#eval-voice-rerun', ['flex-basis', 'white-space', 'border-top-color', 'color', 'background-color', 'margin-left']],
    ['#eval-live-run', ['flex-basis', 'white-space', 'border-top-color', 'color']],
    ['#status-md', ['border-top-width', 'padding-top', 'background-color']],
    ['#status-md [data-testid="markdown"]', ['border-top-width', 'padding-top', 'min-height', 'background-color']],
    ['#status-md li > table', ['margin-left', 'border-collapse', 'display']],
    ['#status-md tbody tr', ['border-bottom-width', 'background-color']],
    ['#status-md tbody td:nth-child(5)', ['display', 'background-color', 'border-top-width', 'font-weight']],
    ['#status-audit-tail [role="gridcell"]', ['font-family', 'font-size']],
    ['#status-telemetry [role="columnheader"]', ['font-family', 'font-size']],
    ['#status-free-gpu', ['background-color', 'color', 'flex-basis', 'white-space']],
    ['#status-warm-tab', ['border-top-width', 'padding-top', 'background-color']],
    ['#status-rebuild-digest', ['border-top-color', 'color', 'flex-basis', 'white-space']],
  ];
  for (const [s, props] of STYLE) {
    const el = q(s);
    if (!el) { out.probes[s] = null; continue; }
    const r = el.getBoundingClientRect();
    const v = {w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top)};
    for (const p of props) v[p] = cs(el, p);
    out.probes[s] = v;
  }
  const off = [];
  for (const el of document.querySelectorAll('#twin-tabs *')) {
    const r = el.getBoundingClientRect();
    if (r.width && r.height && r.right > window.innerWidth + 1) {
      off.push({tag: el.tagName.toLowerCase(), id: el.id || '', right: Math.round(r.right)});
      if (off.length >= 10) break;
    }
  }
  out.overflowing = off;
  return out;
})()
"""


def wait_for_app(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1.0)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--tabs", default="eval,status")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--wait", type=float, default=8.0)
    ap.add_argument("--boot-timeout", type=float, default=240.0)
    a = ap.parse_args()
    if 7861 <= a.port <= 7870:
        print("refusing ports 7861-7870 (the demo app); use a UI port 7871-7879")
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    tabs = [t.strip() for t in a.tabs.split(",") if t.strip()]
    themes = [t.strip() for t in a.themes.split(",") if t.strip()]
    if not wait_for_app(a.port, a.boot_timeout):
        print(f"FAIL no app answered on port {a.port} within {a.boot_timeout:.0f} s")
        return 2
    print(f"app answered on port {a.port}")
    dport = free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_lane_es_{a.port}_")
    proc = subprocess.Popen([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}",
                             f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page, ok, report = None, True, []
    try:
        target = None
        for _ in range(100):
            try:
                target = next((t for t in get_json(f"http://127.0.0.1:{dport}/json/list") if t.get("type") == "page"), None)
            except OSError:
                target = None
            if target:
                break
            time.sleep(0.2)
        if not target:
            print("FAIL no DevTools page target")
            return 2
        page = WebSocket(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        for theme in themes:
            for tab in tabs:
                page.call("Emulation.setDeviceMetricsOverride",
                          {"width": WIDTH, "height": SEGMENT, "deviceScaleFactor": 1, "mobile": False})
                url = f"http://127.0.0.1:{a.port}/?tab={tab}&__theme={theme}&nomotion=1"
                page.events.clear()
                page.call("Page.navigate", {"url": url})
                page.wait_event("Page.loadEventFired", timeout=45)
                time.sleep(a.wait)
                first = page.call("Runtime.evaluate", {"expression": PROBE_JS, "returnByValue": True})["result"]["value"]
                height = min(int(first.get("scrollHeight") or SEGMENT), MAX_HEIGHT)
                page.call("Emulation.setDeviceMetricsOverride",
                          {"width": WIDTH, "height": height, "deviceScaleFactor": 1, "mobile": False})
                time.sleep(2.0)
                info = page.call("Runtime.evaluate", {"expression": PROBE_JS, "returnByValue": True})["result"]["value"]
                height = min(int(info.get("scrollHeight") or height), MAX_HEIGHT)
                parts = []
                for n, y in enumerate(range(0, height, SEGMENT), start=1):
                    h = min(SEGMENT, height - y)
                    shot = page.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                                                                "clip": {"x": 0, "y": y, "width": WIDTH, "height": h,
                                                                         "scale": 1}})
                    png = out_dir / f"{theme}_{WIDTH}_{tab}_p{n}.png"
                    png.write_bytes(base64.b64decode(shot["data"]))
                    parts.append(png.name)
                if a.dump and theme == "light":
                    html = page.call("Runtime.evaluate", {"expression": "document.documentElement.outerHTML",
                                                          "returnByValue": True})["result"]["value"]
                    (out_dir / f"{tab}.html").write_text(html, encoding="utf-8")
                row = {"theme": theme, "tab": tab, "height": height, "parts": parts, **info}
                report.append(row)
                print(f"{theme} {tab}: selected={info.get('selectedTab')!r} dark={info.get('dark')} height={height} "
                      f"scrollWidth={info.get('scrollWidth')} parts={len(parts)} overflowing={len(info.get('overflowing') or [])}")
                if info.get("selectedTab") is None:
                    ok = False
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {type(e).__name__}: {e}")
        ok = False
    finally:
        if page is not None:
            page.close()
        try:
            browser = WebSocket(get_json(f"http://127.0.0.1:{dport}/json/version")["webSocketDebuggerUrl"], timeout=5)
            browser.call("Browser.close", timeout=5)
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    (out_dir / "capture.json").write_text(json.dumps({"port": a.port, "ok": ok, "results": report}, indent=1),
                                          encoding="utf-8")
    return 0 if ok and len(report) == len(tabs) * len(themes) else 1


if __name__ == "__main__":
    sys.exit(main())
