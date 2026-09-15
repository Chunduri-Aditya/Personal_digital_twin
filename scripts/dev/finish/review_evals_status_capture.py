"""Reviewer helper for the P4 evals_status lane (read-only, no GPU, standard library only; run as a file).

Waits until the app that scripts/dev/finish/ui_check.ps1 booted answers on a UI port, then through headless Chrome's
DevTools protocol (cdp_shot.WebSocket) opens each tab through its ?tab= deep link, grows the viewport to the page
height, saves 1000 px PNG segments (<theme>_<width>_<tab>_p<N>.png) and runs independent probes:
- text contrast of every visible text element in the tab panel against its composited background (WCAG ratio);
- light islands in dark mode (opaque backgrounds with luminance > 0.35 inside the panel);
- horizontal clipping (scrollWidth > clientWidth on overflow-hidden elements) and elements past the panel edge;
- every button's rect, variant class and colours; rects of the lane's ids;
- column alignment of the Markdown tables (th vs td left edges);
- samples of the served CSS rules for the partials, to check the frame_requests claims.
It never clicks anything, never calls a model, refuses ports 7861-7870, and does not boot or stop the app.

Usage: python scripts/dev/finish/review_evals_status_capture.py --port 7875 --out-dir <dir> [--widths 1440,400]
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
((tabId) => {
  const panel = document.getElementById('tab-' + tabId);
  const sel = document.querySelector('button[role="tab"][aria-selected="true"]');
  const dark = document.body.classList.contains('dark');
  const out = {scrollHeight: document.documentElement.scrollHeight, scrollWidth: document.documentElement.scrollWidth,
               innerWidth: window.innerWidth, selectedTab: sel ? sel.textContent.trim() : null, dark,
               panelFound: !!panel};
  if (!panel) return out;
  const parse = (s) => {
    const m = s && s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
  };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                       return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
  const bgOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 0.99) break; }
    }
    let res = (layers.length && layers[layers.length - 1].a >= 0.99) ? layers.pop()
              : (dark ? {r: 28, g: 26, b: 23, a: 1} : {r: 247, g: 246, b: 243, a: 1});
    while (layers.length) { const c = layers.pop();
      res = {r: c.r * c.a + res.r * (1 - c.a), g: c.g * c.a + res.g * (1 - c.a), b: c.b * c.a + res.b * (1 - c.a), a: 1}; }
    return res;
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0; };
  const rect = (el) => { const r = el.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height)}; };
  const snip = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 70);

  // 1. text contrast
  const low = []; let minRatio = 99, nText = 0, unknown = 0;
  for (const el of panel.querySelectorAll('*')) {
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent).join(' ');
    if (!own.trim() || !visible(el)) continue;
    const cs = getComputedStyle(el); const fg = parse(cs.color);
    if (!fg) { unknown++; continue; }
    const bg = bgOf(el); nText++;
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const eff = {r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a)};
    const rr = ratio(eff, bg); minRatio = Math.min(minRatio, rr);
    if (rr < (large ? 3 : 4.5)) low.push({tag: el.tagName.toLowerCase(), id: el.id, text: snip(own), ratio: +rr.toFixed(2),
                                          color: cs.color, bg: `rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})`, size});
  }
  out.contrast = {textElements: nText, unknownColour: unknown, minRatio: +minRatio.toFixed(2), below: low.slice(0, 25), belowCount: low.length};

  // 2. light islands (dark only) and dark islands (light only)
  const islands = [];
  for (const el of panel.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const c = parse(getComputedStyle(el).backgroundColor);
    if (!c || c.a < 0.5) continue;
    const r = el.getBoundingClientRect(); if (r.width * r.height < 300) continue;
    const L = lum(c);
    if ((dark && L > 0.35) || (!dark && L < 0.08)) islands.push({tag: el.tagName.toLowerCase(), id: el.id,
      cls: (typeof el.className === 'string' ? el.className : '').slice(0, 60), bg: getComputedStyle(el).backgroundColor,
      rect: rect(el), text: snip(el.textContent)});
  }
  out.islands = islands.slice(0, 25); out.islandCount = islands.length;

  // 3. clipping and overflow past the panel
  const pr = panel.getBoundingClientRect(); const clipped = [], past = [];
  for (const el of panel.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    const txt = snip(el.textContent);
    if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip' || cs.textOverflow === 'ellipsis') && el.scrollWidth > el.clientWidth + 1 && txt)
      clipped.push({tag: el.tagName.toLowerCase(), id: el.id, cls: (typeof el.className === 'string' ? el.className : '').slice(0, 50),
                    text: txt, clientWidth: el.clientWidth, scrollWidth: el.scrollWidth});
    if (r.right > pr.right + 1 && r.width > 0) past.push({tag: el.tagName.toLowerCase(), id: el.id, right: Math.round(r.right), text: txt.slice(0, 40)});
  }
  // inputs whose value is wider than the field
  const inputs = [];
  for (const inp of panel.querySelectorAll('input[type="text"], input:not([type]), textarea')) {
    if (!visible(inp)) continue;
    inputs.push({value: snip(inp.value), clientWidth: inp.clientWidth, scrollWidth: inp.scrollWidth, truncated: inp.scrollWidth > inp.clientWidth + 1});
  }
  out.clipped = clipped.slice(0, 30); out.clippedCount = clipped.length;
  out.pastPanel = past.slice(0, 15); out.pastPanelCount = past.length; out.panelRight = Math.round(pr.right);
  out.inputs = inputs;

  // 4. buttons
  out.buttons = Array.from(panel.querySelectorAll('button')).filter(visible).filter(b => snip(b.textContent)).map(b => {
    const cs = getComputedStyle(b); const fg = parse(cs.color); const bg = bgOf(b);
    return {text: snip(b.textContent), id: b.id, cls: (typeof b.className === 'string' ? b.className : '').replace(/svelte-\w+/g, '').trim().slice(0, 80),
            rect: rect(b), bg: cs.backgroundColor, color: cs.color, border: cs.borderTopColor + ' ' + cs.borderTopWidth,
            whiteSpace: cs.whiteSpace, lines: Math.round(b.getBoundingClientRect().height / (parseFloat(cs.lineHeight) || 20)),
            contrast: fg ? +ratio(fg, bg).toFixed(2) : null};
  });

  // 5. rects of the lane ids
  const ids = tabId === 'eval'
    ? ['eval-intro', 'eval-options', 'eval-use-claude', 'eval-summary', 'eval-retrieval', 'eval-probes', 'eval-actions', 'eval-refresh',
       'eval-voice-rerun', 'eval-retrieval-rerun', 'eval-note', 'eval-live', 'eval-live-controls', 'eval-condition', 'eval-live-run', 'eval-live-result']
    : ['status-safeguards', 'status-audit', 'status-audit-counts', 'status-audit-tail', 'status-audit-refresh', 'status-redaction',
       'status-redaction-report', 'status-redaction-refresh', 'status-md', 'status-controls', 'status-free-gpu', 'status-warm-tab', 'status-warm',
       'status-refresh', 'status-maintenance', 'status-rebuild-index', 'status-rebuild-digest', 'status-telemetry'];
  out.rects = {};
  for (const id of ids) { const el = document.getElementById(id); out.rects[id] = el ? rect(el) : null; }

  // 6. Markdown table column alignment
  out.tables = [];
  for (const t of panel.querySelectorAll('table')) {
    if (!visible(t) || t.closest('[role="grid"]')) continue;
    const ths = Array.from(t.querySelectorAll('thead th'));
    if (!ths.length) continue;
    const head = ths.map(th => Math.round(th.getBoundingClientRect().left));
    const worst = []; let rows = 0;
    for (const tr of t.querySelectorAll('tbody tr')) {
      rows++;
      Array.from(tr.children).forEach((td, i) => {
        const d = Math.round(td.getBoundingClientRect().left) - (head[i] ?? 0);
        if (Math.abs(d) > 14) worst.push({row: rows, col: i + 1, dx: d, text: snip(td.textContent).slice(0, 30)});
      });
    }
    const hs = ths.map(th => snip(th.textContent));
    out.tables.push({owner: (t.closest('[id]') || {}).id, headers: hs, headLeft: head, rows, misaligned: worst.slice(0, 12),
                     misalignedCount: worst.length, rect: rect(t), cellMaxLines: Math.max(...Array.from(t.querySelectorAll('td')).map(td => {
                       const cs = getComputedStyle(td); return Math.round(td.getBoundingClientRect().height / (parseFloat(cs.lineHeight) || 20)); }))});
  }

  // 7. served CSS: rules that mention this tab, and how :is() lists from twin.css were emitted
  const mine = [], isRules = []; let dup = 0;
  for (const sh of Array.from(document.styleSheets)) {
    let rules; try { rules = sh.cssRules; } catch (e) { continue; }
    const walk = (list) => { for (const r of Array.from(list)) {
      if (r.cssRules && !r.selectorText) walk(r.cssRules);
      if (!r.selectorText) continue;
      if (r.selectorText.includes('#tab-' + tabId)) mine.push(r.selectorText);
      if (r.selectorText.includes(':is(') && r.selectorText.includes('twin-table')) isRules.push(r.selectorText);
    } };
    walk(rules);
  }
  const seen = new Map(); for (const s of mine) { const k = s.replace(/\.[\w-]+\.[\w-]+\.[\w-]+\s/g, ''); seen.set(k, (seen.get(k) || 0) + 1); }
  for (const v of seen.values()) if (v > 1) dup++;
  out.css = {rulesMentioningTab: mine.length, sample: mine.slice(0, 6), prefixedSample: mine.filter(s => !s.trim().startsWith('#tab-')).slice(0, 4),
             twinTableIsRules: isRules.slice(0, 4)};
  out.markdownDoubleClass = {
    statusMdInnerTwinCard: document.querySelectorAll('#status-md .twin-card').length,
    evalProbesInner: document.querySelectorAll('#eval-probes .eval-md-table').length};
  out.gridCellFont = (() => { const c = panel.querySelector('[role="gridcell"]'); return c ? getComputedStyle(c).fontFamily : null; })();
  return out;
})('%TAB%')
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
    ap.add_argument("--widths", default="1440,400")
    ap.add_argument("--wait", type=float, default=8.0)
    ap.add_argument("--boot-timeout", type=float, default=240.0)
    a = ap.parse_args()
    if 7861 <= a.port <= 7870:
        print("refusing ports 7861-7870 (the demo app)")
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    tabs = [t for t in a.tabs.split(",") if t]
    themes = [t for t in a.themes.split(",") if t]
    widths = [int(w) for w in a.widths.split(",") if w]
    if not wait_for_app(a.port, a.boot_timeout):
        print(f"FAIL no app on port {a.port}")
        return 2
    print(f"app answered on port {a.port}")
    dport = free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_review_es_{a.port}_")
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
        combos = [(w, th, tb) for w in widths for th in themes for tb in tabs if w == 1440 or th == "light"]
        for width, theme, tab in combos:
            page.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": SEGMENT, "deviceScaleFactor": 1,
                                                             "mobile": False})
            url = f"http://127.0.0.1:{a.port}/?tab={tab}&__theme={theme}&nomotion=1"
            page.events.clear()
            page.call("Page.navigate", {"url": url})
            page.wait_event("Page.loadEventFired", timeout=45)
            time.sleep(a.wait)
            js = PROBE_JS.replace("%TAB%", tab)
            first = page.call("Runtime.evaluate", {"expression": js, "returnByValue": True})["result"].get("value") or {}
            height = min(int(first.get("scrollHeight") or SEGMENT), MAX_HEIGHT)
            page.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                             "mobile": False})
            time.sleep(2.5)
            info = page.call("Runtime.evaluate", {"expression": js, "returnByValue": True})["result"].get("value") or {}
            height = min(int(info.get("scrollHeight") or height), MAX_HEIGHT)
            parts = []
            for n, y in enumerate(range(0, height, SEGMENT), start=1):
                h = min(SEGMENT, height - y)
                shot = page.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True,
                                                            "clip": {"x": 0, "y": y, "width": width, "height": h, "scale": 1}})
                png = out_dir / f"{theme}_{width}_{tab}_p{n}.png"
                png.write_bytes(base64.b64decode(shot["data"]))
                parts.append(png.name)
            row = {"width": width, "theme": theme, "tab": tab, "height": height, "parts": parts, **info}
            report.append(row)
            c = info.get("contrast") or {}
            print(f"{width} {theme} {tab}: selected={info.get('selectedTab')!r} dark={info.get('dark')} height={height} "
                  f"scrollWidth={info.get('scrollWidth')}/{info.get('innerWidth')} parts={len(parts)} "
                  f"minContrast={c.get('minRatio')} below={c.get('belowCount')} islands={info.get('islandCount')} "
                  f"clipped={info.get('clippedCount')} pastPanel={info.get('pastPanelCount')}")
            if not info.get("panelFound"):
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
    (out_dir / "review_capture.json").write_text(json.dumps({"port": a.port, "ok": ok, "results": report}, indent=1),
                                                 encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
