"""P6 (docs mode) tick probe, no model: does the Status tab's 5 s refresh replace a '**Last action:**' line?
Opens the app without ?tab= at 1440x1000, clicks the Status tab, then clicks 'Warm current tab'. With TWIN_NO_WARM=1
its handler returns a Last action note without warming anything (twin/ui/status.py warm_handler returns early when no
tab has a model or when TWIN_NO_WARM=1). That is the same path Free GPU's note takes (free_gpu_handler ->
status_markdown(note)), while the frame timer's tick calls status_refresh -> status_markdown() with no note. The probe
polls #status-md for 16 s and records when the line appears and when it goes. UI ports (7871-7879) only; reuses
scripts/dev/finish/p6_click_probe.py and cdp_shot.py.
  python scripts/dev/finish/p6_tick_probe.py --port 7871 --out-dir scripts/dev/demo/click_probe
"""
import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("p6_click_probe", ROOT / "scripts" / "dev" / "finish" / "p6_click_probe.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)
cdp = cp.cdp

MD_JS = r"""
(() => {
  const md = document.getElementById('status-md');
  const t = md ? md.innerText : '';
  const la = t.split('\n').find(l => l.startsWith('Last action:')) || null;
  const tm = (t.match(/Time:\s*([0-9:]+)/) || [null, null])[1];
  const strip = document.getElementById('status-strip');
  const st = strip ? ((strip.innerText.match(/(\d\d:\d\d:\d\d)/) || [null, null])[1]) : null;
  return {last_action: la, time: tm, strip_time: st};
})()
"""

BTN_JS = r"""
((text) => {
  const b = [...document.querySelectorAll('#tab-status button')].find(x => x.innerText.replace(/\s+/g, ' ').trim() === text);
  if (!b) return null;
  b.scrollIntoView({block: 'center', behavior: 'instant'});
  const r = b.getBoundingClientRect();
  const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
  const hit = document.elementFromPoint(x, y);
  return {id: b.id, x, y, hit_ok: !!hit && (hit === b || b.contains(hit))};
})
"""


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
    profile = tempfile.mkdtemp(prefix=f"twin_p6_tick_{a.port}_")
    proc = subprocess.Popen([cdp.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}", f"--user-data-dir={profile}",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rec: dict = {"port": a.port}
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
        cp.viewport(page, 1000)
        page.events.clear()
        page.call("Page.navigate", {"url": f"http://127.0.0.1:{a.port}/?__theme=light&nomotion=1"})
        page.wait_event("Page.loadEventFired", timeout=45)
        time.sleep(7)
        btn = cp.ev(page, f"({cp.TABBTN_JS})('status')")
        cp.click(page, btn["x"], btn["y"])
        t_tab = time.time()
        while time.time() - t_tab < 10:
            n = cp.ev(page, cp.NOTE_JS) or {}
            if (n.get("note") or "").startswith("Status open"):
                break
            time.sleep(0.25)
        rec["status_note"] = (cp.ev(page, cp.NOTE_JS) or {}).get("note")
        time.sleep(1.0)
        rec["before_click"] = cp.ev(page, MD_JS)
        wb = cp.ev(page, f"({BTN_JS})('Warm current tab')")
        rec["warm_button"] = wb
        time.sleep(0.6)
        wb = cp.ev(page, f"({BTN_JS})('Warm current tab')")
        t0 = time.time()
        cp.click(page, wb["x"], wb["y"])
        timeline = []
        while time.time() - t0 < 16:
            s = cp.ev(page, MD_JS) or {}
            timeline.append({"t": round(time.time() - t0, 2), **s})
            time.sleep(0.5)
        rec["timeline"] = timeline
        seen = [p["t"] for p in timeline if p.get("last_action")]
        rec["appeared_s"] = seen[0] if seen else None
        gone = [p["t"] for p in timeline if seen and p["t"] > seen[0] and not p.get("last_action")]
        rec["gone_s"] = gone[0] if gone else None
        rec["last_action_text"] = next((p["last_action"] for p in timeline if p.get("last_action")), None)
        ok = rec["appeared_s"] is not None
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
    (out_dir / "tick_probe.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"status note: {rec.get('status_note')!r}")
    print(f"before click: {rec.get('before_click')}")
    print(f"warm button: {rec.get('warm_button')}")
    print(f"Last action text: {rec.get('last_action_text')!r}")
    print(f"appeared at +{rec.get('appeared_s')} s, gone at +{rec.get('gone_s')} s (None = still there at +16 s)")
    prev = None
    for p in rec.get("timeline") or []:
        key = (bool(p.get("last_action")), p.get("time"), p.get("strip_time"))
        if key != prev:
            print(f"  +{p['t']:>5} s last_action={'yes' if p.get('last_action') else 'no '} status Time {p.get('time')} strip {p.get('strip_time')}")
            prev = key
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
