"""P6 (docs mode) click probe, no model. Opens the app the way docs/DEMO.md section 2 does (no ?tab=) at 1440x1000 and
uses real mouse events (Input.dispatchMouseEvent, so hit-testing through the restyled CSS is exercised):
- reads #gpu-note, the selected tab and the Onboarding Walkthrough steps, clicks the step 3 and step 2 labels (B1.1)
  and reads them again;
- clicks each tab in the demo order (decide, ask, act, items, eval, status, see), polls #gpu-note until it names the
  tab, and measures document-relative rects of the controls DEMO.md places above or below the fold;
- re-measures Act at 1440x900;
- reports what element sits under the blue dot seen at (innerWidth-37, innerHeight-103) in every headless shot.
Only for an app started with TWIN_NO_WARM=1 on a UI port (7871-7879): a tab select then only does the bookkeeping
("Pre-warm skipped (TWIN_NO_WARM=1)"). Reuses scripts/dev/finish/cdp_shot.py; standard library only.
  python scripts/dev/finish/p6_click_probe.py --port 7871 --out-dir scripts/dev/demo/click_probe
"""
import argparse
import base64
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("cdp_shot", ROOT / "scripts" / "dev" / "finish" / "cdp_shot.py")
cdp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdp)

ORDER = ["decide", "ask", "act", "items", "eval", "status", "see"]
TEXTS = {
    "onboarding": ["1. Run the interview", "3. Rebuild the index", "Check again"],
    "decide": ["Situation", "B1: Would I do it?", "B2: A or B?", "Raw result", "Say it in my voice", "In my voice"],
    "ask": ["Message", "Send", "Clear", "Condition", "Temperature", "Q8 Stheno (Ollama, slow)",
            "Consistency check (qwen2.5)", "Trace"],
    "act": ["Request", "Run", "Answer", "Polished", "Polish with Stheno", "Trace"],
    "items": ["Save answers", "Condition", "Run twin (qwen3-8b-8k, Stheno, two judges)", "Score (no model)",
              "Scores per condition and instrument"],
    "eval": ["Use Claude ceiling judge (needs ANTHROPIC_API_KEY)", "Refresh", "Re-run voice bake-off (~6 min)",
             "Re-run retrieval bake-off", "Live: one candidate x one question (~15 s)"],
    "status": ["Refresh audit tail", "Refresh redaction report", "Free GPU", "Tab to warm", "Warm current tab", "Refresh",
               "Rebuild index + digest", "Rebuild digest (force, qwen3:8b)"],
    "see": ["Image", "Look", "Description (qwen3.5)", "Reaction (in my voice)"],
}

NOTE_JS = r"""
(() => {
  const n = document.getElementById('gpu-note');
  const tabs = [...document.querySelectorAll('button[role="tab"][id^="tab-"][id$="-button"]')];
  const sel = tabs.find(b => b.getAttribute('aria-selected') === 'true');
  const strip = document.getElementById('status-strip');
  return {note: n ? n.innerText.replace(/\s+/g, ' ').trim() : null, selected: sel ? sel.id : null,
          strip: strip ? strip.innerText.replace(/\s+/g, ' ').trim().slice(0, 300) : null,
          scrollY: window.scrollY, innerHeight: window.innerHeight,
          scrollHeight: document.documentElement.scrollHeight};
})()
"""

TABBTN_JS = r"""
((id) => {
  const b = document.getElementById(`tab-${id}-button`);
  if (!b) return {missing: id};
  const r = b.getBoundingClientRect();
  const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
  const hit = document.elementFromPoint(x, y);
  return {x, y, width: Math.round(r.width), height: Math.round(r.height), text: b.textContent.trim(),
          hit_ok: !!hit && (hit === b || b.contains(hit)),
          hit: hit ? (hit.tagName.toLowerCase() + '#' + (hit.id || '') + '.' + String(hit.className || '').slice(0, 60)) : null};
})
"""

