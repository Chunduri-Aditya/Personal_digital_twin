"""Review r1 of lane onboarding_items (docs/PLAN_FINISH.md P4): in-place captures that ui_check's 1440x1000
top-of-tab shots can't show. Standard library only; reuses the DevTools client in scripts/dev/finish/cdp_shot.py.

Point it only at an app started with TWIN_NO_WARM=1 on a UI port (scripts/dev/finish/review_oi_r1_harness.ps1 boots
and stops one). It clicks only the Onboarding walkthrough step labels (DEMO B1.1) and the Items accordion headers,
both client-side; it never clicks a button that calls an endpoint and never touches the Wave dropdown.

  python scripts/dev/finish/review_oi_r1_capture.py --port 7876 --out-dir <dir>
Writes <dir>/cap_<theme>_<width>_<name>.png and <dir>/capture.json. Exit 0 when every capture ran."""
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

ONB_JS = r"""
(() => {
  const R = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width)}; };
  const w = document.querySelector('#onboarding-walkthrough');
  const sheet = R(w);
  const tabs = w ? [...w.querySelectorAll('[role="tab"]')] : [];
  const hit = (b, x, y) => { const el = document.elementFromPoint(x, y); if (!el) return null;
    return b.contains(el) ? 'own-button' : (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + (typeof el.className === 'string' ? el.className.slice(0, 50) : '')); };
  const steps = tabs.map(b => {
    const spans = b.querySelectorAll(':scope > span');
    const num = spans[0] || null, lab = spans[1] || null;
    const lr = R(lab), nr = R(num);
    const cs = lab ? getComputedStyle(lab) : null, ncs = num ? getComputedStyle(num) : null;
    return {selected: b.getAttribute('aria-selected'), text: lab ? lab.textContent.trim() : null, label: lr, num: nr,
      labelVisible: cs ? (cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0) : null,
      labelFont: cs && cs.fontSize, labelWeight: cs && cs.fontWeight, labelColor: cs && cs.color,
      numBg: ncs && ncs.backgroundColor, numColor: ncs && ncs.color, numBorder: ncs && ncs.borderTopColor,
      withinSheet: (lr && sheet) ? (lr.left >= sheet.left && lr.right <= sheet.right) : null,
      withinViewport: lr ? (lr.left >= 0 && lr.right <= innerWidth) : null,
      hitCenter: lr ? hit(b, (lr.left + lr.right) / 2, (lr.top + lr.bottom) / 2) : null,
      hitLeft: lr ? hit(b, lr.left + 4, (lr.top + lr.bottom) / 2) : null,
      hitRight: lr ? hit(b, lr.right - 4, (lr.top + lr.bottom) / 2) : null};
  });
  const panels = w ? [...w.querySelectorAll('[role="tabpanel"]')].filter(p => p.getClientRects().length && getComputedStyle(p).display !== 'none') : [];
  const chk = document.querySelector('#onboarding-check');
  return {innerWidth, scrollWidth: document.documentElement.scrollWidth, sheet, steps,
    status: panels.map(p => p.innerText.replace(/\s+/g, ' ').slice(0, 260)),
    check: chk ? {text: chk.textContent.trim(), rect: R(chk), bg: getComputedStyle(chk).backgroundColor, color: getComputedStyle(chk).color} : null};
})()
"""

