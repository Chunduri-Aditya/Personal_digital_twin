"""Offline checks for the Act and See restyle (docs/PLAN_FINISH.md P4, lane act_see).

The two tabs keep their labels, placeholder, event wiring and handler returns (the DEMO CONTRACT). They also carry
the elem_ids and classes that static/tabs/act.css and static/tabs/see.css style. Only these two tab modules are
built, inside a bare gr.Blocks: no model, no network, no other tab module."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import gradio as gr
import pytest

from twin.pipelines import act as act_pipeline
from twin.pipelines import see as see_pipeline
from twin.ui import act as act_ui
from twin.ui import see as see_ui

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


@pytest.fixture(scope="module")
def built():
    with gr.Blocks() as demo:
        with gr.Tabs():
            act_parts = act_ui.build(SimpleNamespace())
            see_parts = see_ui.build(SimpleNamespace())
    return demo, act_parts, see_parts


def _fn(demo, api_name):
    fns = [f for f in demo.fns.values() if f.api_name == api_name]
    assert len(fns) == 1, api_name
    return fns[0]


def _ancestors(block) -> list:
    out, cur = [], getattr(block, "parent", None)
    while cur is not None:
        out.append(cur)
        cur = getattr(cur, "parent", None)
    return out


def _nearest(block, kind):
    return next(b for b in _ancestors(block) if isinstance(b, kind))


def _classes(block) -> set[str]:
    return set(block.elem_classes or [])


# ---- the DEMO CONTRACT: labels, placeholder, wiring ---------------------------------------------------------
def test_act_labels_placeholder_and_wiring_unchanged(built):
    demo, p, _ = built
    assert set(p) == {"tab", "request", "run_btn", "answer", "polish_btn", "polished", "trace"}
    assert (p["tab"].label, p["tab"].id, p["tab"].elem_id) == ("Act", "act", "tab-act")
    req = p["request"]
    assert (req.label, req.lines, req.placeholder) == ("Request", 2, "What time is it and what's 17% of 240?")
    assert (p["run_btn"].value, p["run_btn"].variant) == ("Run", "primary")
    assert (p["answer"].label, p["answer"].lines) == ("Answer", 6)
    assert (p["polish_btn"].value, p["polish_btn"].variant) == ("Polish with Stheno", "secondary")
    assert (p["polished"].label, p["polished"].lines) == ("Polished", 4)
    assert p["trace"].value == "_(no trace)_"
    accordion = _nearest(p["trace"], gr.Accordion)
    assert accordion.label == "Trace" and accordion.open is False
    run = _fn(demo, "act")
    assert run.fn is act_ui.act_run_handler and run.concurrency_id == "gpu"
    assert list(run.inputs) == [p["request"]] and list(run.outputs) == [p["answer"], p["trace"]]
    polish = _fn(demo, "polish")
    assert polish.fn is act_ui.act_polish_handler and polish.concurrency_id == "gpu"
    assert list(polish.inputs) == [p["answer"]] and list(polish.outputs) == [p["polished"]]


def test_see_labels_and_wiring_unchanged(built):
    demo, _, p = built
    assert set(p) == {"tab", "image", "description", "reaction", "btn", "trace"}
    assert (p["tab"].label, p["tab"].id, p["tab"].elem_id) == ("See", "see", "tab-see")
    assert (p["image"].label, p["image"].type, p["image"].height) == ("Image", "pil", 360)
    assert (p["description"].label, p["description"].lines) == ("Description (qwen3.5)", 6)
    assert (p["reaction"].label, p["reaction"].lines) == ("Reaction (in my voice)", 3)
    assert (p["btn"].value, p["btn"].variant) == ("Look", "primary")
    assert p["trace"].value == "_(no trace)_"
    look = _fn(demo, "see")
    assert look.fn is see_ui.see_handler and look.concurrency_id == "gpu"
    assert list(look.inputs) == [p["image"]]
    assert list(look.outputs) == [p["description"], p["reaction"], p["trace"]]


# ---- the restyle: ids, classes, layout wrappers ---------------------------------------------------------------
def test_act_restyle_ids_classes_and_layout(built):
    _, p, _ = built
    compose = _nearest(p["request"], gr.Column)
    assert p["request"].elem_id == "act-request"
    assert compose.elem_id == "act-compose" and "twin-panel" in _classes(compose)
    assert compose in _ancestors(p["run_btn"])
    for key, eid in (("run_btn", "act-run"), ("polish_btn", "act-polish")):
        btn = p[key]
        assert btn.elem_id == eid and btn.scale == 0, key
        assert "twin-actions" in _classes(_nearest(btn, gr.Row)), key
    answer_card, polished_card = _nearest(p["answer"], gr.Column), _nearest(p["polished"], gr.Column)
    assert p["answer"].elem_id == "act-answer" and answer_card.elem_id == "act-answer-card"
    assert {"twin-card", "twin-result", "act-answer"} <= _classes(answer_card)
    assert p["polished"].elem_id == "act-polished" and polished_card.elem_id == "act-polished-card"
    assert {"quote-card", "act-polished"} <= _classes(polished_card)
    split = next(b for b in _ancestors(p["answer"]) if isinstance(b, gr.Row) and b.elem_id == "act-results")
    assert "twin-split" in _classes(split)
    left, right = _nearest(answer_card, gr.Column), _nearest(polished_card, gr.Column)
    assert left is not right and split in _ancestors(left) and split in _ancestors(right)
    assert not (_classes(left) | _classes(right))          # plain columns: card padding never widens one side
    assert left in _ancestors(p["polish_btn"])             # Polish sits under the Answer it reads
    accordion = _nearest(p["trace"], gr.Accordion)
    assert accordion.elem_id == "act-trace-accordion" and "act-trace-accordion" in _classes(accordion)
    assert split not in _ancestors(accordion)              # the trace runs full width under the split
    assert p["trace"].elem_id == "act-trace" and {"trace", "act-trace"} <= _classes(p["trace"])


def test_see_restyle_ids_classes_and_layout(built):
    _, _, p = built
    img, btn = p["image"], p["btn"]
    assert img.elem_id == "see-image" and "see-image" in _classes(img)
    assert btn.elem_id == "see-look" and btn.scale == 0
    assert "twin-actions" in _classes(_nearest(btn, gr.Row))
    left = _nearest(img, gr.Column)
    assert left.elem_id == "see-input" and left in _ancestors(btn)   # Look sits under the image it reads
    split = _nearest(left, gr.Row)
    assert split.elem_id == "see-row" and "twin-split" in _classes(split)
    description_card, reaction_card = _nearest(p["description"], gr.Column), _nearest(p["reaction"], gr.Column)
    assert (description_card.elem_id, reaction_card.elem_id) == ("see-description-card", "see-reaction-card")
    assert {"twin-card", "see-description"} <= _classes(description_card)
    assert {"quote-card", "see-reaction"} <= _classes(reaction_card)
    right = _nearest(description_card, gr.Column)
    assert right.elem_id == "see-output" and right is not left and split in _ancestors(right)
    assert right is _nearest(reaction_card, gr.Column)    # two card columns, so two separate form containers
    assert (p["description"].elem_id, p["reaction"].elem_id) == ("see-description", "see-reaction")
    assert p["trace"].elem_id == "see-trace" and {"trace", "see-trace"} <= _classes(p["trace"])
    assert split not in _ancestors(p["trace"])


def test_card_classes_sit_on_columns_not_on_textboxes(built):
    """Gradio wraps a Textbox in a form container whose CSS forces border-width 0, radius 0 and no shadow
    (!important) on the block inside it, so a card class on the Textbox itself would render flat and edgeless."""
    _, act_parts, see_parts = built
    cards = {"twin-card", "twin-result", "quote-card", "twin-panel", "trace"}
    for tb in (act_parts["request"], act_parts["answer"], act_parts["polished"], see_parts["description"],
               see_parts["reaction"]):
        assert not (_classes(tb) & cards), tb.label


def _preludes(css: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [p.strip() for p in re.findall(r"([^{}]+)\{", css)]


@pytest.mark.parametrize("tab,classes", [
    ("act", ("act-answer", "act-polished", "act-trace-accordion", "act-trace")),
    ("see", ("see-image", "see-description", "see-reaction", "see-trace")),
])
def test_partials_style_every_lane_class(tab, classes):
    selectors = " ".join(_preludes((STATIC / "tabs" / f"{tab}.css").read_text(encoding="utf-8")))
    for cls in classes:
        assert re.search(r"\." + re.escape(cls) + r"(?![\w-])", selectors), (tab, cls)


@pytest.mark.parametrize("tab", ["act", "see"])
def test_partials_keep_selector_lists_at_the_top_level(tab):
    """Gradio re-emits custom CSS with a .gradio-container prefix and splits selectors on every comma, including
    commas inside :is()/:where()/:not()/:has(). That silently raises or breaks a rule's specificity, so the partials
    write selector lists only at the top level."""
    for prelude in _preludes((STATIC / "tabs" / f"{tab}.css").read_text(encoding="utf-8")):
        depth = 0
        for ch in prelude:
            depth += {"(": 1, ")": -1}.get(ch, 0)
            assert not (ch == "," and depth > 0), (tab, prelude)


def test_shared_classes_used_here_exist_in_twin_css():
    css = (STATIC / "twin.css").read_text(encoding="utf-8")
    for cls in ("twin-panel", "twin-card", "twin-result", "twin-actions", "twin-split", "quote-card", "trace"):
        assert re.search(r"#twin-tabs \." + re.escape(cls) + r"(?![\w-])", css), cls


# ---- what the handlers return, and the trace shape the step cards rely on -----------------------------------
def _boom(*_a, **_k):
    raise RuntimeError("down")


def test_handlers_return_the_same_values(monkeypatch):
    trace = [{"step": 1, "kind": "tool", "tool": "search_profile", "args": {"query": "q"}, "result": {"results": []}}]
    monkeypatch.setattr(act_pipeline, "run_agent", lambda text: {"answer": "draft", "trace": trace, "steps": 1})
    assert act_ui.act_run_handler("look it up") == ("draft", act_pipeline.format_trace_markdown(trace))
    monkeypatch.setattr(act_pipeline, "run_agent", _boom)
    assert act_ui.act_run_handler("x") == ("Error: RuntimeError: down", "**Error:** `RuntimeError: down`")
    monkeypatch.setattr(act_pipeline, "polish", lambda text: text.upper())
    assert act_ui.act_polish_handler("ok") == "OK"
    monkeypatch.setattr(act_pipeline, "polish", _boom)
    assert act_ui.act_polish_handler("ok") == "Error: RuntimeError: down"
    assert see_ui.see_handler(None) == ("", "", "_(upload an image first)_")
    monkeypatch.setattr(see_pipeline, "see_turn",
                        lambda img: {"description": "d", "reaction": "r", "trace": ["vision m: 1 chars", "total 5 ms"]})
    assert see_ui.see_handler(object()) == ("d", "r", "- vision m: 1 chars\n- total 5 ms")
    monkeypatch.setattr(see_pipeline, "see_turn", _boom)
    assert see_ui.see_handler(object()) == ("Error: RuntimeError: down", "", "**Error:** `RuntimeError: down`")


def test_trace_markdown_shape_the_step_cards_rely_on():
    """static/tabs/act.css paints each "---"-separated entry as a card, gives a "**Step N - tool `x`**" heading its
    tool chip, sets "Arguments:"/"Result:" as labels over fenced JSON, and shows a lone "**Error:** `...`" line as an
    inline error. If this shape changes, revisit those rules."""
    trace = [
        {"step": 1, "kind": "assistant", "content": "", "tool_calls": [{"name": "search_profile",
                                                                        "arguments": {"query": "q"}}]},
        {"step": 1, "kind": "tool", "tool": "search_profile", "args": {"query": "q"}, "result": {"results": []}},
        {"step": 2, "kind": "note", "note": "nudge"},
        {"step": 2, "kind": "assistant", "content": "ok wait", "tool_calls": []},
    ]
    entries = act_pipeline.format_trace_markdown(trace).split("\n\n---\n\n")
    assert len(entries) == 4
    assert entries[0].startswith("**Step 1 - assistant**\n\nRequested tools: `search_profile(")
    assert entries[1].startswith("**Step 1 - tool `search_profile`**\n\nArguments:\n```json\n")
    assert "\n```\n\nResult:\n```json\n" in entries[1]
    assert entries[2] == "**Step 2 - note**\n\n_nudge_"
    assert entries[3] == "**Step 2 - assistant**\n\nok wait"
    assert act_pipeline.format_trace_markdown([]) == "_(no trace)_"
