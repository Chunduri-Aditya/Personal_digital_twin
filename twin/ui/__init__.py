"""Gradio UI package: ``frame`` (header, status strip, tab shell, page-load hook) plus one module per tab.

``app.py`` is only the assembler; every model call still lives in ``twin.pipelines.*`` and the GPU sequencing
in ``twin.gpu``. Shared state (the loaded profile, error helpers) is in ``twin.ui.state`` and is always read
through the module (``state.PROFILE``), never imported by value.
"""
