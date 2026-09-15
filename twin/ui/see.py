"""See tab: qwen3.5 describes an image, Stheno reacts (``/see``)."""
from __future__ import annotations

import gradio as gr

from twin.pipelines import see
from twin.ui import state


def see_handler(image):
    """qwen3.5 describes, Stheno reacts -> (description, reaction, trace markdown)."""
    if image is None:
        return "", "", "_(upload an image first)_"
    try:
        result = see.see_turn(image)
        return (result.get("description", ""), result.get("reaction", ""),
                state._trace_markdown(list(result.get("trace") or [])))
    except Exception as e:  # noqa: BLE001
        state._log_exc("see_turn")
        return state._err_text(e), "", state._err_md(e)


def build(ctx) -> dict:
    """Render the See tab and wire /see.

    Layout and classes only (docs/PLAN_FINISH.md P4; styled by static/tabs/see.css):
    - the Image drop zone, with Look under it;
    - beside them, the Description (qwen3.5) card and the Reaction (in my voice) quote card;
    - the trace panel below.
    Each card class sits on its own gr.Column around one Textbox, because Gradio's form container strips a Textbox
    block's own border, radius and shadow and joins consecutive Textboxes into one box. Labels, api_name, queue,
    inputs and outputs are as before."""
    with gr.Tab("See", id="see", elem_id="tab-see") as tab:
        with gr.Row(elem_id="see-row", elem_classes=["twin-split"]):
            with gr.Column(min_width=320, elem_id="see-input"):
                see_image = gr.Image(type="pil", label="Image", height=360, elem_id="see-image",
                                     elem_classes=["see-image"])
                with gr.Row(elem_classes=["twin-actions"]):
                    see_btn = gr.Button("Look", variant="primary", scale=0, elem_id="see-look")
            with gr.Column(min_width=320, elem_id="see-output"):
                with gr.Column(elem_id="see-description-card", elem_classes=["twin-card", "see-description"]):
                    see_description = gr.Textbox(label="Description (qwen3.5)", lines=6, elem_id="see-description")
                with gr.Column(elem_id="see-reaction-card", elem_classes=["quote-card", "see-reaction"]):
                    see_reaction = gr.Textbox(label="Reaction (in my voice)", lines=3, elem_id="see-reaction")
        see_trace = gr.Markdown("_(no trace)_", elem_id="see-trace", elem_classes=["trace", "see-trace"])

    see_btn.click(see_handler, inputs=[see_image], outputs=[see_description, see_reaction, see_trace],
                  api_name="see", concurrency_id="gpu")
    return {"tab": tab, "image": see_image, "description": see_description, "reaction": see_reaction,
            "btn": see_btn, "trace": see_trace}
