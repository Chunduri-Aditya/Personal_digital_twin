"""Act tab: hermes3 tool loop and the Stheno polish (``/act``, ``/polish``)."""
from __future__ import annotations

import gradio as gr

from twin.pipelines import act
from twin.ui import state


def act_run_handler(request):
    """hermes3 tool loop -> (answer, trace markdown)."""
    try:
        result = act.run_agent(request or "")
        return result.get("answer", ""), act.format_trace_markdown(result.get("trace") or [])
    except Exception as e:  # noqa: BLE001
        state._log_exc("run_agent")
        return state._err_text(e), state._err_md(e)


def act_polish_handler(text):
    """Rewrite the answer in voice with Stheno."""
    try:
        return act.polish(text or "")
    except Exception as e:  # noqa: BLE001
        state._log_exc("polish")
        return state._err_text(e)


def build(ctx) -> dict:
    """Render the Act tab and wire /act and /polish.

    Layout and classes only (docs/PLAN_FINISH.md P4; styled by static/tabs/act.css):
    - the request and Run share one sheet;
    - the Answer card is the raised result, with Polish with Stheno under it as the secondary action, beside the
      Polished quote card;
    - the Trace accordion follows, and its Markdown renders as step cards.
    The card classes sit on a gr.Column around each Textbox, because Gradio's form container strips a Textbox
    block's own border, radius and shadow. Both result columns are plain, so the card padding doesn't widen one of
    them. Labels, the placeholder, api_names, queues, inputs and outputs are as before."""
    with gr.Tab("Act", id="act", elem_id="tab-act") as tab:
        with gr.Column(elem_id="act-compose", elem_classes=["twin-panel"]):
            act_request = gr.Textbox(label="Request", lines=2, elem_id="act-request",
                                     placeholder="What time is it and what's 17% of 240?")
            with gr.Row(elem_classes=["twin-actions"]):
                act_run_btn = gr.Button("Run", variant="primary", scale=0, elem_id="act-run")
        with gr.Row(elem_id="act-results", elem_classes=["twin-split"]):
            with gr.Column(min_width=320):
                with gr.Column(elem_id="act-answer-card", elem_classes=["twin-card", "twin-result", "act-answer"]):
                    act_answer = gr.Textbox(label="Answer", lines=6, elem_id="act-answer")
                with gr.Row(elem_classes=["twin-actions"]):
                    act_polish_btn = gr.Button("Polish with Stheno", scale=0, elem_id="act-polish")
            with gr.Column(min_width=320):
                with gr.Column(elem_id="act-polished-card", elem_classes=["quote-card", "act-polished"]):
                    act_polished = gr.Textbox(label="Polished", lines=4, elem_id="act-polished")
        with gr.Accordion("Trace", open=False, elem_id="act-trace-accordion", elem_classes=["act-trace-accordion"]):
            act_trace = gr.Markdown("_(no trace)_", elem_id="act-trace", elem_classes=["trace", "act-trace"])

    act_run_btn.click(act_run_handler, inputs=[act_request], outputs=[act_answer, act_trace],
                      api_name="act", concurrency_id="gpu")
    act_polish_btn.click(act_polish_handler, inputs=[act_answer], outputs=[act_polished],
                         api_name="polish", concurrency_id="gpu")
    return {"tab": tab, "request": act_request, "run_btn": act_run_btn, "answer": act_answer,
            "polish_btn": act_polish_btn, "polished": act_polished, "trace": act_trace}
