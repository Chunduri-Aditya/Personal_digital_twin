"""P4 decide lane helper (read-only, no GPU, standard library only; run as a file).

Waits until an app answers on a UI port, then through headless Chrome's DevTools protocol (the WebSocket client in
cdp_shot.py) opens ?tab=decide in each theme and:
- at 1440 px grows the viewport to the page height and saves 1000 px PNG segments <state>_<theme>_1440_decide_p<N>.png;
- at a true 400 px saves the Decide result area (verdict card to quote card) as <state>_<theme>_400_decide.png and
  measures document scrollWidth;
- probes computed styles of the Decide parts and whether the meter overlaps the verdict figure (<state>_probe.json);
- with --dump saves the light 1440 DOM as <state>_decide.html.
It never calls a model or clicks anything, refuses ports 7861-7870, and does not boot or stop the app.

Usage (project root): python scripts/dev/finish/lane_decide_capture.py --port 7873 --state verdict
                      --out-dir scripts/dev/shots/lane_decide/states [--themes light,dark] [--dump] [--wait 8]
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
SEGMENT = 1000
MAX_HEIGHT = 9000

PROBE_JS = r"""
(() => {
  const q = (s) => document.querySelector(s);
  const box = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height)}; };
  const style = (el, props) => { const c = getComputedStyle(el); const o = {}; for (const p of props) o[p] = c.getPropertyValue(p); return o; };
  const sel = q('button[role="tab"][aria-selected="true"]');
  const out = {scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
               scrollHeight: document.documentElement.scrollHeight, selectedTab: sel ? sel.textContent.trim() : null,
               dark: document.body ? document.body.classList.contains('dark') : null, probes: {}};
  const probes = {
    panel_question: ['#decide-question', ['background-color', 'border-top-color', 'padding-top']],
    verdict: ['#decide-verdict', ['display', 'background-color', 'border-top-style', 'border-top-color', 'box-shadow']],
    meter_block: ['#decide-confidence', ['display', 'width', 'height']],
    meter_fill: ['#decide-confidence .fill', ['width', 'background-color']],
    meter_value: ['#decide-confidence .value', ['color', 'font-size']],
    head_p: ['#decide-result p:first-of-type', ['padding-right', 'color', 'background-color', 'font-size']],
    head_strong: ['#decide-result p:first-of-type > strong', ['font-size', 'color', 'font-weight']],
    label: ['#decide-result p:has(+ ul)', ['font-size', 'color']],
    reason_li: ['#decide-result ul:nth-of-type(1) > li', ['font-size', 'list-style-type']],
    chip: ['#decide-result ul:nth-of-type(2) > li', ['border-top-style', 'background-color', 'font-size']],
    annotation: ['#decide-result p:not(:first-of-type):not(:has(+ ul)):not(:has(> br)):has(> strong)', ['border-left-width', 'border-left-color']],
    uncited: ['#decide-result p:not(:first-of-type):not(:last-of-type):has(> em:only-child)', ['color', 'font-size']],
    footer: ['#decide-result p:last-of-type:not(:first-of-type):has(> em:only-child)', ['border-top-style', 'color', 'font-size']],
    error_p: ['#decide-result p:first-of-type:not(:has(> br)):has(> strong)', ['background-color']],
    error_strong: ['#decide-result p:first-of-type:not(:has(> br)):has(> strong) > strong', ['color']],
    raw: ['#decide-raw', ['background-color']],
    say: ['#decide-say-card', ['font-family', 'border-left-width', 'border-left-color', 'box-shadow', 'background-color']],
    say_textarea: ['#decide-say textarea', ['font-family', 'color', 'background-color', 'border-top-color', '-webkit-text-fill-color']],
    label_margin: ['#decide-result p:not(:first-of-type):has(+ ul)', ['margin-top', 'margin-bottom']],
    annotation_margin: ['#decide-result p:not(:first-of-type):not(:has(+ ul)):not(:has(> br)):has(> strong)', ['margin-top']],
    situation_block: ['#decide-situation', ['padding-left', 'border-radius']],
    b1: ['#decide-b1', ['background-color', 'color']],
    b2: ['#decide-b2', ['background-color', 'color', 'border-top-color']],
    say_btn: ['#decide-say-btn', ['background-color', 'border-top-color']],
  };
  for (const [k, [s, props]] of Object.entries(probes)) {
    const el = q(s);
    out.probes[k] = el ? {...style(el, props), box: box(el), text: (el.textContent || '').trim().slice(0, 60)} : null;
  }
  const strong = q('#decide-result p:first-of-type > strong');
  const meter = q('#decide-confidence .confidence-meter');
  out.meter_present = !!meter;
  if (strong && meter) {
    const a = strong.getBoundingClientRect(), b = meter.getBoundingClientRect();
    out.meter_overlaps_head = !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
  }
  const off = [];
  for (const el of document.querySelectorAll('#tab-decide *')) {
    const r = el.getBoundingClientRect();
    if (r.width && r.height && r.right > window.innerWidth + 1) {
      off.push({tag: el.tagName.toLowerCase(), id: el.id || '', right: Math.round(r.right)});
      if (off.length >= 10) break;
    }
  }
  out.overflowing_in_tab = off;
  const v = q('#decide-question'), s = q('#decide-say-card') || q('#decide-say');
  out.region = (v && s) ? {top: Math.max(0, Math.round(v.getBoundingClientRect().top + window.scrollY) - 16),
                            bottom: Math.round(s.getBoundingClientRect().bottom + window.scrollY) + 16} : null;
  return out;
})()
"""


DIAG_JS = r"""
(() => {
  const res = {holder: null, children: [], rules: {}};
  const first = document.querySelector('#decide-result p');
  const holder = first ? first.parentElement : null;
  if (holder) {
    const hs = getComputedStyle(holder);
    res.holder = {tag: holder.tagName, cls: String(holder.className).slice(0, 60), display: hs.display, gap: hs.gap};
    for (const el of holder.children) {
      const c = getComputedStyle(el);
      res.children.push({tag: el.tagName, text: el.textContent.trim().slice(0, 30), mt: c.marginTop, mb: c.marginBottom,
                         display: c.display});
    }
  }
  const targets = {label: '#decide-result p:has(+ ul)',
                   annotation: '#decide-result p:not(:first-of-type):not(:has(+ ul)):not(:has(> br)):has(> strong)',
                   say_block: '#decide-say', say_card: '#decide-say-card', panel: '#decide-question'};
  for (const [k, s] of Object.entries(targets)) {
    const el = document.querySelector(s);
    if (!el) { res.rules[k] = null; continue; }
    const c = getComputedStyle(el);
    const hits = [];
    const walk = (list, media) => {
      for (const r of list) {
        if (r.cssRules && !r.selectorText) { walk(r.cssRules, r.conditionText || media); continue; }
        if (!r.selectorText) continue;
        let m = false;
        try { m = el.matches(r.selectorText); } catch (e) { m = false; }
        if (!m) continue;
        const props = [];
        for (const p of r.style) {
          if (/^(margin|padding|border-left|border-width|border-style|box-shadow|background|--block)/.test(p)) {
            props.push(p + ': ' + r.style.getPropertyValue(p) + (r.style.getPropertyPriority(p) ? ' !important' : ''));
          }
        }
        if (props.length) hits.push({sel: r.selectorText.slice(0, 200), media: media || '', props});
      }
    };
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch (e) { continue; }
      walk(rules, '');
    }
    res.rules[k] = {computed: {mt: c.marginTop, mb: c.marginBottom, blw: c.borderLeftWidth, shadow: c.boxShadow},
                    hits};
  }
  return res;
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


def evaluate(page: WebSocket, expression: str):
    return page.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})["result"].get("value")


