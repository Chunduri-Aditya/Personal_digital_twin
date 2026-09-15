"""Review r1 of lane onboarding_items: DevTools probe for review_oi_r1_walk_app.py. For the plain and the lane-styled
walkthrough it records each step button (aria-selected, disabled, class, rects), then clicks: a forward label (step 4
text), a forward number (step 3 circle), a DOM .click() on step 4, and a backward number (step 1 circle), reading
the selected step and the visible panel after each. Standard library only; reuses scripts/dev/finish/cdp_shot.py.
  python scripts/dev/finish/review_oi_r1_walk_probe.py --port 7876 --out-dir <dir>"""
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

STATE_JS = r"""
((wid) => {
  const w = document.getElementById(wid); if (!w) return {missing: wid};
  const R = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom), width: Math.round(r.width), height: Math.round(r.height)}; };
  const tabs = [...w.querySelectorAll('[role="tab"]')];
  const panels = [...w.querySelectorAll('[role="tabpanel"]')].filter(p => p.getClientRects().length && getComputedStyle(p).display !== 'none').map(p => p.innerText.trim().slice(0, 40));
  return {steps: tabs.map(b => { const n = b.querySelector(':scope > span'); const l = b.querySelector(':scope > span + span');
    return {sel: b.getAttribute('aria-selected'), disabled: b.disabled, cls: (b.className || '').toString().slice(0, 80), btn: R(b), num: R(n), label: R(l), text: l ? l.textContent.trim() : null,
      pointer: getComputedStyle(b).pointerEvents, cursor: getComputedStyle(b).cursor}; }), panels};
})
"""


def ev(page, js):
    r = page.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
    if r.get("exceptionDetails"):
        return {"exception": json.dumps(r["exceptionDetails"])[:300]}
    return r.get("result", {}).get("value")


def state(page, wid):
    return ev(page, f"({STATE_JS})({json.dumps(wid)})")


def click(page, x, y):
    page.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    page.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    page.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def selected(st):
    return [i for i, s in enumerate((st or {}).get("steps") or []) if s.get("sel") == "true"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    if not 7871 <= a.port <= 7879:
        return 2
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dport = cdp.free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_review_walk_{a.port}_")
    proc = subprocess.Popen([cdp.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}", f"--user-data-dir={profile}",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rec, page, ok = {}, None, True
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
        page.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        for wid in ("plain-walkthrough", "onboarding-walkthrough"):
            page.events.clear()
            page.call("Page.navigate", {"url": f"http://127.0.0.1:{a.port}/?__theme=light"})
            page.wait_event("Page.loadEventFired", timeout=45)
            time.sleep(6)
            ev(page, f"document.getElementById({json.dumps(wid)}).scrollIntoView({{block: 'center', behavior: 'instant'}})")
            time.sleep(0.8)
            steps = []
            s0 = state(page, wid)
            steps.append({"action": "initial", "selected": selected(s0), "state": s0})
            acts = [("mouse on step 4 label text", lambda st: st["steps"][3]["label"], "label"),
                    ("mouse on step 3 number", lambda st: st["steps"][2]["num"], "num"),
                    ("DOM click() on step 4 button", None, "dom"),
                    ("mouse on step 1 number (backward)", lambda st: st["steps"][0]["num"], "num")]
            for name, pick, kind in acts:
                st = state(page, wid)
                if kind == "dom":
                    ev(page, f"document.getElementById({json.dumps(wid)}).querySelectorAll('[role=\"tab\"]')[3].click()")
                    xy = None
                else:
                    r = pick(st)
                    if not r or not r.get("width"):
                        steps.append({"action": name, "error": "no rect"})
                        continue
                    xy = ((r["left"] + r["right"]) // 2, (r["top"] + r["bottom"]) // 2)
                    click(page, *xy)
                time.sleep(1.2)
                after = state(page, wid)
                steps.append({"action": name, "xy": xy, "selected": selected(after), "panels": after.get("panels")})
            data = page.call("Page.captureScreenshot", {"format": "png"})["data"]
            (out_dir / f"walk_{wid}.png").write_bytes(base64.b64decode(data))
            rec[wid] = steps
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
    (out_dir / "walk_probe.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    for wid, steps in rec.items():
        init = steps[0]["state"]["steps"] if steps and "state" in steps[0] else []
        print(f"{wid} initial selected {steps[0].get('selected')}; buttons: "
              + "; ".join(f"{s.get('text')!r} sel={s.get('sel')} disabled={s.get('disabled')} cls={s.get('cls')!r} cursor={s.get('cursor')}" for s in init))
        for s in steps[1:]:
            print(f"{wid} {s.get('action')} at {s.get('xy')}: selected {s.get('selected')} panels {s.get('panels')} {s.get('error', '')}")
    return 0 if ok and len(rec) == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
