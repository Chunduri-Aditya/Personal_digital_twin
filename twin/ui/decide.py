"""Decide tab: B1 "would I do it?", B2 "A or B?" and "say it in my voice" (``/decide_b1``, ``/decide_b2``,
``/say_it``). The condition dropdown (docs/PLAN_UNIFIED.md 3.4) is the LAST input of /decide_b1 and /decide_b2,
so phase-1 positional calls still work; ``/say_it`` follows the condition stored in the result.

Layout (docs/PLAN_FINISH.md P4; shared classes in static/twin.css, tab rules in static/tabs/decide.css):
- the question sheet ``#decide-question``: Situation beside Condition, then **B1**, the tab's one primary action;
- the options sheet ``#decide-options``: Option A and Option B, then **B2** (secondary);
- the result row: the raised verdict card ``#decide-verdict`` (the confidence meter and the result markdown) across
  the whole row;
- **Say it in my voice**, then the **In my voice** box on the quote card ``#decide-say-card``;
- the **Raw result** JSON behind the closed disclosure ``#decide-raw-panel`` (Nocturne sheet, docs/design/tokens.md
  section 5).
Labels, placeholders, defaults, api_names, queues, event inputs and outputs and every handler return are unchanged.
The meter is a private, model-less hook that redraws from the decision the endpoint already returned."""
from __future__ import annotations

import gradio as gr

from twin import prompts
from twin.pipelines import decide
from twin.ui import state

CONDITION_CHOICES = [(c, c) for c in prompts.CONDITIONS]


def _condition(value) -> str:
    return str(value or prompts.DEFAULT_CONDITION)


def decide_b1_handler(situation, condition=prompts.DEFAULT_CONDITION):
    """B1: would I do it? -> (markdown, raw json, state)."""
    try:
        result = decide.decide_b1(situation or "", condition=_condition(condition))
        return decide.render_result_markdown(result), result, result
    except Exception as e:  # noqa: BLE001
        state._log_exc("decide_b1")
        return state._err_md(e), {"error": state._err_text(e)}, None


def decide_b2_handler(situation, option_a, option_b, condition=prompts.DEFAULT_CONDITION):
    """B2: A or B? -> (markdown, raw json, state)."""
    try:
        result = decide.decide_b2(situation or "", option_a or "", option_b or "", condition=_condition(condition))
        return decide.render_result_markdown(result), result, result
    except Exception as e:  # noqa: BLE001
        state._log_exc("decide_b2")
        return state._err_md(e), {"error": state._err_text(e)}, None


def say_it_handler(st):
    """Render the last decision as one message in the twin's voice (Stheno loads only now)."""
    if not isinstance(st, dict):
        return "(run B1 or B2 first)"
    try:
        return decide.say_it(st)
    except Exception as e:  # noqa: BLE001
        state._log_exc("say_it")
        return state._err_text(e)


def confidence_html(st) -> str:
    """The confidence meter for the verdict card (frame contract ``.confidence-meter``), drawn from the decision
    result /decide_b1 or /decide_b2 already returned. '' when there is no result, the result carries an error, or it
    holds no verdict (B1) or choice (B2). The value uses the markdown's own clamp and rounding, so it always equals
    the card's "Confidence: x.xx" line; the meter is aria-hidden because that line already says it."""
    if not isinstance(st, dict) or st.get("error") or st.get("confidence") is None:
        return ""
    decided = st.get("choice") in ("A", "B") if st.get("kind") == "b2" else st.get("verdict") in ("yes", "no")
    if not decided:
        return ""
    value = decide._clamp_confidence(st.get("confidence"))
    return ('<div class="confidence-meter" aria-hidden="true">'
            f'<span class="track"><span class="fill" style="width: {value * 100:.0f}%"></span></span>'
            f'<span class="value">{value:.2f}</span></div>')


def confidence_handler(st) -> str:
    """Private meter hook: never raises, so a failed redraw can't put an error toast on screen mid-demo."""
    try:
        return confidence_html(st)
    except Exception:  # noqa: BLE001
        state._log_exc("decide confidence meter")
        return ""


