"""Headless Chrome through the DevTools protocol, standard library only (run as a file).

Why: a Chrome --headless=new window can't be narrower than 500 px, so scripts/screenshot_tabs.ps1 -Width 400
renders a 500 px layout and crops the PNG to 400 (innerWidth reads 500). This tool sets a true CSS viewport with
Emulation.setDeviceMetricsOverride, opens each tab through the ?tab= deep link, waits, measures
document.documentElement.scrollWidth and window.innerWidth, lists elements that overflow the viewport, and saves
a screenshot named <theme>_<width>_<tab>.png. It never calls a model itself; point it only at an app running with
TWIN_NO_WARM=1 (or accept that each deep link fires that tab's pre-warm).

Usage (project root):
  python scripts/dev/finish/cdp_shot.py --port 7871 --tabs ask[,decide] --theme light --width 400 --height 900
         --out-dir scripts/dev/shots/x [--json scripts/dev/shots/x/measure.json] [--wait 10]
Exit 0 when every tab produced a measurement and a PNG, 1 otherwise, 2 on a setup error.
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

MEASURE_JS = r"""
(() => {
  const iw = window.innerWidth;
  const off = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > iw + 1) {
      off.push({tag: el.tagName.toLowerCase(), id: el.id || '',
                cls: (typeof el.className === 'string' ? el.className : '').slice(0, 80),
                left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width)});
      if (off.length >= 25) break;
    }
  }
  const sel = document.querySelector('button[role="tab"][aria-selected="true"]');
  return {scrollWidth: document.documentElement.scrollWidth, innerWidth: iw,
          bodyScrollWidth: document.body ? document.body.scrollWidth : null,
          selectedTab: sel ? sel.textContent.trim() : null,
          dark: document.body ? document.body.classList.contains('dark') : null,
          title: document.title, overflowing: off};
})()
"""


class WebSocket:
    """Minimal RFC 6455 client: masked text frames out, fragmented and extended-length frames in."""

    def __init__(self, url: str, timeout: float = 60.0):
        rest = url[len("ws://"):]
        hostport, path = rest.split("/", 1)
        host, port = hostport.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            buf += chunk
        head, self.pending = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"websocket handshake failed: {head[:200]!r}")
        self.next_id = 0
        self.events: list[dict] = []

    def _recv_exact(self, n: int) -> bytes:
        while len(self.pending) < n:
            chunk = self.sock.recv(max(65536, n - len(self.pending)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self.pending += chunk
        data, self.pending = self.pending[:n], self.pending[n:]
        return data

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _recv_message(self) -> str:
        parts = []
        while True:
            b1, b2 = self._recv_exact(2)
            fin, opcode, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            if b2 & 0x80:
                mask = self._recv_exact(4)
                data = bytes(x ^ mask[i % 4] for i, x in enumerate(self._recv_exact(n)))
            else:
                data = self._recv_exact(n)
            if opcode == 8:
                raise ConnectionError("websocket closed by the browser")
            if opcode == 9:
                self._send_frame(data, 10)
                continue
            if opcode == 10:
                continue
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8")

    def call(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        self.next_id += 1
        mid = self.next_id
        self._send_frame(json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self._recv_message())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)
        raise TimeoutError(method)

    def wait_event(self, name: str, timeout: float = 45.0) -> dict | None:
        for i, e in enumerate(self.events):
            if e.get("method") == name:
                return self.events.pop(i)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self._recv_message())
            except socket.timeout:
                return None
            if msg.get("method") == name:
                return msg
            self.events.append(msg)
        return None

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def find_chrome() -> str:
    for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"):
        if p.exists():
            return str(p)
    raise FileNotFoundError("no chrome.exe or msedge.exe found")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--tabs", default="ask")
    ap.add_argument("--theme", choices=("light", "dark"), default="light")
    ap.add_argument("--width", type=int, default=400)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--json")
    ap.add_argument("--wait", type=float, default=10.0, help="seconds after the load event before measuring")
    a = ap.parse_args()
    if 7861 <= a.port <= 7870:
        print("refusing ports 7861-7870 (the demo app); use a UI port 7871-7879")
        return 2
    tabs = [t.strip() for t in a.tabs.split(",") if t.strip()]
    out_dir = Path(a.out_dir) if Path(a.out_dir).is_absolute() else ROOT / a.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    dport = free_port()
    profile = tempfile.mkdtemp(prefix=f"twin_cdp_{a.port}_")
    proc = subprocess.Popen([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                             "--no-default-browser-check", f"--remote-debugging-port={dport}",
                             f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results, ok, page = [], True, None
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
        page.call("Emulation.setDeviceMetricsOverride",
                  {"width": a.width, "height": a.height, "deviceScaleFactor": 1, "mobile": False})
        for tab in tabs:
            url = f"http://127.0.0.1:{a.port}/?tab={tab}&__theme={a.theme}&nomotion=1"
            t0 = time.time()
            page.events.clear()
            page.call("Page.navigate", {"url": url})
            loaded = page.wait_event("Page.loadEventFired", timeout=45) is not None
            time.sleep(a.wait)
            value = page.call("Runtime.evaluate", {"expression": MEASURE_JS, "returnByValue": True}).get("result", {}).get("value") or {}
            shot = page.call("Page.captureScreenshot", {"format": "png"})
            png = out_dir / f"{a.theme}_{a.width}_{tab}.png"
            png.write_bytes(base64.b64decode(shot["data"]))
            row = {"tab": tab, "url": url, "load_event": loaded, "seconds": round(time.time() - t0, 1),
                   "png": str(png.relative_to(ROOT)) if str(png).startswith(str(ROOT)) else str(png),
                   "png_bytes": png.stat().st_size, **value}
            results.append(row)
            if value.get("scrollWidth") is None:
                ok = False
            print(f"{tab:<10} {a.theme} {a.width}px: scrollWidth={value.get('scrollWidth')} innerWidth={value.get('innerWidth')} "
                  f"selected={value.get('selectedTab')!r} dark={value.get('dark')} overflowing={len(value.get('overflowing') or [])} "
                  f"-> {row['png']} ({row['png_bytes']} bytes)")
            for o in (value.get("overflowing") or [])[:8]:
                print(f"    overflow: <{o['tag']} id='{o['id']}' class='{o['cls']}'> left={o['left']} right={o['right']} width={o['width']}")
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
    if a.json:
        jp = Path(a.json) if Path(a.json).is_absolute() else ROOT / a.json
        jp.write_text(json.dumps({"port": a.port, "theme": a.theme, "viewport": {"width": a.width, "height": a.height},
                                  "results": results, "ok": ok}, indent=1), encoding="utf-8")
    return 0 if ok and len(results) == len(tabs) else 1


if __name__ == "__main__":
    sys.exit(main())