ITEMS_JS = r"""
(() => {
  const R = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width), height: Math.round(r.height)}; };
  const CS = (el, props) => { if (!el) return null; const c = getComputedStyle(el); const o = {}; for (const p of props) o[p] = c.getPropertyValue(p); return o; };
  const q = s => document.querySelector(s);
  const btn = id => { const b = q('#' + id); return b && {text: b.textContent.trim(), rect: R(b), style: CS(b, ['color', 'background-color', 'border-top-color', 'white-space', 'font-size'])}; };
  const scores = q('#items-scores');
  let cell = null;
  if (scores) { for (const el of scores.querySelectorAll('*')) { if (el.children.length === 0 && el.textContent.trim() === 'demographic') { cell = el; break; } } }
  const dec = q('#items-decision');
  const inner = dec ? dec.querySelector('.twin-card') : null;
  const ps = dec ? [...dec.querySelectorAll('p')] : [];
  const lik = q('.item-likert');
  const files = q('#items-files');
  const accs = [...document.querySelectorAll('#items-form button')].filter(b => b.querySelectorAll(':scope > span').length >= 2)
    .map(b => ({text: b.textContent.trim().slice(0, 50), label: CS(b.querySelector(':scope > span'), ['font-size', 'font-weight', 'color'])}));
  return {innerWidth, scrollWidth: document.documentElement.scrollWidth,
    save: btn('items-save'), run: btn('items-run'), score: btn('items-score'),
    waveRow: R(q('#items-wave-row')), runRow: R(q('#items-run-row')), condition: R(q('#items-condition')), scores: R(scores),
    cell: CS(cell, ['font-family', 'font-variant-numeric', 'font-size', 'color']),
    th: CS(scores ? scores.querySelector('th') : null, ['font-family', 'color', 'background-color']),
    decision: dec ? {rect: R(dec), outer: CS(dec, ['border-top-width', 'box-shadow', 'background-color', 'padding-top', 'min-height']),
      inner: inner ? CS(inner, ['border-top-width', 'box-shadow', 'padding-top', 'background-color']) : null,
      strong: CS(ps[0] ? ps[0].querySelector('strong') : null, ['font-size', 'font-weight', 'color']),
      footer: ps[1] ? CS(ps[1], ['font-size', 'color', 'border-top-width', 'font-style']) : null,
      text: dec.innerText.replace(/\s+/g, ' ').slice(0, 420)} : null,
    likert: lik ? [...lik.querySelectorAll('label')].map(l => ({text: l.textContent.trim(), top: Math.round(l.getBoundingClientRect().top),
      checked: !!l.querySelector('input:checked'), bg: getComputedStyle(l).backgroundColor, fs: getComputedStyle(l).fontSize})) : [],
    likertTitle: lik ? CS(lik.querySelector(':scope > span'), ['font-size', 'font-weight', 'color']) : null,
    filesEm: files ? [...files.querySelectorAll('em')].map(e => e.textContent) : [],
    files: files ? files.innerText.replace(/\s+/g, ' ').slice(0, 500) : null,
    accordions: accs};
})()
"""


def ev(page, js):
    r = page.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    if r.get("exceptionDetails"):
        return {"exception": json.dumps(r["exceptionDetails"])[:400]}
    return r.get("result", {}).get("value")


def scroll(page, selector, block):
    js = ("(() => { const el = document.querySelector(%s); if (!el) return false; "
          "el.scrollIntoView({block: %s, behavior: 'instant'}); return true; })()") % (json.dumps(selector), json.dumps(block))
    ok = ev(page, js)
    time.sleep(1.2)
    return ok


def shot(page, out_dir, name, shots):
    data = page.call("Page.captureScreenshot", {"format": "png"})["data"]
    p = out_dir / f"{name}.png"
    p.write_bytes(base64.b64decode(data))
    shots.append(f"{p.name} {p.stat().st_size}")


