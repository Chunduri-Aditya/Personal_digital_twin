"""P4 decide lane helper (no GPU, no model call; run as a file from the project root).

Launches the real app layout (twin.ui.frame.build_app with app.py's queue, theme, css and js) on a UI port with one
extra, harness-only page-load event that fills the Decide tab with a recorded result, so headless Chrome can capture
the verdict card, the confidence meter (drawn by the tab's real private JSON.change hook), the raw result and the
quote card without ever calling /decide_b1, /decide_b2 or /say_it. The markdown comes from
twin.pipelines.decide.render_result_markdown (pure; it reads decision titles from the profile on disk) or from
twin.ui.state._err_md. TWIN_NO_WARM=1 is forced, so no tab select or heartbeat loads anything.

States:
  verdict  DEMO.md Appendix B2.1 run 1 (Verdict NO, 0.95, five reasons, eight cited decisions) and its say_it line
  b2       a choice with one uncited reference and an empty In my voice box
  error    the pipeline's early "situation is empty" result and the say_it text it produces
  crash    a handler exception line (the "**Error:** `Type: message`" form)
  loading  the verdict fill, held back 60 s, so Gradio's pending overlay (and queue position) shows on the card
  empty    no fill (the tab as it opens)
Usage: python scripts/dev/finish/lane_decide_preview.py --port 7873 --state verdict
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ["TWIN_NO_WARM"] = "1"
os.environ.setdefault("PYTHONUTF8", "1")
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from twin.pipelines import decide  # noqa: E402
from twin.ui import frame, state  # noqa: E402
from twin.ui import theme as theme_mod  # noqa: E402

SITUATION = ("A former agency client offers me a three-month contract at double my usual rate, but it means pausing "
             "my own product work and going back into their office three days a week. Should I take it?")
REASONS = [
    "the contract would mean pausing my own product work, which is a core part of my creative output and personal "
    "fulfillment",
    "going back into an office environment feels like a step back from the autonomy and flexibility i value",
    "even though the rate is double, the trade-off with my time and creative freedom is too high",
    "i’ve made decisions in the past that prioritize my craft and independence over short-term financial gains, "
    "like raising my rates and turning down the crypto client",
    "the digest highlights that i value my craft over external validation and that i need trust and clear briefs to "
    "thrive, which this contract might compromise",
]
CITED = ["D-01", "D-02", "D-08", "D-10", "D-12", "D-15", "D-04", "D-07"]
CHANGE = ("if the contract included a clear agreement to maintain my creative freedom and allowed me to continue my "
          "product work without conflict")
SAY_RUN1 = ("nope, not gonna do it \U0001F643 double rate aside, giving up my personal project time and office life "
            "feels like a step back for me right now. i value freedom & autonomy too much to trade that for any amt of "
            "$$, tbh. maybe in the future but rn, gotta prioritize staying true to myself as an artist \U0001F62D")
CHUNKS = [f"preview-chunk-{i:02d}" for i in range(1, 13)]


def fill_for(name: str):
    """(markdown, raw result, state, In my voice text) for a preview state."""
    base = {"situation": SITUATION, "model": "qwen3-8b-8k", "chunks": [], "raw": "(recorded preview, no model call)",
            "error": None, "attempts": 1, "condition": "interview", "uncited": []}
    if name == "verdict":
        r = {**base, "kind": "b1", "verdict": "no", "confidence": 0.95, "reasons": REASONS, "cited_decisions": CITED,
             "what_would_change_my_mind": CHANGE, "timing_ms": 12029.0, "chunk_ids": CHUNKS}
        return decide.render_result_markdown(r), r, r, SAY_RUN1
    if name == "b2":
        r = {**base, "kind": "b2", "option_a": "Take the three-month contract",
             "option_b": "Keep my own product work going", "choice": "B", "confidence": 0.7,
             "reasons": REASONS[:3], "cited_decisions": ["D-01", "D-08"], "uncited": ["D-99"],
             "tradeoff": "double the rate for three months against the momentum of my own product",
             "timing_ms": 9420.0, "chunk_ids": CHUNKS}
        return decide.render_result_markdown(r), r, r, ""
    if name == "error":
        r = {**base, "kind": "b1", "situation": "", "error": "situation is empty", "attempts": 0, "timing_ms": 0.2,
             "chunk_ids": [], "confidence": 0.0, "reasons": [], "cited_decisions": [], "verdict": None,
             "what_would_change_my_mind": ""}
        return decide.render_result_markdown(r), r, r, f"(nothing to say: {r['error']})"
    if name == "crash":
        e = ConnectionError("[WinError 10061] No connection could be made because the target machine actively "
                            "refused it")
        return state._err_md(e), {"error": state._err_text(e)}, None, ""
    raise ValueError(name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--state", choices=("verdict", "b2", "error", "crash", "loading", "empty"), default="verdict")
    a = ap.parse_args()
    if not 7871 <= a.port <= 7879:
        print(f"refusing port {a.port}: use a UI port 7871-7879")
        return 2
    demo = frame.build_app()
    parts = demo.twin_parts["decide"]
    if a.state != "empty":
        values = fill_for("verdict" if a.state == "loading" else a.state)

        def fill():
            if a.state == "loading":
                time.sleep(60)   # stands in for a model load; nothing is loaded
            return values

        with demo:
            demo.load(fill, inputs=None, outputs=[parts["md"], parts["json"], parts["state"], parts["say_out"]],
                      api_name=False)
    demo.queue(default_concurrency_limit=1)
    theme = theme_mod.build_theme()
    css = theme_mod.css_text() or None
    print(f"[preview] decide state={a.state} port={a.port} TWIN_NO_WARM={os.environ['TWIN_NO_WARM']}", flush=True)
    demo.launch(server_name="127.0.0.1", server_port=a.port, inbrowser=False, show_error=True, js=frame.TAB_JS,
                theme=theme, css=css)
    return 0


if __name__ == "__main__":
    sys.exit(main())
