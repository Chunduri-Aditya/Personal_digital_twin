"""Digital twin: Gradio UI assembler (eight tabs: Onboarding, Ask, Decide, Act, See, Items, Eval, Status).

The frame, the tab modules and the endpoint list (every ``api_name``) live in ``twin/ui`` (see
``twin/ui/frame.py``); every model call lives in ``twin.pipelines.*`` and the GPU sequencing in ``twin.gpu``.
This file only picks a port, starts the heartbeat, builds the app and launches it. Run from the project root::

    $env:PYTHONUTF8=1; $env:GRADIO_ANALYTICS_ENABLED="False"; python app.py --port 7861

``--port`` is the first port tried; the next 9 are probed when it is busy (Gradio itself scans only when no port
is pinned). Switches: ``TWIN_NO_WARM=1`` (no pre-warm, no heartbeat thread, /warm and /rebuild_* skip) and
``TWIN_THEME=light|dark``. The theme and CSS come from ``twin.ui.theme`` when that module is available;
otherwise the app launches with Gradio's defaults.
``PROFILE``, ``PROFILE_ERROR`` and ``load_app_profile`` are re-exported from ``twin.ui.state`` for compatibility
(the two names track the state module at access time).
"""
from __future__ import annotations

import argparse
import socket
import sys

from twin.gpu import MANAGER
from twin.ui import state as _state
from twin.ui.frame import TAB_IDS, TAB_JS, build_app  # noqa: F401  (re-exported)

PORT_TRIES = 10

load_app_profile = _state.load_app_profile


def __getattr__(name: str):
    """PROFILE / PROFILE_ERROR read twin.ui.state at access time (load_app_profile() rebinds them there)."""
    if name in ("PROFILE", "PROFILE_ERROR"):
        return getattr(_state, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def pick_port(host: str, first: int, tries: int = PORT_TRIES) -> int:
    """First free port in [first, first + tries): Gradio scans ports only when server_port is None, so a pinned
    busy port would otherwise raise OSError('Cannot find empty port in range: 7861-7861')."""
    for port in range(first, first + max(1, tries)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"no free port in {first}-{first + tries - 1} on {host}")


def _theme_and_css():
    """(theme, css) from twin.ui.theme when it imports and builds cleanly; (None, None) otherwise."""
    try:
        from twin.ui import theme as theme_mod
        theme = theme_mod.build_theme()
        css = theme_mod.css_text() or None
        return theme, css
    except Exception as e:  # noqa: BLE001 - the theme module is optional
        print(f"[app] theme unavailable ({type(e).__name__}: {e}); launching with Gradio defaults",
              file=sys.stderr, flush=True)
        return None, None


def main(argv=None) -> int:
    """Parse --port/--host, start the heartbeat, build and launch the app on the first free port from --port."""
    ap = argparse.ArgumentParser(prog="python app.py", description="Digital twin Gradio UI")
    ap.add_argument("--port", type=int, default=7861, help="first port to try (the next 9 are probed if busy)")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)

    port = pick_port(args.host, args.port)
    if port != args.port:
        print(f"[app] port {args.port} is busy; using {port}", flush=True)
    print(f"[app] serving on http://{args.host}:{port}", flush=True)
    if _state.no_warm():
        print("[app] TWIN_NO_WARM=1: no heartbeat, no pre-warm, /warm and /rebuild_* skip", flush=True)
    MANAGER.start_heartbeat()          # active tab starts as None; the page-load hook marks Ask active (no load)
    demo = build_app()
    demo.queue(default_concurrency_limit=1)
    theme, css = _theme_and_css()
    demo.launch(server_name=args.host, server_port=port, inbrowser=False, show_error=True, js=TAB_JS,
                theme=theme, css=css)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