def click(page, x, y):
    page.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    page.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    page.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def viewport(page, w, h):
    page.call("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})


def goto(page, port, tab, theme, wait):
    page.events.clear()
    page.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/?tab={tab}&__theme={theme}&nomotion=1"})
    loaded = page.wait_event("Page.loadEventFired", timeout=45) is not None
    time.sleep(wait)
    return loaded


def run(page, port, out_dir, rec, shots):
    for theme in ("light", "dark"):
        t = rec.setdefault(theme, {})
        # Onboarding at the demo width: labels whole, and every label clickable on its text (DEMO B1.1)
        viewport(page, 1440, 1000)
        t["onb_loaded"] = goto(page, port, "onboarding", theme, 8)
        t["onb_initial"] = ev(page, ONB_JS)
        clicks = []
        # (step index, where on the label to click): away from the circle, so the label's own area is tested
        for idx, where in ((1, "left"), (2, "right"), (3, "left"), (0, "right")):
            m = ev(page, ONB_JS)
            st = (m.get("steps") or [{}] * 4)[idx] if isinstance(m, dict) else {}
            lr = st.get("label")
            if not lr:
                clicks.append({"idx": idx, "error": "no label rect"})
                continue
            x = lr["left"] + 10 if where == "left" else lr["right"] - 10
            y = (lr["top"] + lr["bottom"]) // 2
            click(page, x, y)
            time.sleep(1.5)
            after = ev(page, ONB_JS)
            sel = [i for i, s in enumerate(after.get("steps") or []) if s.get("selected") == "true"]
            clicks.append({"label": st.get("text"), "x": x, "y": y, "selected_after": sel, "ok": sel == [idx],
                           "status": after.get("status"), "steps_after": [(s.get("text"), s.get("labelVisible"), s.get("withinSheet"), s.get("label")) for s in after.get("steps") or []]})
            if idx in (2, 3):
                shot(page, out_dir, f"cap_{theme}_1440_onb_step{idx + 1}", shots)
        t["onb_clicks"] = clicks

        # Items at the demo width, in place: the run row, then the table and the decision card (DEMO B6.1)
        t["items_loaded"] = goto(page, port, "items", theme, 12)
        t["items"] = ev(page, ITEMS_JS)
        t["scroll_runrow"] = scroll(page, "#items-run-row", "center")
        shot(page, out_dir, f"cap_{theme}_1440_items_runrow", shots)
        t["scroll_bottom"] = scroll(page, "#items-decision", "end")
        t["items_at_bottom"] = ev(page, ITEMS_JS)
        shot(page, out_dir, f"cap_{theme}_1440_items_bottom", shots)
        # the closed instrument groups (not in the demo; client-side toggles only)
        t["acc_open"] = ev(page, "(() => { const out = []; for (const id of ['items-group-game', 'items-group-gold', 'items-group-gss']) {"
                                 " const g = document.getElementById(id); const b = g ? [...g.querySelectorAll('button')].find(x => x.querySelectorAll(':scope > span').length >= 2) : null;"
                                 " if (b) { b.click(); out.push(id); } } return out; })()")
        time.sleep(2.0)
        for gid in ("items-group-game", "items-group-gold", "items-group-gss"):
            scroll(page, "#" + gid, "start")
            shot(page, out_dir, f"cap_{theme}_1440_{gid}", shots)

        # true 400 px: onboarding (compact stepper) and items (stacked buttons)
        viewport(page, 400, 900)
        goto(page, port, "onboarding", theme, 8)
        t["onb_400"] = ev(page, cdp.MEASURE_JS)
        t["onb_400_steps"] = ev(page, ONB_JS)
        shot(page, out_dir, f"cap_{theme}_400_onb", shots)
        goto(page, port, "items", theme, 12)
        t["items_400"] = ev(page, cdp.MEASURE_JS)
        scroll(page, "#items-run-row", "center")
        t["items_400_runrow"] = ev(page, ITEMS_JS)
        shot(page, out_dir, f"cap_{theme}_400_items_runrow", shots)
        scroll(page, "#items-decision", "end")
        shot(page, out_dir, f"cap_{theme}_400_items_bottom", shots)

    # other presenter widths for the stepper labels (light)
    for w, h in ((1280, 800), (1920, 1080)):
        viewport(page, w, h)
        goto(page, port, "onboarding", "light", 8)
        rec[f"onb_{w}"] = ev(page, ONB_JS)
        shot(page, out_dir, f"cap_light_{w}_onb", shots)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    if not 7871 <= a.port <= 7879:
        print("refusing a non-UI port (use 7871-7879)")
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dport = cdp.free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_review_oi_{a.port}_")
    proc = subprocess.Popen([cdp.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}", f"--user-data-dir={profile}",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rec, shots, ok, page = {}, [], True, None
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
        if not target:
            print("FAIL no DevTools page target")
            return 2
        page = cdp.WebSocket(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        run(page, a.port, out_dir, rec, shots)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {type(e).__name__}: {e}")
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
    rec["shots"] = shots
    (out_dir / "capture.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    for theme in ("light", "dark"):
        t = rec.get(theme, {})
        for c in t.get("onb_clicks", []):
            print(f"{theme} B1.1 click {c.get('label')!r} at ({c.get('x')},{c.get('y')}): selected {c.get('selected_after')} ok={c.get('ok')}")
        init = t.get("onb_initial") or {}
        for s in init.get("steps") or []:
            print(f"{theme} 1440 label {s.get('text')!r}: rect {s.get('label')} visible={s.get('labelVisible')} inSheet={s.get('withinSheet')} "
                  f"hit L/C/R={s.get('hitLeft')}/{s.get('hitCenter')}/{s.get('hitRight')} font={s.get('labelFont')}")
        it = t.get("items") or {}
        print(f"{theme} items buttons: save={it.get('save')} run={it.get('run')} score={it.get('score')}")
        print(f"{theme} items cell={it.get('cell')} th={it.get('th')}")
        print(f"{theme} items decision={it.get('decision')}")
        print(f"{theme} 400 onboarding scrollWidth={(t.get('onb_400') or {}).get('scrollWidth')} items scrollWidth={(t.get('items_400') or {}).get('scrollWidth')}")
    for w in (1280, 1920):
        for s in (rec.get(f"onb_{w}") or {}).get("steps") or []:
            print(f"light {w} label {s.get('text')!r}: visible={s.get('labelVisible')} inSheet={s.get('withinSheet')} rect={s.get('label')}")
    print(f"{len(shots)} screenshots -> {out_dir}")
    return 0 if ok and len(shots) >= 20 else 1


if __name__ == "__main__":
    sys.exit(main())
