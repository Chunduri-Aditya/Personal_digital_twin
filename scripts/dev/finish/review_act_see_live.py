"""Review of lane act_see, round 1 (no GPU, no model call): render the Act and See tabs of the REAL app with the
recorded demo outputs (run 8 B5.2, run 3 BX.1, plus a synthetic connection error) injected by one model-free
page-load event, then shoot and probe them through the DevTools protocol.

It mirrors app.py main() (build_app, queue, theme and css, TAB_JS) minus the heartbeat, with TWIN_NO_WARM=1. It adds
one demo.load (api_name=False) that fills the Act and See outputs and opens the Trace accordion, launches on the lane
port 7874 inside this process, and closes the server before it exits. /api/ps is read before and after.

Run (project root): python scripts/dev/finish/review_act_see_live.py
Output: scripts/dev/shots/lane_act_see/review_r1/live/*.png and live.json
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

os.environ["TWIN_NO_WARM"] = "1"
os.environ["PYTHONUTF8"] = "1"
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "dev" / "finish"))
os.chdir(ROOT)
PORT = 7874
OUT = ROOT / "scripts" / "dev" / "shots" / "lane_act_see" / "review_r1" / "live"

import cdp_shot  # noqa: E402
import gradio as gr  # noqa: E402  (module level, so the fill() gr.Request annotation resolves)


def section(text: str, name: str) -> str:
    out, on = [], False
    for ln in text.splitlines():
        if ln.lstrip().startswith("[+") and "=== " in ln:
            if on:
                break
            on = f"=== {name} ===" in ln
            continue
        if on:
            out.append(ln)
    return "\n".join(out).strip("\n")


RUN8 = (ROOT / "scripts" / "dev" / "demo" / "run8_B5.2.txt").read_text(encoding="utf-8")
RUN3 = (ROOT / "scripts" / "dev" / "demo" / "run3_BX.1.txt").read_text(encoding="utf-8")
ACT_ANSWER, ACT_TRACE = section(RUN8, "answer"), section(RUN8, "trace_md")
SEE_DESC, SEE_REACT, SEE_TRACE = section(RUN3, "description"), section(RUN3, "reaction"), section(RUN3, "trace_md")
ERR = "ConnectionError: [WinError 10061] No connection could be made because the target machine actively refused it"

PROBE_ACT = r"""
(() => {
  const q = s => document.querySelector(s);
  const cs = (el, props) => { if (!el) return null; const c = getComputedStyle(el); const o = {};
    for (const p of props) o[p] = c.getPropertyValue(p); return o; };
  const rect = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)}; };
  const inner = q('#tab-act #act-trace .act-trace');
  const span = q('#tab-act #act-trace .act-trace > span');
  const kids = span ? Array.from(span.children).map(e => e.tagName.toLowerCase()
      + (typeof e.className === 'string' && e.className ? '.' + e.className.split(' ')[0] : '')) : [];
  const ta = s => { const t = q(s); return t ? {scrollH: t.scrollHeight, clientH: t.clientHeight} : null; };
  const pres = Array.from(document.querySelectorAll('#act-trace pre'));
  return {
    prose_div_classes: inner ? inner.className : null,
    span_children: kids.slice(0, 24), n_children: kids.length,
    firstChild: cs(span && span.firstElementChild, ['border-top-width','border-left-width','background-color','padding-top','border-top-left-radius','font-family']),
    heading: cs(q('#tab-act #act-trace .act-trace > span > p > strong:first-child'), ['font-family','font-size','color','font-weight']),
    toolHeading: cs(q('#tab-act #act-trace .act-trace > span > p > strong:first-child:has(> code)'), ['color']),
    chip: cs(q('#tab-act #act-trace .act-trace > span > p > strong:first-child > code'), ['font-family','background-color','color','padding-left','border-top-left-radius']),
    label: cs(q('#tab-act #act-trace .act-trace > span > p:has(+ div > pre)'), ['font-family','font-size','color']),
    pre: cs(q('#tab-act #act-trace .act-trace > span > div > pre'), ['font-family','background-color','border-top-width','color','white-space']),
    preSpanColor: cs(q('#act-trace pre span'), ['color']),
    copyBtn: cs(q('#tab-act #act-trace .act-trace > span > div > button'), ['background-color','color','border-top-color']),
    copyBtnHtml: q('#tab-act #act-trace .act-trace > span > div > button') ? q('#tab-act #act-trace .act-trace > span > div > button').outerHTML.slice(0, 160) : null,
    lonePara: cs(q('#tab-act #act-trace .act-trace > span > p:only-child'), ['background-color','border-left-width','color','border-top-width','font-family']),
    errStrong: cs(q('#tab-act #act-trace .act-trace > span > p:has(> strong:first-child + code) > strong'), ['color','font-family']),
    pres_overflowing_x: pres.filter(p => p.scrollWidth > p.clientWidth + 1).length, n_pres: pres.length,
    codeWs: cs(q('#act-trace pre code'), ['white-space','display','overflow-wrap']),
    preOx: cs(q('#act-trace pre'), ['overflow-x','overflow-wrap','white-space']),
    preDims: pres.map(p => [p.scrollWidth, p.clientWidth]),
    traceBlock: cs(q('#act-trace'), ['border-top-width','padding-top','background-color','font-family','min-height']),
    traceBlockScroll: q('#act-trace') ? [q('#act-trace').scrollWidth, q('#act-trace').clientWidth] : null,
    innerBox: cs(inner, ['border-top-width','padding-top','background-color']),
    answerCard: cs(q('#act-answer-card'), ['box-shadow','background-color','border-top-width','padding-top']),
    polishedCard: cs(q('#act-polished-card'), ['border-left-width','border-left-color','box-shadow','background-color','font-family','max-width']),
    polishedTa: cs(q('#tab-act .act-polished textarea'), ['font-family','font-size','background-color','border-top-color']),
    answerTa: ta('#tab-act .act-answer textarea'), polishedTaScroll: ta('#tab-act .act-polished textarea'),
    rects: {run: rect(q('#act-run')), polish: rect(q('#act-polish')), accordionBtn: rect(q('#tab-act .act-trace-accordion > button')),
            answerCard: rect(q('#act-answer-card')), polishedCard: rect(q('#act-polished-card')), trace: rect(q('#act-trace')),
            requestTa: rect(q('#tab-act #act-request textarea'))},
    accordionOpen: q('#act-trace') ? getComputedStyle(q('#act-trace')).display !== 'none' && q('#act-trace').offsetParent !== null : null,
  };
})()
"""

PROBE_SEE = r"""
(() => {
  const q = s => document.querySelector(s);
  const cs = (el, props) => { if (!el) return null; const c = getComputedStyle(el); const o = {};
    for (const p of props) o[p] = c.getPropertyValue(p); return o; };
  const rect = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)}; };
  const lis = document.querySelectorAll('#tab-see #see-trace li');
  const ta = s => { const t = q(s); return t ? {scrollH: t.scrollHeight, clientH: t.clientHeight} : null; };
  const inner = q('#tab-see #see-trace .see-trace');
  return {
    inner_classes: inner ? inner.className : null, n_li: lis.length,
    li0: cs(lis[0], ['font-family','list-style-type','padding-top','color']),
    lastLi: cs(lis.length ? lis[lis.length - 1] : null, ['border-top-width','font-weight','padding-top']),
    ul: cs(q('#tab-see #see-trace ul'), ['list-style-type','padding-left']),
    block: cs(q('#see-trace'), ['border-top-width','background-color','min-height','padding-top','font-family']),
    innerBox: cs(inner, ['border-top-width','padding-top','background-color']),
    firstP: cs(q('#tab-see #see-trace p'), ['background-color','border-left-width','color','font-family']),
    descCard: cs(q('#see-description-card'), ['border-top-width','background-color','box-shadow','padding-top']),
    reactCard: cs(q('#see-reaction-card'), ['border-left-width','border-left-color','box-shadow','background-color','max-width']),
    reactTa: cs(q('#tab-see .see-reaction textarea'), ['font-family','font-size','background-color','border-top-color']),
    descTa: cs(q('#tab-see .see-description textarea'), ['font-family','font-size','background-color','border-top-color']),
    reactTaScroll: ta('#tab-see .see-reaction textarea'), descTaScroll: ta('#tab-see .see-description textarea'),
    image: cs(q('#see-image'), ['border-top-style','border-top-color','background-color','border-top-width']),
    rects: {image: rect(q('#see-image')), look: rect(q('#see-look')), desc: rect(q('#see-description-card')),
            react: rect(q('#see-reaction-card')), trace: rect(q('#see-trace'))},
  };
})()
"""

JOBS = [
    ("act_filled_light_1440", "act", "light", "filled", 1440, 2900, PROBE_ACT),
    ("act_filled_dark_1440", "act", "dark", "filled", 1440, 2900, PROBE_ACT),
    ("see_filled_light_1440", "see", "light", "filled", 1440, 1100, PROBE_SEE),
    ("see_filled_dark_1440", "see", "dark", "filled", 1440, 1100, PROBE_SEE),
    ("act_error_dark_1440", "act", "dark", "error", 1440, 1200, PROBE_ACT),
    ("see_error_light_1440", "see", "light", "error", 1440, 1100, PROBE_SEE),
    ("act_filled_light_400", "act", "light", "filled", 400, 1900, PROBE_ACT),
    ("see_filled_dark_400", "see", "dark", "filled", 400, 1900, PROBE_SEE),
]
if "--errors" in sys.argv:
    JOBS = [j for j in JOBS if j[3] == "error"] + [
        ("act_codeprobe_light_1440", "act", "light", "filled", 1440, 1400, PROBE_ACT),
        ("act_empty_dark_1440", "act", "dark", "empty", 1440, 1000, PROBE_ACT),
        ("act_pending_light_1440", "act", "light", "pending", 1440, 1000, PROBE_ACT),
        ("see_pending_dark_1440", "see", "dark", "pending", 1440, 1000, PROBE_SEE),
    ]
if "--see-pending" in sys.argv:
    JOBS = [("see_pending_dark_1440", "see", "dark", "pending", 1440, 1000, PROBE_SEE)]
JSON_NAME = ("live_see_pending.json" if "--see-pending" in sys.argv
             else "live_errors.json" if "--errors" in sys.argv else "live.json")
EXPECT = {("act", "filled"): ("#act-trace", "Step 3 - assistant"), ("see", "filled"): ("#see-trace", "total 13603 ms"),
          ("act", "error"): ("#act-trace", "Error:"), ("see", "error"): ("#see-trace", "Error:"),
          ("act", "empty"): ("#act-trace", "(no trace)"), ("see", "empty"): ("#see-trace", "(upload an image first)")}


def api_ps() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as r:
            return r.read().decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}: {e}"


def port_free() -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PORT))
            return True
        except OSError:
            return False


def shoot() -> list[dict]:
    dport = cdp_shot.free_port()
    profile = tempfile.mkdtemp(prefix="twin_review_act_see_")
    proc = subprocess.Popen([cdp_shot.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             "--no-first-run", "--no-default-browser-check", f"--remote-debugging-port={dport}",
                             f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results, page = [], None
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
        page = cdp_shot.WebSocket(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        for name, tab, theme, state, width, height, probe in JOBS:
            page.call("Emulation.setDeviceMetricsOverride",
                      {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
            url = f"http://127.0.0.1:{PORT}/?tab={tab}&__theme={theme}&nomotion=1&state={state}"
            page.events.clear()
            page.call("Page.navigate", {"url": url})
            loaded = page.wait_event("Page.loadEventFired", timeout=45) is not None
            sel, txt = EXPECT.get((tab, state), ("#act-trace", "never-present-marker"))
            js = f"(() => {{ const e = document.querySelector({json.dumps(sel)}); return !!(e && e.textContent.includes({json.dumps(txt)})); }})()"
            filled, t0 = False, time.time()
            while state != "pending" and time.time() - t0 < 45:
                filled = bool(page.call("Runtime.evaluate", {"expression": js, "returnByValue": True})
                              .get("result", {}).get("value"))
                if filled:
                    break
                time.sleep(1)
            if state == "pending":
                mount, t1 = False, time.time()
                while not mount and time.time() - t1 < 40:
                    mount = bool(page.call("Runtime.evaluate", {
                        "expression": "!!document.querySelector('button[role=\"tab\"][aria-selected=\"true\"]')",
                        "returnByValue": True}).get("result", {}).get("value"))
                    time.sleep(0.5)
            time.sleep(7 if state == "pending" else 4)
            measure = page.call("Runtime.evaluate", {"expression": cdp_shot.MEASURE_JS, "returnByValue": True}) \
                .get("result", {}).get("value") or {}
            probed = page.call("Runtime.evaluate", {"expression": probe, "returnByValue": True}) \
                .get("result", {}).get("value")
            shot = page.call("Page.captureScreenshot", {"format": "png"})
            png = OUT / f"{name}.png"
            png.write_bytes(base64.b64decode(shot["data"]))
            row = {"name": name, "url": url, "load_event": loaded, "filled": filled, "png": str(png.relative_to(ROOT)),
                   "scrollWidth": measure.get("scrollWidth"), "innerWidth": measure.get("innerWidth"),
                   "selectedTab": measure.get("selectedTab"), "dark": measure.get("dark"),
                   "overflowing": (measure.get("overflowing") or [])[:10], "probe": probed}
            results.append(row)
            print(f"{name}: load={loaded} filled={filled} selected={row['selectedTab']!r} dark={row['dark']} "
                  f"scrollWidth={row['scrollWidth']} innerWidth={row['innerWidth']} "
                  f"overflowing={len(measure.get('overflowing') or [])}")
    finally:
        if page is not None:
            page.close()
        try:
            browser = cdp_shot.WebSocket(cdp_shot.get_json(f"http://127.0.0.1:{dport}/json/version")["webSocketDebuggerUrl"], timeout=5)
            browser.call("Browser.close", timeout=5)
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return results


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not port_free():
        print(f"FAIL port {PORT} is busy")
        return 3
    before = api_ps()
    print("api_ps_before:", before)

    import app as app_mod

    def fill(request: gr.Request):
        state = (dict(request.query_params).get("state") if request is not None else None) or "filled"
        if state == "pending":
            time.sleep(20)
        if state == "empty":
            return ("", "_(no trace)_", "", gr.Accordion(open=True), "", "", "_(upload an image first)_")
        if state == "error":
            return (f"Error: {ERR}", f"**Error:** `{ERR}`", "", gr.Accordion(open=True),
                    f"Error: {ERR}", "", f"**Error:** `{ERR}`")
        return (ACT_ANSWER, ACT_TRACE, ACT_ANSWER, gr.Accordion(open=True), SEE_DESC, SEE_REACT, SEE_TRACE)

    demo = app_mod.build_app()
    ids = ["act-answer", "act-trace", "act-polished", "act-trace-accordion", "see-description", "see-reaction",
           "see-trace"]
    comps = []
    for eid in ids:
        hits = [b for b in demo.blocks.values() if getattr(b, "elem_id", None) == eid]
        assert len(hits) == 1, (eid, len(hits))
        comps.append(hits[0])
    with demo:
        demo.load(fill, inputs=None, outputs=comps, api_name=False, concurrency_limit=None)
    demo.queue(default_concurrency_limit=1)
    theme, css = app_mod._theme_and_css()
    results, rc = [], 0
    try:
        demo.launch(server_name="127.0.0.1", server_port=PORT, inbrowser=False, show_error=True, js=app_mod.TAB_JS,
                    theme=theme, css=css, prevent_thread_lock=True, quiet=True)
        results = shoot()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {type(e).__name__}: {e}")
        rc = 1
    finally:
        demo.close()
    time.sleep(2)
    after = api_ps()
    print("api_ps_after:", after)
    print("port free after:", port_free())
    (OUT / JSON_NAME).write_text(json.dumps({"api_ps_before": before, "api_ps_after": after,
                                               "port_free_after": port_free(), "results": results},
                                              indent=1, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(json.dumps({"name": r["name"], "overflowing": r["overflowing"], "probe": r["probe"]}, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
