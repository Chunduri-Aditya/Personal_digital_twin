"""Offline tests for the Decide tab restyle (docs/PLAN_FINISH.md P4, decide lane): the copy, defaults and event wiring
the DEMO CONTRACT freezes are unchanged; the new wrappers carry the frame-contract classes; B1 is the tab's one primary
action; the confidence-meter hook is private, off the gpu queue and model-less; static/tabs/decide.css only names
elem_ids the tab really has. No network: MANAGER.status, the clients and nvidia-smi are faked (tests/test_ui_build.py)."""
from __future__ import annotations

import re
from pathlib import Path

import gradio as gr
import pytest

from twin import clients, gpu, prompts
from twin.gpu import MANAGER
from twin.pipelines import decide
from twin.ui import decide as decide_ui
from twin.ui import frame

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "tabs" / "decide.css"
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
_DEMO: dict = {}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
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
    monkeypatch.delenv("TWIN_NO_WARM", raising=False)
    saved = (MANAGER.active_tab, MANAGER.last_model_tab, dict(MANAGER.tab_overrides))
    yield
    MANAGER.active_tab, MANAGER.last_model_tab = saved[0], saved[1]
    MANAGER.tab_overrides.clear()
    MANAGER.tab_overrides.update(saved[2])


def _demo() -> gr.Blocks:
    if "demo" not in _DEMO:
        _DEMO["demo"] = frame.build_app()
    return _DEMO["demo"]


def _parts() -> dict:
    return _demo().twin_parts["decide"]


def _by_elem_id() -> dict:
    return {b.elem_id: b for b in _demo().blocks.values() if getattr(b, "elem_id", None)}


def _ids(components) -> list[int]:
    return [c._id for c in components]


def _ancestors(block) -> list:
    out = []
    block = getattr(block, "parent", None)
    while block is not None:
        out.append(block)
        block = getattr(block, "parent", None)
    return out


def _in_decide_tab(block) -> bool:
    return any(a is _parts()["tab"] for a in _ancestors(block))


RECORDED_B1 = {"kind": "b1", "situation": "A three-month contract at double my rate. Should I take it?",
               "verdict": "no", "confidence": 0.95, "reasons": ["it pauses my own product work"],
               "cited_decisions": ["D-01", "D-08"], "uncited": [], "what_would_change_my_mind": "keeping my product work",
               "model": "qwen3-8b-8k", "timing_ms": 12029.0, "chunk_ids": ["a", "b"], "attempts": 1,
               "condition": "interview", "error": None}


# ---- the DEMO CONTRACT: copy, defaults and wiring --------------------------------------------------------------
def test_decide_copy_and_defaults_are_unchanged():
    p = _parts()
    assert p["tab"].label == "Decide" and p["tab"].id == "decide" and p["tab"].elem_id == "tab-decide"
    assert p["situation"].label == "Situation" and p["situation"].lines == 3
    assert p["situation"].placeholder == "Describe the situation as if you were texting me about it..."
    assert p["condition"].label == "Condition" and p["condition"].elem_id == "decide-condition"
    assert p["condition"].value == prompts.DEFAULT_CONDITION
    assert [c[1] for c in p["condition"].choices] == list(prompts.CONDITIONS)
    assert p["condition"].info == ("interview: retrieved context + digest; persona: identity + digest; "
                                   "demographic: identity only")
    assert p["b1_btn"].value == "B1: Would I do it?"
    assert p["option_a"].label == "Option A" and p["option_a"].lines == 2
    assert p["option_b"].label == "Option B" and p["option_b"].lines == 2
    assert p["b2_btn"].value == "B2: A or B?"
    assert p["md"].value == "_(no decision yet)_"
    assert p["json"].label == "Raw result"
    assert p["say_btn"].value == "Say it in my voice"
    assert p["say_out"].label == "In my voice" and p["say_out"].lines == 2


def test_decide_endpoints_keep_their_inputs_outputs_and_queue():
    demo, p = _demo(), _parts()
    pub = {fn.api_name: fn for fn in demo.fns.values() if fn.api_visibility != "private"}
    expected = {
        "decide_b1": (decide_ui.decide_b1_handler, p["b1_btn"], [p["situation"], p["condition"]]),
        "decide_b2": (decide_ui.decide_b2_handler, p["b2_btn"],
                      [p["situation"], p["option_a"], p["option_b"], p["condition"]]),
    }
    for name, (handler, button, inputs) in expected.items():
        fn = pub[name]
        assert fn.fn is handler and fn.concurrency_id == "gpu", name
        assert fn.targets == [(button._id, "click")], name
        assert _ids(fn.inputs) == _ids(inputs), name
        assert _ids(fn.outputs) == _ids([p["md"], p["json"], p["state"]]), name
    say = pub["say_it"]
    assert say.fn is decide_ui.say_it_handler and say.concurrency_id == "gpu"
    assert say.targets == [(p["say_btn"]._id, "click")]
    assert _ids(say.inputs) == [p["state"]._id] and _ids(say.outputs) == [p["say_out"]._id]


