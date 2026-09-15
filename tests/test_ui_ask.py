"""Offline tests for the restyled Ask tab (docs/PLAN_FINISH.md P4, ask lane).

The DEMO CONTRACT side: every label, placeholder, default, choice, api_name, queue, input and output order and handler
return the demo relies on is unchanged. The restyle side: the new elem_ids and elem_classes, one primary action, the
empty-chat placeholder, the colourless monogram avatar, and that static/tabs/ask.css only names ids the tab renders.
No network and no model: the status and client calls are faked as in tests/test_ui_build.py."""
from __future__ import annotations

import base64
import re
from pathlib import Path

import gradio as gr
import pytest

from twin import clients, gpu, prompts
from twin.gpu import MANAGER
from twin.ui import ask, frame, state

ROOT = Path(__file__).resolve().parent.parent
ASK_CSS = ROOT / "static" / "tabs" / "ask.css"
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
ASK_INPUTS = ("msg", "chatbot", "q8", "temp", "checker", "condition")        # condition stays LAST
ASK_OUTPUTS = ("chatbot", "trace", "badge", "hint", "msg")
_DEMO: dict = {}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """GET-only fakes; any chat/embed/warm/stop call fails the test."""
    monkeypatch.setattr(MANAGER, "status", lambda: dict(FIXED_STATUS))
    monkeypatch.setattr(clients.ollama, "ps", lambda: [])
    monkeypatch.setattr(clients.ollama, "tags", lambda: [])
    monkeypatch.setattr(clients.lms, "models_v0", lambda: [])
    monkeypatch.setattr(clients.lms, "models_v1", lambda: [])
    monkeypatch.setattr(clients.lms, "loaded", lambda: [])
    monkeypatch.setattr(gpu, "gpu_line", lambda: "")
    for obj, names in ((clients.ollama, ("chat", "embed", "warm", "stop")),
                       (clients.lms, ("chat", "embed", "unload_all"))):
        for n in names:
            monkeypatch.setattr(obj, n, _boom)
    yield


def _demo() -> gr.Blocks:
    if "demo" not in _DEMO:
        _DEMO["demo"] = frame.build_app()
    return _DEMO["demo"]


def _parts() -> dict:
    return _demo().twin_parts["ask"]


def _ancestors(block) -> list:
    out, p = [], getattr(block, "parent", None)
    while p is not None:
        out.append(p)
        p = getattr(p, "parent", None)
    return out


def _ancestor_with_id(block, elem_id: str):
    return next((a for a in _ancestors(block) if getattr(a, "elem_id", None) == elem_id), None)


def _ids(blocks) -> list:
    return [b._id for b in blocks]


# ---- DEMO CONTRACT: copy, defaults, wiring and returns --------------------------------------------------------------

def test_labels_placeholders_defaults_and_choices_unchanged():
    p = _parts()
    assert p["tab"].label == "Ask" and p["tab"].id == "ask" and p["tab"].elem_id == "tab-ask"
    assert p["chatbot"].label == "Chat with the twin" and p["chatbot"].height == 420
    assert p["msg"].label == "Message" and p["msg"].placeholder == "Ask me something..." and p["msg"].lines == 1
    assert p["send_btn"].value == "Send" and p["clear_btn"].value == "Clear"
    t = p["temp"]
    assert (t.label, t.minimum, t.maximum, t.value, t.step) == ("Temperature", 0.5, 1.4, 1.0, 0.01)
    assert p["q8"].label == "Q8 Stheno (Ollama, slow)" and p["q8"].value is False
    assert p["checker"].label == "Consistency check (qwen2.5)" and p["checker"].value is False
    c = p["condition"]
    assert c.label == "Condition" and c.value == prompts.DEFAULT_CONDITION and c.elem_id == "ask-condition"
    assert [v for _label, v in c.choices] == list(prompts.CONDITIONS)
    assert p["trace"].value == "_(no trace yet)_" and p["hint"].value == "" and p["badge"].value == ""
    acc = next(a for a in _ancestors(p["trace"]) if isinstance(a, gr.Accordion))
    assert acc.label == "Trace" and acc.open is False


def test_event_wiring_unchanged():
    demo, p = _demo(), _parts()
    fns = list(demo.fns.values())
    send = next(fn for fn in fns if fn.api_name == "ask")
    assert _ids(send.inputs) == _ids(p[k] for k in ASK_INPUTS)
    assert _ids(send.outputs) == _ids(p[k] for k in ASK_OUTPUTS)
    assert send.concurrency_id == "gpu" and (p["send_btn"]._id, "click") in [tuple(t) for t in send.targets]
    submit = [fn for fn in fns if any(ev == "submit" and demo.blocks.get(i) is p["msg"] for i, ev in fn.targets)]
    assert len(submit) == 1 and submit[0].api_visibility == "private" and submit[0].concurrency_id == "gpu"
    assert _ids(submit[0].inputs) == _ids(send.inputs) and _ids(submit[0].outputs) == _ids(send.outputs)
    clear = next(fn for fn in fns if fn.api_name == "ask_clear")
    assert clear.inputs == [] and _ids(clear.outputs) == _ids(p[k] for k in ASK_OUTPUTS)
    assert clear.concurrency_id != "gpu" and (p["clear_btn"]._id, "click") in [tuple(t) for t in clear.targets]


