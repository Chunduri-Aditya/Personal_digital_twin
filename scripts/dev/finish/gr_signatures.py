"""Print the constructor signatures of the Gradio layout pieces the P3 frame restyle uses (read-only helper)."""
import inspect

import gradio as gr

for cls in (gr.HTML, gr.Markdown, gr.Column, gr.Row, gr.Group, gr.Sidebar, gr.Tabs):
    params = inspect.signature(cls.__init__).parameters
    print(cls.__name__ + ":", ", ".join(n for n in params if n != "self"))
