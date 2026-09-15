"""Render the Ask tab's states without any model (P4 ask lane helper; run as a file from the project root).

Why: ui_check.ps1 shows only the empty Ask tab. The rubric also asks for the streaming, waiting-for-a-model, hint,
checker and inline-error states, which only appear during a turn. This script boots the real app IN THIS PROCESS
(frame.build_app with the app's theme, CSS and TAB_JS, TWIN_NO_WARM=1) on a UI port, replaces
twin.pipelines.ask.ask_turn with a scripted generator (recorded demo text, no model, no network) and every model
client call with a function that raises, drives headless Chrome over the DevTools protocol (cdp_shot.py) and saves
full-page screenshots. It stops Chrome and the app before it exits, so it is safe under the PowerShell tool.

Usage (project root):
  python scripts/dev/finish/ask_states.py --port 7872 --out-dir scripts/dev/shots/lane_ask/states [--themes light,dark]
         [--widths 1440,400] [--dump-dom]
Output: <theme>_<width>_ask_<state>.png (states: empty, waiting, streaming, done, error), dom_<theme>_<width>.html
with --dump-dom, and states.json (scrollWidth per width and theme, /api/ps before and after).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import shutil
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
os.environ["TWIN_NO_WARM"] = "1"
os.environ["PYTHONUTF8"] = "1"
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.chdir(ROOT)

import cdp_shot  # noqa: E402  (WebSocket, find_chrome, free_port, get_json)

REPLY = ("ok wait, this is the one i've actually thought about, so bear with me. first thing i learned is that i'm "
         "not lazy, i'm allergic to being managed. at the agency i was late, resentful, doing the minimum, and i "
         "assumed that was just who i was. the week after i quit i worked twelve hour days for free on my own stuff "
         "and loved it. same person, different owner.\n\nsecond, my floor is way lower than i thought. i survived a "
         "year on rice and eggs and cheap coffee and i didn't die, i got scared but i didn't die. once you know your "
         "floor, most threats stop working on you.")
TRACE = [
    "profile: Mara Ellison (61 chunks, sha ea2a2d0c); digest 1607 chars; history {turns} turns",
    "router: about_me (3.39 s)",
    "rewrite: skipped (no history)",
    "retrieval[nomic] k=5: Interview/T-004a 0.859, Interview/T-004b 0.767, Interview/T-003 0.729, Decisions/D-01 "
    "0.688, Life events/The year i was fully broke 0.685 (2.76 s)",
    "voice: stheno_q4 = l3-8b-stheno-v3.2 on lms, temperature 1.0",
]
MODE = {"wait": 0.0, "pause": 0.0, "hint": False, "error": False}


def _boom(*_a, **_k):
    raise AssertionError("ask_states.py: a model call was attempted")


def fake_turn(message, history, *, use_q8=False, temperature=1.0, use_checker=False, condition="interview"):
    """Scripted stand-in for twin.pipelines.ask.ask_turn: same event kinds, recorded run-8 text, timed by MODE."""
    def ev(kind, text="", data=None):
        return {"kind": kind, "text": text, "data": data or {}}
    for line in TRACE[:1]:
        yield ev("trace", line.format(turns=len(history or [])))
    if MODE["hint"]:
        yield ev("trace", "router: tool (1.12 s)")
        yield ev("hint", "This looks like a job for a tool (time, a calculation, or drafting a message). "
                         "The Act tab can actually run it; answering in voice anyway.", {"intent": "tool"})
    else:
        for line in TRACE[1:4]:
            yield ev("trace", line)
    yield ev("trace", TRACE[4])
    time.sleep(MODE["wait"])                       # the voice model loading: no token yet
    words = REPLY.split(" ")
    half = len(words) // 2
    for i, w in enumerate(words):
        if MODE["error"] and i == half:
            raise RuntimeError("LM Studio is down: connection refused on 127.0.0.1:1234")
        if i == half:
            time.sleep(MODE["pause"])              # mid-reply pause for the streaming screenshot
        yield ev("token", ("" if i == 0 else " ") + w)
        time.sleep(0.01)
    yield ev("trace", "voice: 120 pieces, 598 chars raw, 598 cleaned (6.51 s)")
    if use_checker:
        data = {"consistent": False, "unsupported_claims": ["worked twelve hour days for free"], "contradictions": []}
        yield ev("checker", "inconsistent: 1 unsupported, 0 contradictions", data)
        yield ev("trace", "checker: qwen25 = qwen2.5:7b, 1 unsupported, 0 contradictions (4.10 s)")
    yield ev("trace", "total 12.99 s")
    yield ev("done", REPLY, {})


def get_text(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.read().decode("utf-8", "replace")
    except OSError as e:
        return f"unreachable: {e}"


class Page:
    def __init__(self, ws):
        self.ws = ws

    def js(self, expr: str):
        res = self.ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return res.get("result", {}).get("value")

    def wait_for(self, expr: str, timeout: float = 40.0, step: float = 0.25) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.js(expr):
                return True
            time.sleep(step)
        return False

    def viewport(self, width: int, height: int):
        self.ws.call("Emulation.setDeviceMetricsOverride",
                     {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

    def shot(self, path: Path, width: int, height: int, full: bool = True):
        if full:
            h = int(self.js("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)") or height)
            self.viewport(width, max(height, min(h, 4000)))
            time.sleep(0.6)
        data = self.ws.call("Page.captureScreenshot", {"format": "png"})["data"]
        path.write_bytes(base64.b64decode(data))
        if full:
            self.viewport(width, height)
            time.sleep(0.3)
        print(f"  shot {path.name} ({path.stat().st_size} bytes)")


def send(page: Page, text: str):
    page.js("(() => { const ta = document.querySelector('#tab-ask #ask-compose textarea');"
            f" ta.value = {json.dumps(text)}; ta.dispatchEvent(new Event('input', {{bubbles: true}})); return true; }})()")
    time.sleep(0.4)
    page.js("document.querySelector('#tab-ask #ask-send').click()")


TRACE_DONE = "(document.querySelector('#tab-ask #ask-trace') || {}).textContent?.includes('total 12.99') === true"
NO_PENDING = "!document.querySelector('#tab-ask [aria-label=\"Loading response\"]')"


def run_width(page: Page, out: Path, theme: str, width: int, port: int, dump: bool, results: dict):
    height = 1000 if width >= 1000 else 900
    page.viewport(width, height)
    page.ws.events.clear()
    page.ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/?tab=ask&__theme={theme}&nomotion=1"})
    page.ws.wait_event("Page.loadEventFired", timeout=45)
    page.wait_for("!!document.querySelector('#tab-ask #ask-send')", timeout=30)
    time.sleep(4)
    tag = f"{theme}_{width}_ask"
    page.shot(out / f"{tag}_empty.png", width, height)

    slow = width >= 1000
    MODE.update(wait=4.0 if slow else 0.0, pause=6.0 if slow else 0.0, hint=False, error=False)
    send(page, "What did you learn from quitting the agency job?")
    if slow:
        time.sleep(2.0)
        page.shot(out / f"{tag}_waiting.png", width, height, full=False)
        time.sleep(4.5)
        page.shot(out / f"{tag}_streaming.png", width, height, full=False)
    page.wait_for(TRACE_DONE, timeout=40)
    time.sleep(1.0)

    # a follow-up with the hint and the checker panel, then open Trace
    page.js("document.querySelector('#tab-ask #ask-checker-toggle input[type=checkbox]').click()")
    MODE.update(wait=0.0, pause=0.0, hint=True, error=False)
    page.js("(() => { const t = document.querySelector('#tab-ask #ask-trace'); if (t) t.textContent = ''; })()")
    send(page, "and what's 17% of 240?")
    page.wait_for(TRACE_DONE, timeout=40)
    page.wait_for(NO_PENDING, timeout=10)
    time.sleep(1.0)
    page.js("document.querySelector('#tab-ask #ask-trace-panel > button').click()")
    time.sleep(1.2)
    page.js("window.scrollTo(0, 0)")
    page.shot(out / f"{tag}_done.png", width, height)
    m = page.js("({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})") or {}
    results.setdefault("scroll", {})[f"{theme}_{width}_done"] = m
    if dump:
        (out / f"dom_{theme}_{width}.html").write_text(page.js("document.documentElement.outerHTML") or "",
                                                         encoding="utf-8")

    # inline error: Clear, untick the checker, send a turn that fails half way
    page.js("document.querySelector('#tab-ask #ask-clear').click()")
    time.sleep(1.5)
    page.js("document.querySelector('#tab-ask #ask-checker-toggle input[type=checkbox]').click()")
    MODE.update(wait=0.0, pause=0.0, hint=False, error=True)
    send(page, "What did you learn from quitting the agency job?")
    page.wait_for("(document.querySelector('#tab-ask #ask-trace') || {}).textContent?.includes('error: RuntimeError')"
                  " === true", timeout=40)
    page.wait_for(NO_PENDING, timeout=10)
    time.sleep(1.5)
    page.shot(out / f"{tag}_error.png", width, height)
    m = page.js("({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})") or {}
    results["scroll"][f"{theme}_{width}_error"] = m
    page.js("document.querySelector('#tab-ask #ask-clear').click()")
    time.sleep(1.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=7872)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--widths", default="1440,400")
    ap.add_argument("--dump-dom", action="store_true")
    a = ap.parse_args()
    if not 7871 <= a.port <= 7879:
        print("refusing: use a UI port 7871-7879 (never the demo ports 7861-7870)")
        return 2
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", a.port)) == 0:
            print(f"refusing: port {a.port} already has a listener")
            return 3
    out = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out.mkdir(parents=True, exist_ok=True)
    results: dict = {"port": a.port, "api_ps_before": get_text("http://127.0.0.1:11434/api/ps")}

    from twin import clients
    from twin.gpu import MANAGER
    from twin.pipelines import ask as ask_pipeline
    from twin.ui import frame, theme as theme_mod

    for obj, names in ((clients.ollama, ("chat", "embed", "warm", "stop")), (clients.lms, ("chat", "embed", "unload_all"))):
        for n in names:
            if hasattr(obj, n):
                setattr(obj, n, _boom)
    MANAGER.warm = _boom
    ask_pipeline.ask_turn = fake_turn

    demo = frame.build_app()
    demo.queue(default_concurrency_limit=1)
    demo.launch(server_name="127.0.0.1", server_port=a.port, inbrowser=False, show_error=True, js=frame.TAB_JS,
                theme=theme_mod.build_theme(), css=theme_mod.css_text() or None, prevent_thread_lock=True, quiet=True)
    print(f"app up on {a.port} (in-process, TWIN_NO_WARM=1, ask_turn scripted)")

    dport = cdp_shot.free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_ask_states_{a.port}_")
    chrome = subprocess.Popen([cdp_shot.find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                               "--no-first-run", "--no-default-browser-check", f"--remote-debugging-port={dport}",
                               f"--user-data-dir={profile}", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws, rc = None, 0
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
        ws = cdp_shot.WebSocket(target["webSocketDebuggerUrl"], timeout=90)
        ws.call("Page.enable")
        page = Page(ws)
        for theme in [t.strip() for t in a.themes.split(",") if t.strip()]:
            for width in [int(w) for w in a.widths.split(",") if w.strip()]:
                print(f"{theme} {width}px")
                run_width(page, out, theme, width, a.port, a.dump_dom, results)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {type(e).__name__}: {e}")
        rc = 1
    finally:
        if ws is not None:
            ws.close()
        try:
            browser = cdp_shot.WebSocket(cdp_shot.get_json(f"http://127.0.0.1:{dport}/json/version")["webSocketDebuggerUrl"],
                                         timeout=5)
            browser.call("Browser.close", timeout=5)
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)
        demo.close()
        time.sleep(1.0)
        with socket.socket() as s:
            results["port_free_after"] = s.connect_ex(("127.0.0.1", a.port)) != 0
        results["api_ps_after"] = get_text("http://127.0.0.1:11434/api/ps")
        (out / "states.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(json.dumps(results, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