def build(ctx) -> dict:
    """Render the Decide tab and wire /decide_b1, /decide_b2, /say_it and the private confidence-meter hook."""
    with gr.Tab("Decide", id="decide", elem_id="tab-decide") as tab:
        # The question sheet: the situation beside its condition, then B1, the tab's one primary action.
        with gr.Column(elem_id="decide-question", elem_classes=["twin-panel"]):
            with gr.Row(elem_id="decide-question-fields", elem_classes=["twin-split"]):
                situation = gr.Textbox(label="Situation", lines=3,
                                       placeholder="Describe the situation as if you were texting me about it...",
                                       elem_id="decide-situation", scale=3, min_width=320)
                condition = gr.Dropdown(choices=CONDITION_CHOICES, value=prompts.DEFAULT_CONDITION, label="Condition",
                                        elem_id="decide-condition",
                                        info="interview: retrieved context + digest; persona: identity + digest; "
                                             "demographic: identity only", scale=2, min_width=240)
            with gr.Row(elem_classes=["twin-actions"]):
                b1_btn = gr.Button("B1: Would I do it?", variant="primary", elem_id="decide-b1", scale=0)
        # The options sheet: A or B about the same situation. B2 is secondary, so B1 stays the one primary action.
        with gr.Column(elem_id="decide-options", elem_classes=["twin-panel"]):
            with gr.Row(elem_id="decide-option-fields", elem_classes=["twin-split"]):
                option_a = gr.Textbox(label="Option A", lines=2, elem_id="decide-option-a")
                option_b = gr.Textbox(label="Option B", lines=2, elem_id="decide-option-b")
            with gr.Row(elem_classes=["twin-actions"]):
                b2_btn = gr.Button("B2: A or B?", elem_id="decide-b2", scale=0)
        # The result: the raised verdict card takes the whole row (meter and result markdown share it).
        with gr.Row(elem_id="decide-result-row"):
            with gr.Column(min_width=320, elem_id="decide-verdict", elem_classes=["verdict-card"]):
                confidence = gr.HTML("", elem_id="decide-confidence")
                decide_md = gr.Markdown("_(no decision yet)_", elem_id="decide-result")
        decide_state = gr.State(None)
        with gr.Row(elem_classes=["twin-actions"]):
            say_btn = gr.Button("Say it in my voice", elem_id="decide-say-btn", scale=0)
        # The quote card is the column: Gradio wraps a Textbox in a form that drops a block's own border and shadow.
        with gr.Column(elem_id="decide-say-card", elem_classes=["quote-card"]):
            say_out = gr.Textbox(label="In my voice", lines=2, elem_id="decide-say")
        # The raw result is there to check, not to read out: behind a closed disclosure at the end of the tab.
        with gr.Accordion("Raw result", open=False, elem_id="decide-raw-panel"):
            decide_json = gr.JSON(label="Raw result", show_label=False, elem_id="decide-raw")

    b1_btn.click(decide_b1_handler, inputs=[situation, condition], outputs=[decide_md, decide_json, decide_state],
                 api_name="decide_b1", concurrency_id="gpu")
    b2_btn.click(decide_b2_handler, inputs=[situation, option_a, option_b, condition],
                 outputs=[decide_md, decide_json, decide_state], api_name="decide_b2", concurrency_id="gpu")
    say_btn.click(say_it_handler, inputs=[decide_state], outputs=[say_out], api_name="say_it",
                  concurrency_id="gpu")
    # Private and model-less, in its own queue slot (never "gpu"): when the result markdown changes, redraw the meter
    # from the decision in the session state. It keys on the markdown, which is always on screen, not on the raw JSON
    # inside the closed disclosure. gradio_client calls (scripts/demo_rehearse.py) never fire browser events.
    decide_md.change(confidence_handler, inputs=[decide_state], outputs=[confidence], api_name=False,
                     show_progress="hidden")
    return {"tab": tab, "situation": situation, "condition": condition, "b1_btn": b1_btn, "option_a": option_a,
            "option_b": option_b, "b2_btn": b2_btn, "md": decide_md, "json": decide_json, "state": decide_state,
            "say_btn": say_btn, "say_out": say_out, "confidence": confidence}