def test_handlers_return_what_they_returned_before():
    assert ask.ask_clear() == ([], "", "", "", "")
    assert list(ask.ask_send("   ", [], False, 1.0, False)) == [([], "_(empty message)_", "", "", "")]


# ---- restyle: ids, classes, one primary action ------------------------------------------------------------------------

def test_composer_panel_and_one_primary_action():
    demo, p = _demo(), _parts()
    buttons = [b for b in demo.blocks.values()
               if isinstance(b, gr.Button) and any(a is p["tab"] for a in _ancestors(b))]
    assert sorted(b.value for b in buttons) == ["Clear", "Send"]
    assert [b.value for b in buttons if b.variant == "primary"] == ["Send"]
    assert "twin-quiet" in p["clear_btn"].elem_classes and p["clear_btn"].variant != "primary"
    assert (p["send_btn"].elem_id, p["clear_btn"].elem_id) == ("ask-send", "ask-clear")
    composer = _ancestor_with_id(p["msg"], "ask-composer")
    assert composer is not None and "twin-panel" in composer.elem_classes
    compose = _ancestor_with_id(p["send_btn"], "ask-compose")
    assert compose is not None and "twin-actions" in compose.elem_classes
    assert _ancestor_with_id(p["msg"], "ask-compose") is compose and _ancestor_with_id(compose, "ask-composer") is composer
    for key, elem_id in (("condition", "ask-condition"), ("temp", "ask-temperature"), ("q8", "ask-q8"),
                         ("checker", "ask-checker-toggle")):
        assert p[key].elem_id == elem_id
        assert _ancestor_with_id(p[key], "ask-settings") is not None
        assert _ancestor_with_id(p[key], "ask-composer") is composer


def test_evidence_rail_sits_beside_the_conversation():
    p = _parts()
    conversation = _ancestor_with_id(p["chatbot"], "ask-conversation")
    rail = _ancestor_with_id(p["trace"], "ask-rail")
    main = _ancestor_with_id(rail, "ask-main")
    assert conversation is not None and rail is not None and main is _ancestor_with_id(conversation, "ask-main")
    assert "twin-split" in main.elem_classes and main.children == [conversation, rail]
    assert _ancestor_with_id(p["msg"], "ask-conversation") is conversation
    for key in ("hint", "badge"):
        assert _ancestor_with_id(p[key], "ask-rail") is rail, key


def test_side_panels_carry_the_contract_classes():
    p = _parts()
    assert p["chatbot"].elem_id == "ask-chat"
    assert p["hint"].elem_id == "ask-hint" and "twin-hint" in p["hint"].elem_classes
    assert p["badge"].elem_id == "ask-checker" and "trace" in p["badge"].elem_classes
    assert p["trace"].elem_id == "ask-trace" and "trace" in p["trace"].elem_classes
    assert _ancestor_with_id(p["trace"], "ask-trace-panel") is not None


# ---- restyle: placeholder and avatar ----------------------------------------------------------------------------------

def test_chatbot_gets_the_placeholder_and_the_monogram_avatar():
    p = _parts()
    name = getattr(state.PROFILE, "name", "") or ""
    assert p["chatbot"].placeholder == ask.empty_chat_html(name)
    user_avatar, twin_avatar = p["chatbot"].avatar_images
    assert user_avatar is None
    initial = frame.avatar_initial(name)
    if not initial:
        assert twin_avatar is None
        return
    assert twin_avatar["url"].startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(twin_avatar["url"].split(",", 1)[1]).decode("utf-8")
    assert f">{initial}</text>" in svg
    # colourless on purpose: static/tabs/ask.css paints the glyph and its tile from --twin-* tokens
    assert re.search(r"fill=|stroke=|style=|#[0-9a-f]{3,8}\b|rgba?\(", svg, re.IGNORECASE) is None


def test_placeholder_and_avatar_helpers():
    assert ask.twin_avatar("") is None and ask.twin_avatar(None) is None
    anonymous = ask.empty_chat_html(None)
    assert "Ask the twin a question to start." in anonymous and "the twin's voice" in anonymous and "<img" not in anonymous
    mara = ask.empty_chat_html("Mara Ellison")
    assert "Ask Mara a question to start." in mara and "Mara's voice" in mara
    assert 'class="ask-empty-mark" aria-hidden="true"' in mara and 'alt=""' in mara
    hostile = ask.empty_chat_html("<b>x</b> y")
    assert "&lt;b&gt;x&lt;/b&gt;" in hostile and "<b>" not in hostile


def test_ask_partial_names_only_ids_the_tab_renders():
    css = ASK_CSS.read_text(encoding="utf-8")
    for hook in ('[role="log"]', '[aria-label^="bot\'s message"]', '[aria-label^="user\'s message"]',
                 'img[alt="bot avatar"]', "#ask-compose", "#ask-settings", "#ask-trace-panel"):
        assert hook in css, hook
    rendered = {b.elem_id for b in _demo().blocks.values() if getattr(b, "elem_id", None)}
    named = set(re.findall(r"#(ask-[a-z0-9-]+)", css))
    assert named and named <= rendered, sorted(named - rendered)