RECTS_JS = r"""
((tabId, texts) => {
  const panel = document.getElementById(`tab-${tabId}`);
  if (!panel) return {missing: tabId};
  const all = [...panel.querySelectorAll('button, label, span, p, div, h2, h3, h4, strong')];
  const out = {};
  for (const t of texts) {
    let best = null, bestArea = Infinity;
    for (const el of all) {
      const txt = (el.innerText || '').replace(/\s+/g, ' ').trim();
      if (txt !== t) continue;
      const r = el.getBoundingClientRect();
      const area = r.width * r.height;
      if (area > 0 && area < bestArea) { best = el; bestArea = area; }
    }
    if (!best) { out[t] = null; continue; }
    const target = best.closest('button') || best;
    const r = target.getBoundingClientRect();
    out[t] = {tag: target.tagName.toLowerCase(), id: target.id || '', top: Math.round(r.top + window.scrollY),
              bottom: Math.round(r.bottom + window.scrollY), left: Math.round(r.left), right: Math.round(r.right)};
  }
  return {innerHeight: window.innerHeight, scrollHeight: document.documentElement.scrollHeight, rects: out};
})
"""

WALK_JS = r"""
(() => {
  const w = document.getElementById('onboarding-walkthrough'); if (!w) return {missing: 'onboarding-walkthrough'};
  const R = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom),
            width: Math.round(r.width), height: Math.round(r.height)}; };
  const steps = [...w.querySelectorAll('[role="tab"]')].map(b => {
    const l = b.querySelector(':scope > span + span');
    return {sel: b.getAttribute('aria-selected'), disabled: b.disabled, label: R(l), text: l ? l.textContent.trim() : null,
            cursor: getComputedStyle(b).cursor}; });
  const statuses = {};
  for (const k of ['interview', 'redact', 'index', 'items']) {
    const el = document.getElementById('onboarding-status-' + k);
    statuses[k] = el ? {visible: el.getClientRects().length > 0, text: el.innerText.replace(/\s+/g, ' ').trim().slice(0, 90)} : null;
  }
  return {steps, statuses};
})()
"""

DOT_JS = r"""
(() => {
  const x = window.innerWidth - 37, y = window.innerHeight - 103;
  const el = document.elementFromPoint(x, y);
  const chain = []; let e = el;
  while (e && chain.length < 6) {
    chain.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') +
               (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/).slice(0, 3).join('.') : ''));
    e = e.parentElement;
  }
  const fixed = [...document.querySelectorAll('body *')].filter(n => getComputedStyle(n).position === 'fixed' && n.getClientRects().length)
    .map(n => { const r = n.getBoundingClientRect();
      return {tag: n.tagName.toLowerCase(), id: n.id, cls: String(n.className || '').slice(0, 60), left: Math.round(r.left),
              top: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)}; }).slice(0, 15);
  return {x, y, chain, fixed};
})()
"""


def ev(page, js):
    r = page.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    if r.get("exceptionDetails"):
        return {"exception": json.dumps(r["exceptionDetails"])[:300]}
    return r.get("result", {}).get("value")


def click(page, x, y):
    page.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    page.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    page.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def viewport(page, h):
    page.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": h, "deviceScaleFactor": 1, "mobile": False})


def shot(page, path: Path, clip=None):
    params = {"format": "png"}
    if clip:
        params["clip"] = clip
    path.write_bytes(base64.b64decode(page.call("Page.captureScreenshot", params)["data"]))