def open_tab(page: WebSocket, port: int, theme: str, width: int, height: int, wait: float) -> dict:
    page.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                     "mobile": False})
    page.events.clear()
    page.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/?tab=decide&__theme={theme}&nomotion=1"})
    page.wait_event("Page.loadEventFired", timeout=45)
    time.sleep(wait)
    first = evaluate(page, PROBE_JS) or {}
    full = min(int(first.get("scrollHeight") or height), MAX_HEIGHT)
    page.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": full, "deviceScaleFactor": 1,
                                                     "mobile": False})
    time.sleep(2.0)
    return evaluate(page, PROBE_JS) or {}


def shot(page: WebSocket, path: Path, width: int, y: int, h: int) -> None:
    data = page.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                                                "clip": {"x": 0, "y": y, "width": width, "height": h, "scale": 1}})
    path.write_bytes(base64.b64decode(data["data"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--wait", type=float, default=8.0)
    ap.add_argument("--boot-timeout", type=float, default=150.0)
    a = ap.parse_args()
    if 7861 <= a.port <= 7870:
        print("refusing ports 7861-7870 (the demo app); use a UI port 7871-7879")
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    themes = [t.strip() for t in a.themes.split(",") if t.strip()]
    if not wait_for_app(a.port, a.boot_timeout):
        print(f"FAIL no app answered on port {a.port} within {a.boot_timeout:.0f} s")
        return 2
    dport = free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_lane_decide_{a.port}_")
    proc = subprocess.Popen([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}",
                             f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    page, ok, report = None, True, {}
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
            info = open_tab(page, a.port, theme, 1440, SEGMENT, a.wait)
            height = min(int(info.get("scrollHeight") or SEGMENT), MAX_HEIGHT)
            parts = []
            for n, y in enumerate(range(0, height, SEGMENT), start=1):
                png = out_dir / f"{a.state}_{theme}_1440_decide_p{n}.png"
                shot(page, png, 1440, y, min(SEGMENT, height - y))
                parts.append(png.name)
            if a.dump and theme == "light":
                html = evaluate(page, "document.documentElement.outerHTML") or ""
                (out_dir / f"{a.state}_decide.html").write_text(html, encoding="utf-8")
                diag = evaluate(page, DIAG_JS) or {}
                (out_dir / f"{a.state}_diag.json").write_text(json.dumps(diag, indent=1), encoding="utf-8")
            narrow = open_tab(page, a.port, theme, 400, 900, a.wait)
            region = narrow.get("region") or {"top": 0, "bottom": 900}
            top, bottom = int(region["top"]), min(int(region["bottom"]), MAX_HEIGHT)
            png400 = out_dir / f"{a.state}_{theme}_400_decide.png"
            shot(page, png400, 400, top, max(100, bottom - top))
            report[theme] = {"1440": {**info, "parts": parts}, "400": {**narrow, "png": png400.name}}
            print(f"{a.state} {theme}: selected={info.get('selectedTab')!r} dark={info.get('dark')} height={height} "
                  f"parts={len(parts)} meter={info.get('meter_present')} overlap={info.get('meter_overlaps_head')} | "
                  f"400: scrollWidth={narrow.get('scrollWidth')} innerWidth={narrow.get('innerWidth')} "
                  f"meter={narrow.get('meter_present')} overlap={narrow.get('meter_overlaps_head')} "
                  f"overflowing_in_tab={len(narrow.get('overflowing_in_tab') or [])}")
            if info.get("selectedTab") != "Decide" or narrow.get("selectedTab") is None:
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
    (out_dir / f"{a.state}_probe.json").write_text(json.dumps({"port": a.port, "state": a.state, "ok": ok,
                                                               "themes": report}, indent=1), encoding="utf-8")
    return 0 if ok and len(report) == len(themes) else 1


if __name__ == "__main__":
    sys.exit(main())