def test_handlers_return_what_they_returned_before(monkeypatch):
    monkeypatch.setattr(decide, "decide_b1", lambda *_a, **_k: dict(RECORDED_B1))
    md, raw, st = decide_ui.decide_b1_handler("x")
    assert md == decide.render_result_markdown(RECORDED_B1) and raw == RECORDED_B1 and st == RECORDED_B1
    monkeypatch.setattr(decide, "decide_b1", lambda *_a, **_k: (_ for _ in ()).throw(ConnectionError("refused")))
    md, raw, st = decide_ui.decide_b1_handler("x")
    assert md == "**Error:** `ConnectionError: refused`" and raw == {"error": "Error: ConnectionError: refused"}
    assert st is None
    assert decide_ui.say_it_handler(None) == "(run B1 or B2 first)"


# ---- the restyle: wrappers, classes, hierarchy -----------------------------------------------------------------
def test_decide_wrappers_carry_the_frame_contract_classes():
    ids, p = _by_elem_id(), _parts()
    assert isinstance(ids["decide-question"], gr.Column) and "twin-panel" in ids["decide-question"].elem_classes
    assert isinstance(ids["decide-options"], gr.Column) and "twin-panel" in ids["decide-options"].elem_classes
    assert "twin-split" in ids["decide-option-fields"].elem_classes
    verdict = ids["decide-verdict"]
    assert isinstance(verdict, gr.Column) and verdict.elem_classes == ["verdict-card"]
    assert p["confidence"].parent is verdict and p["md"].parent is verdict
    assert verdict.children.index(p["confidence"]) < verdict.children.index(p["md"])   # the markdown paints on top
    assert p["md"].elem_id == "decide-result" and isinstance(p["confidence"], gr.HTML)
    row = ids["decide-result-row"]
    assert verdict.parent is row and row.children == [verdict]                          # the card takes the whole row
    panel = ids["decide-raw-panel"]                                                     # raw result behind a disclosure
    assert isinstance(panel, gr.Accordion) and panel.label == "Raw result" and panel.open is False
    assert p["json"].parent is panel and p["json"].elem_id == "decide-raw"
    card = ids["decide-say-card"]
    assert isinstance(card, gr.Column) and card.elem_classes == ["quote-card"]
    assert p["say_out"].elem_id == "decide-say" and card in _ancestors(p["say_out"])   # via Gradio's auto Form
    for key in ("b1_btn", "b2_btn", "say_btn"):
        assert "twin-actions" in (p[key].parent.elem_classes or []), key
        assert p[key].scale == 0, key


def test_b1_is_the_one_primary_action_on_the_tab():
    buttons = [b for b in _demo().blocks.values() if isinstance(b, gr.Button) and _in_decide_tab(b)]
    assert {b.value for b in buttons} == {"B1: Would I do it?", "B2: A or B?", "Say it in my voice"}
    assert [b.value for b in buttons if b.variant == "primary"] == ["B1: Would I do it?"]


# ---- the confidence meter -----------------------------------------------------------------------------------------
def test_confidence_hook_is_private_model_less_and_off_the_gpu_queue():
    demo, p = _demo(), _parts()
    # keyed on the result markdown, which is always on screen (the raw JSON sits in a closed disclosure)
    assert not [fn for fn in demo.fns.values() if (p["json"]._id, "change") in fn.targets]
    hooks = [fn for fn in demo.fns.values() if (p["md"]._id, "change") in fn.targets]
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook.api_visibility == "private" and hook.concurrency_id != "gpu"
    assert hook.fn is decide_ui.confidence_handler and hook.show_progress == "hidden"
    assert _ids(hook.inputs) == [p["state"]._id] and _ids(hook.outputs) == [p["confidence"]._id]
    assert p["confidence"].value in ("", None)


def test_confidence_html_draws_only_real_decisions():
    for st in (None, "text", {}, {**RECORDED_B1, "error": "situation is empty"}, {**RECORDED_B1, "verdict": None},
               {**RECORDED_B1, "confidence": None}, {"kind": "b2", "choice": None, "confidence": 0.5}):
        assert decide_ui.confidence_html(st) == "", st
    html = decide_ui.confidence_html(RECORDED_B1)
    assert html.startswith('<div class="confidence-meter" aria-hidden="true">')
    assert '<span class="fill" style="width: 95%"></span>' in html and '<span class="value">0.95</span>' in html
    b2 = decide_ui.confidence_html({"kind": "b2", "choice": "B", "confidence": 1.7, "error": None})
    assert "width: 100%" in b2 and ">1.00<" in b2
    assert decide_ui.confidence_handler(RECORDED_B1) == html


def test_confidence_meter_value_equals_the_markdown_line():
    for conf in (0.95, 0.5, 0.004, 0.996, "0.7", 3):
        result = {**RECORDED_B1, "confidence": conf}
        line = re.search(r"Confidence: (\d\.\d\d)", decide.render_result_markdown(result)).group(1)
        assert f'<span class="value">{line}</span>' in decide_ui.confidence_html(result), conf


def test_confidence_handler_never_raises(monkeypatch):
    monkeypatch.setattr(decide, "_clamp_confidence", _boom)
    assert decide_ui.confidence_handler(RECORDED_B1) == ""


# ---- the partial names only real ids -------------------------------------------------------------------------------
def test_decide_css_names_only_ids_the_tab_has():
    css = CSS.read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    named = set(re.findall(r"#(decide-[a-z0-9-]+)", body))
    assert {"decide-verdict", "decide-confidence", "decide-result", "decide-raw", "decide-say-card"} <= named
    missing = named - set(_by_elem_id())
    assert not missing, sorted(missing)
