"""Offline checks for the Onboarding and Items restyle (docs/PLAN_FINISH.md P4, lane onboarding_items): the ids and
classes static/tabs/onboarding.css and static/tabs/items.css style sit on the right components, and the DEMO CONTRACT
holds (the docs/DEMO.md labels, button text and event wiring). No network, no model: the clients are faked as in
tests/test_ui_build.py."""
from __future__ import annotations

from pathlib import Path

import gradio as gr
import pytest

from twin import clients, gpu
from twin.gpu import MANAGER
from twin.pipelines import items as items_mod
from twin.ui import frame
from twin.ui import onboarding as onboarding_ui

ROOT = Path(__file__).resolve().parent.parent
TABS_CSS = ROOT / "static" / "tabs"
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
_DEMO: dict = {}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """GET-only fakes; any chat/embed/warm/stop call fails the test. MANAGER bookkeeping is restored afterwards."""
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
    MANAGER.active_tab = None
    yield
    MANAGER.active_tab, MANAGER.last_model_tab = saved[0], saved[1]
    MANAGER.tab_overrides.clear()
    MANAGER.tab_overrides.update(saved[2])


def _demo() -> gr.Blocks:
    if "demo" not in _DEMO:
        _DEMO["demo"] = frame.build_app()
    return _DEMO["demo"]


def _public(demo) -> dict:
    return {fn.api_name: fn for fn in demo.fns.values() if fn.api_visibility != "private"}


def _by_id(demo, elem_id: str):
    hits = [b for b in demo.blocks.values() if getattr(b, "elem_id", None) == elem_id]
    assert len(hits) == 1, (elem_id, len(hits))
    return hits[0]


def _classes(block) -> list[str]:
    c = getattr(block, "elem_classes", None) or []
    return [c] if isinstance(c, str) else list(c)


def _same(xs, ys) -> bool:
    xs, ys = list(xs), list(ys)
    return len(xs) == len(ys) and all(a is b for a, b in zip(xs, ys))


# ---- Onboarding --------------------------------------------------------------------------------
def test_onboarding_keeps_labels_ids_and_wiring():
    demo = _demo()
    parts = demo.twin_parts["onboarding"]
    assert "twin-intro" in _classes(_by_id(demo, "onboarding-intro"))
    walk = _by_id(demo, "onboarding-walkthrough")
    assert isinstance(walk, gr.Walkthrough) and "onboarding-walkthrough" in _classes(walk)
    # DEMO.md B1.1 clicks through these four labels
    steps = [b for b in demo.blocks.values() if isinstance(b, gr.Step)]
    assert [s.label for s in steps] == ["1. Run the interview", "2. Save the profile and transcript, then redact",
                                        "3. Rebuild the index", "4. Answer the self-report items"]
    assert [s.elem_id for s in steps] == [f"onboarding-step-{k}" for k in onboarding_ui.STEP_KEYS]
    btn = parts["check_btn"]
    assert btn.elem_id == "onboarding-check" and btn.value == "Check again" and btn.variant == "primary"
    fn = _public(demo)["onboarding_check"]
    assert fn.inputs == [] and _same(fn.outputs, parts["status"])
    assert [o.elem_id for o in fn.outputs] == [f"onboarding-status-{k}" for k in onboarding_ui.STEP_KEYS]
    assert all("onboarding-status" in _classes(o) for o in fn.outputs)
    assert list(fn.targets) == [(btn._id, "click")]


# ---- Items -------------------------------------------------------------------------------------
DATA_BUTTONS = {"items-save": "Save answers", "items-run": "Run twin (qwen3-8b-8k, Stheno, two judges)",
                "items-score": "Score (no model)"}


def test_items_data_buttons_are_caution_outlines_with_their_labels():
    """docs/DEMO.md section 3 forbids all three live: none may look like the next step (no primary fill)."""
    demo = _demo()
    for elem_id, label in DATA_BUTTONS.items():
        b = _by_id(demo, elem_id)
        assert isinstance(b, gr.Button) and b.value == label, elem_id
        assert b.variant != "primary" and "twin-caution" in _classes(b) and b.scale == 0, elem_id
    for row in ("items-wave-row", "items-run-row"):
        assert isinstance(_by_id(demo, row), gr.Row) and "twin-actions" in _classes(_by_id(demo, row)), row


def test_items_restyle_keeps_labels_classes_and_wiring():
    demo = _demo()
    parts = demo.twin_parts["items"]
    assert "twin-intro" in _classes(parts["intro"])
    assert parts["wave"].label == "Wave (1 = day 0, 2 = day-14 retest)" and parts["date"].label == "Date (YYYY-MM-DD)"
    assert parts["condition"].label == "Condition" and parts["condition"].value == "interview"
    assert parts["scores"].label == "Scores per condition and instrument" and "twin-table" in _classes(parts["scores"])
    assert list(parts["scores"].headers) == items_mod.SCORE_HEADERS
    assert parts["decision"].elem_id == "items-decision"
    assert {"twin-card", "twin-result"} <= set(_classes(parts["decision"]))
    accs = [b for b in demo.blocks.values() if isinstance(b, gr.Accordion) and "items-group" in _classes(b)]
    assert [a.elem_id for a in accs] == ["items-group-ipip50", "items-group-game", "items-group-gold", "items-group-gss"]
    assert [a.open for a in accs] == [True, False, False, False]
    assert len([b for b in demo.blocks.values() if isinstance(b, gr.Markdown) and "items-note" in _classes(b)]) == 3
    pub = _public(demo)
    save, run, score = pub["items_save"], pub["items_run"], pub["items_score"]
    assert _same(save.inputs, [parts["wave"], parts["date"], *parts["inputs"]])
    assert _same(save.outputs, [parts["save_note"], parts["files"]])
    assert _same(run.inputs, [parts["condition"]]) and _same(run.outputs, [parts["run_note"], parts["scores"]])
    assert score.inputs == [] and _same(score.outputs, [parts["scores"], parts["decision"]])
    assert run.concurrency_id == "gpu" and save.concurrency_id != "gpu" and score.concurrency_id != "gpu"
    for fn, btn in ((save, parts["save_btn"]), (run, parts["run_btn"]), (score, parts["score_btn"])):
        assert list(fn.targets) == [(btn._id, "click")], fn.api_name
    reload = [fn for fn in demo.fns.values() if (parts["wave"]._id, "change") in list(fn.targets)]
    assert len(reload) == 1 and reload[0].api_visibility == "private"


# ---- the partials ------------------------------------------------------------------------------
def test_partials_carry_the_lane_rules():
    """The partials exist and style the hooks above; they never set Gradio's accent variable (the walkthrough paints
    white numbers on it) and never need !important. tests/test_theme.py enforces scope and tokens-only for all."""
    onb = (TABS_CSS / "onboarding.css").read_text(encoding="utf-8")
    its = (TABS_CSS / "items.css").read_text(encoding="utf-8")
    for needle in ("#onboarding-walkthrough", '[role="tablist"] > div:first-child', '[role="tablist"] > div:last-child',
                   ":has(> span + span)", "#onboarding-check"):
        assert needle in onb, needle
    for needle in ("#items-decision .twin-card", "#items-form button:has(> span + span)", "#items-files em",
                   "label:has(> input:checked)"):
        assert needle in its, needle
    for name, text in (("onboarding.css", onb), ("items.css", its)):
        assert "--color-accent" not in text and "!important" not in text, name
