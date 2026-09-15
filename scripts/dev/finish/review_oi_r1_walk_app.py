"""Review r1 of lane onboarding_items (docs/PLAN_FINISH.md P4): a model-free Gradio page with two gr.Walkthrough copies
of the Onboarding stepper, to tell Gradio's own step-click behaviour apart from static/tabs/onboarding.css.

The first copy has no lane ids, so no lane CSS reaches it; the second sits under #twin-tabs > #tab-onboarding >
#onboarding-walkthrough with static/twin.css and static/tabs/onboarding.css loaded. No model, no project data, no
project module import. Run only through scripts/dev/finish/review_oi_r1_walk_harness.ps1 (boots, probes, stops).
  python scripts/dev/finish/review_oi_r1_walk_app.py --port 7876 --selected 1"""
import argparse
import inspect
from pathlib import Path

import gradio as gr

ROOT = Path(__file__).resolve().parents[3]
LABELS = ["1. Run the interview", "2. Save the profile and transcript, then redact", "3. Rebuild the index",
          "4. Answer the self-report items"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--selected", type=int, default=0)
    a = ap.parse_args()
    if not 7871 <= a.port <= 7879:
        raise SystemExit("UI ports 7871-7879 only")
    css = ((ROOT / "static" / "twin.css").read_text(encoding="utf-8") + "\n"
           + (ROOT / "static" / "tabs" / "onboarding.css").read_text(encoding="utf-8"))
    launch_kw, blocks_kw = {}, {}
    (launch_kw if "css" in inspect.signature(gr.Blocks.launch).parameters else blocks_kw)["css"] = css
    print(f"gradio {gr.__version__}; css passed to {'launch' if launch_kw else 'Blocks'}", flush=True)
    with gr.Blocks(**blocks_kw) as demo:
        gr.Markdown("plain copy (no lane ids)")
        with gr.Walkthrough(selected=a.selected, elem_id="plain-walkthrough"):
            for i, lab in enumerate(LABELS):
                with gr.Step(lab, id=i):
                    gr.Markdown(f"plain panel {i + 1}")
        with gr.Tabs(elem_id="twin-tabs"):
            with gr.Tab("Onboarding", id="onboarding", elem_id="tab-onboarding"):
                with gr.Walkthrough(selected=a.selected, elem_id="onboarding-walkthrough"):
                    for i, lab in enumerate(LABELS):
                        with gr.Step(lab, id=i):
                            gr.Markdown(f"styled panel {i + 1}")
    demo.launch(server_name="127.0.0.1", server_port=a.port, **launch_kw)


if __name__ == "__main__":
    main()
