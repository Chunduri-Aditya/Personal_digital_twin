"""Decide lane (P4) read-only helper: print the Gradio constructor and event signatures the Decide restyle relies on."""
import inspect

import gradio as gr

print("gradio", gr.__version__)
for cls in (gr.HTML, gr.JSON, gr.Textbox, gr.Button, gr.Column, gr.Row, gr.Group, gr.Markdown):
    params = inspect.signature(cls.__init__).parameters
    print(cls.__name__ + ":", ", ".join(f"{n}={p.default!r}" for n, p in params.items()
                                         if n != "self" and n in ("value", "padding", "container", "min_height",
                                                                   "max_height", "show_label", "scale", "min_width",
                                                                   "variant", "size", "equal_height", "open",
                                                                   "height", "elem_id", "elem_classes", "lines",
                                                                   "max_lines", "interactive", "show_copy_button",
                                                                   "buttons", "autoscroll")))
    print("   all:", ", ".join(n for n in params if n != "self"))
print("JSON events:", [e if isinstance(e, str) else getattr(e, "event_name", e) for e in gr.JSON.EVENTS])
change = gr.JSON.change
print("JSON.change params:", ", ".join(f"{n}={p.default!r}" for n, p in inspect.signature(change).parameters.items()
                                      if n in ("api_name", "api_visibility", "show_progress", "queue",
                                               "concurrency_limit", "concurrency_id", "trigger_mode")))