def rects(page, tab):
    return ev(page, f"({RECTS_JS})({json.dumps(tab)}, {json.dumps(TEXTS[tab])})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    if not 7871 <= a.port <= 7879:
        print("refusing: UI ports 7871-7879 only")
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dport = cdp.free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_p6_click_{a.port}_")
    proc = subprocess.Popen([cdp.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}", f"--user-data-dir={profile}",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rec: dict = {"port": a.port, "url": f"http://127.0.0.1:{a.port}/?__theme=light&nomotion=1"}
    page, ok = None, True
    try:
        target = None
        for _ in range(100):
            try:
                target = next((t for t in cdp.get_json(f"http://127.0.0.1:{dport}/json/list") if t.get("type") == "page"), None)
            except OSError:
                target = None
            if target:
                break
            time.sleep(0.2)
        page = cdp.WebSocket(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        viewport(page, 1000)
        page.events.clear()
        page.call("Page.navigate", {"url": rec["url"]})
        rec["load_event"] = page.wait_event("Page.loadEventFired", timeout=45) is not None
        time.sleep(8)
        rec["on_load"] = ev(page, NOTE_JS)
        rec["blue_dot"] = ev(page, DOT_JS)
        shot(page, out_dir / "dot_clip.png", {"x": 1440 - 37 - 23, "y": 1000 - 103 - 23, "width": 46, "height": 46, "scale": 4})
        rec["onboarding_rects"] = rects(page, "onboarding")

        walk = [{"action": "initial", "state": ev(page, WALK_JS)}]
        for idx, name in ((2, "mouse on step 3 label"), (1, "mouse on step 2 label")):
            st = ev(page, WALK_JS)
            lab = ((st or {}).get("steps") or [{}] * 4)[idx].get("label")
            if not lab or not lab.get("width"):
                walk.append({"action": name, "error": "no label rect"})
                continue
            xy = ((lab["left"] + lab["right"]) // 2, (lab["top"] + lab["bottom"]) // 2)
            click(page, *xy)
            time.sleep(1.5)
            walk.append({"action": name, "xy": xy, "state": ev(page, WALK_JS)})
        rec["walkthrough"] = walk
        shot(page, out_dir / "onboarding_after_clicks.png")

        tabs = []
        for tab in ORDER:
            ev(page, "window.scrollTo(0, 0)")
            time.sleep(0.4)
            btn = ev(page, f"({TABBTN_JS})({json.dumps(tab)})")
            row = {"tab": tab, "button": btn}
            if not btn or btn.get("missing"):
                row["error"] = "tab button missing"
                ok = False
                tabs.append(row)
                continue
            want = "Status open" if tab == "status" else f"Active tab: {tab}."
            t0 = time.time()
            click(page, btn["x"], btn["y"])
            note = None
            while time.time() - t0 < 10:
                note = ev(page, NOTE_JS)
                if (note or {}).get("note", "") and note["note"].startswith(want):
                    break
                time.sleep(0.25)
            row["note_ms"] = round((time.time() - t0) * 1000)
            row["after"] = note
            row["note_ok"] = bool((note or {}).get("note", "").startswith(want)) and (note or {}).get("selected") == f"tab-{tab}-button"
            ok = ok and row["note_ok"]
            time.sleep(1.0)
            row["rects_1000"] = rects(page, tab)
            if tab == "act":
                shot(page, out_dir / "act_1440x1000.png")
                viewport(page, 900)
                time.sleep(1.2)
                row["rects_900"] = rects(page, tab)
                shot(page, out_dir / "act_1440x900.png")
                viewport(page, 1000)
                time.sleep(1.2)
            tabs.append(row)
        rec["tabs"] = tabs
        rec["final"] = ev(page, NOTE_JS)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {type(e).__name__}: {e}")
        rec["error"] = f"{type(e).__name__}: {e}"
        ok = False
    finally:
        if page is not None:
            page.close()
        try:
            browser = cdp.WebSocket(cdp.get_json(f"http://127.0.0.1:{dport}/json/version")["webSocketDebuggerUrl"], timeout=5)
            browser.call("Browser.close", timeout=5)
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    (out_dir / "click_probe.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")

    ol = rec.get("on_load") or {}
    print(f"on load: selected={ol.get('selected')} note={ol.get('note')!r}")
    print(f"on load strip: {ol.get('strip')!r}")
    bd = rec.get("blue_dot") or {}
    print(f"blue dot point ({bd.get('x')},{bd.get('y')}): chain={bd.get('chain')} fixed={bd.get('fixed')}")
    for w in rec.get("walkthrough") or []:
        st = w.get("state") or {}
        steps = "; ".join(f"{s.get('text')!r} sel={s.get('sel')} disabled={s.get('disabled')} cursor={s.get('cursor')}"
                          for s in st.get("steps") or [])
        vis = [k for k, v in (st.get("statuses") or {}).items() if v and v.get("visible")]
        print(f"walkthrough {w.get('action')} {w.get('xy', '')}: {steps} | visible status: {vis} {w.get('error', '')}")
    for k, v in ((rec.get("onboarding_rects") or {}).get("rects") or {}).items():
        print(f"  onboarding {k!r}: {v}")
    for t in rec.get("tabs") or []:
        b = t.get("button") or {}
        af = t.get("after") or {}
        print(f"tab {t['tab']}: click ({b.get('x')},{b.get('y')}) hit_ok={b.get('hit_ok')} -> note_ok={t.get('note_ok')} "
              f"in {t.get('note_ms')} ms: selected={af.get('selected')} note={af.get('note')!r}")
        for key in ("rects_1000", "rects_900"):
            r = t.get(key)
            if not r:
                continue
            print(f"  {key} (innerHeight {r.get('innerHeight')}, scrollHeight {r.get('scrollHeight')}):")
            for name, v in (r.get("rects") or {}).items():
                print(f"    {name!r}: {v}")
    print(f"final strip: {(rec.get('final') or {}).get('strip')!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
