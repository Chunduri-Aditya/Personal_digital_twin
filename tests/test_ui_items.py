"""Offline tests for the Items and Onboarding tabs (docs/PLAN_UNIFIED.md 3.5, 3.8): endpoint shapes, the form in
bank order, the wave save with tmp paths, the walkthrough statuses and the default tab. No network, no model:
the clients are faked exactly as in tests/test_ui_build.py."""
from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
import pytest

from twin import clients, config, gpu, index
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_V2_PATH
from twin.gpu import MANAGER
from twin.pipelines import items as items_mod
from twin.ui import frame, state
from twin.ui import items as items_ui
from twin.ui import onboarding as onboarding_ui

FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
_DEMO: dict = {}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path: Path):
    """GET-only fakes; any chat/embed call fails the test; every item data path points at tmp_path."""
    monkeypatch.setattr(MANAGER, "status", lambda: dict(FIXED_STATUS))
    monkeypatch.setattr(clients.ollama, "ps", lambda: [])
    monkeypatch.setattr(clients.ollama, "tags", lambda: [])
    monkeypatch.setattr(clients.lms, "models_v0", lambda: [])
    monkeypatch.setattr(clients.lms, "models_v1", lambda: [])
    monkeypatch.setattr(clients.lms, "loaded", lambda: [])
    monkeypatch.setattr(gpu, "gpu_line", lambda: "")
    for obj, names in ((clients.ollama, ("chat", "embed", "warm", "stop")), (clients.lms, ("chat", "embed", "unload_all"))):
        for n in names:
            monkeypatch.setattr(obj, n, _boom)
    monkeypatch.setattr(index, "search_chunks", _boom)
    monkeypatch.setattr(MANAGER, "free_all", lambda: [])
    monkeypatch.setattr(config, "SELF_ANSWERS_PATH", tmp_path / "items" / "self_answers.json")
    monkeypatch.setattr(config, "SELF_ANSWERS_RETEST_PATH", tmp_path / "items" / "self_answers_retest.json")
    monkeypatch.setattr(config, "TWIN_ANSWERS_PATH", tmp_path / "items" / "twin_answers.json")
    monkeypatch.setattr(config, "ITEM_SCORES_PATH", tmp_path / "items" / "scores.json")
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_V2_PATH)
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


def _example_values() -> list:
    ex = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))["answers"]
    return [ex[it["id"]] for it in items_mod.bank_items(state.PROFILE)]


# ---- endpoints ------------------------------------------------------------------------------
def test_ready_flags_and_new_api_names():
    assert items_ui.READY is True and onboarding_ui.READY is True
    pub = _public(_demo())
    assert {"items_save", "items_run", "items_score", "onboarding_check"} <= set(pub)


def test_items_save_inputs_are_wave_date_then_every_bank_item_in_order():
    demo = _demo()
    fn = _public(demo)["items_save"]
    its = items_mod.bank_items(state.PROFILE)
    assert len(fn.inputs) == 2 + len(its) == 113
    assert isinstance(fn.inputs[0], gr.Dropdown) and fn.inputs[0].elem_id == "items-wave"
    assert [c[1] if isinstance(c, tuple) else c for c in fn.inputs[0].choices] == ["1", "2"]
    assert isinstance(fn.inputs[1], gr.Textbox) and fn.inputs[1].elem_id == "items-date"
    assert [c.elem_id for c in fn.inputs[2:]] == [f"item-{it['id']}" for it in its]
    kinds = {it["type"]: type(c).__name__ for it, c in zip(its, fn.inputs[2:])}
    assert kinds == {"likert5": "Radio", "categorical": "Radio", "number": "Number", "fraction": "Number",
                     "binary": "Radio", "open": "Textbox"}
    # IPIP radios carry the five anchors with int values; GSS radios the exact option labels
    e1 = fn.inputs[2]
    assert [c[1] for c in e1.choices] == [1, 2, 3, 4, 5] and e1.choices[0][0].startswith("1 Very Inaccurate")
    happy = next(c for it, c in zip(its, fn.inputs[2:]) if it["id"] == "GSS_HAPPY")
    assert [c[1] if isinstance(c, tuple) else c for c in happy.choices] == ["VERY HAPPY", "PRETTY HAPPY", "NOT TOO HAPPY"]
    # pre-filled from wave 1 (the example while the real file is missing)
    ex = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))["answers"]
    assert e1.value == ex["IPIP_E1"] and happy.value == ex["GSS_HAPPY"]
    assert len(fn.outputs) == 2 and all(isinstance(o, gr.Markdown) for o in fn.outputs)
    assert fn.concurrency_id != "gpu"
    # form groups per instrument, in bank order
    accs = [b for b in demo.blocks.values() if isinstance(b, gr.Accordion) and (b.elem_id or "").startswith("items-group-")]
    assert [a.elem_id for a in accs] == ["items-group-ipip50", "items-group-game", "items-group-gold", "items-group-gss"]


def test_items_run_and_score_endpoints():
    pub = _public(_demo())
    run = pub["items_run"]
    assert run.concurrency_id == "gpu"
    assert len(run.inputs) == 1 and isinstance(run.inputs[0], gr.Dropdown) and run.inputs[0].elem_id == "items-condition"
    assert [c[1] if isinstance(c, tuple) else c for c in run.inputs[0].choices] == ["all", "demographic", "persona", "interview"]
    assert run.inputs[0].value == "interview"
    assert [type(o).__name__ for o in run.outputs] == ["Markdown", "Dataframe"]
    sc = pub["items_score"]
    assert sc.concurrency_id != "gpu" and sc.inputs == []
    assert [type(o).__name__ for o in sc.outputs] == ["Dataframe", "Markdown"]
    assert list(sc.outputs[0].headers) == items_mod.SCORE_HEADERS


def test_onboarding_check_endpoint_and_walkthrough():
    demo = _demo()
    fn = _public(demo)["onboarding_check"]
    assert fn.inputs == [] and fn.concurrency_id != "gpu"
    assert [type(o).__name__ for o in fn.outputs] == ["Markdown"] * 4
    assert [o.elem_id for o in fn.outputs] == [f"onboarding-status-{k}" for k in onboarding_ui.STEP_KEYS]
    steps = [b for b in demo.blocks.values() if isinstance(b, gr.Step)]
    assert [s.label for s in steps] == [onboarding_ui.STEP_LABELS[k] for k in onboarding_ui.STEP_KEYS]
    assert any(isinstance(b, gr.Walkthrough) and b.elem_id == "onboarding-walkthrough" for b in demo.blocks.values())
    codes = [b for b in demo.blocks.values() if isinstance(b, gr.Code) and (b.elem_id or "").startswith("onboarding-cmd-")]
    assert [c.value for c in codes] == [onboarding_ui.COMMANDS[k] for k in onboarding_ui.STEP_KEYS]
    assert "twin.redact" in codes[1].value and "--build all --digest --reflect" in codes[2].value
    out = onboarding_ui.onboarding_check()
    assert len(out) == 4 and all(isinstance(m, str) and m.startswith("**") for m in out)


# ---- default tab -------------------------------------------------------------------------------
def test_onboarding_is_the_default_tab_when_the_real_profile_is_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "PROFILE_PATH", tmp_path / "twin_profile.md")
    assert frame.default_tab() == "onboarding"
    assert frame._on_page_load(None).selected == "onboarding" and MANAGER.active_tab is None
    (tmp_path / "twin_profile.md").write_text(EXAMPLE_PROFILE_V2_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    assert frame.default_tab() == "ask"


# ---- handlers ---------------------------------------------------------------------------------
def test_items_save_writes_the_wave_file_with_the_date(tmp_path: Path):
    state.load_app_profile()
    values = _example_values()
    note, files = items_ui.items_save("1", "2026-09-14", *values)
    p = config.SELF_ANSWERS_PATH
    assert p == tmp_path / "items" / "self_answers.json" and p.exists()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["wave"] == 1 and doc["date"] == "2026-09-14" and doc["name"] == "Mara Ellison"
    assert len(doc["answers"]) == 111 and doc["answers"]["IPIP_E1"] == 1 and doc["answers"]["GAME_trust_return"] == 0.5
    assert "GOLD_Q-12" not in doc["answers"]
    assert note.startswith("Saved wave 1 dated 2026-09-14: 111 answers, 0 unanswered")
    assert "self_answers.json" in files and "not saved yet" in files
    assert items_mod.resolve_waves()["example"] is False
    # wave 2 with blanks, an invalid value and a default date
    values2 = list(values)
    values2[0] = None                      # IPIP_E1 unanswered
    values2[-1] = "NOT AN OPTION"          # last GSS item invalid
    note2, _files = items_ui.items_save(2, "", *values2)
    p2 = config.SELF_ANSWERS_RETEST_PATH
    doc2 = json.loads(p2.read_text(encoding="utf-8"))
    assert doc2["wave"] == 2 and len(doc2["date"]) == 10 and len(doc2["answers"]) == 109
    assert "1 unanswered" in note2 and "`IPIP_E1`" in note2 and "Invalid (not saved):" in note2 and "GSS_HELPOTH" in note2
    assert "ceiling" in note2
    # wrong arity is an error, not a crash
    bad, _ = items_ui.items_save("1", "2026-09-14", 1, 2, 3)
    assert bad.startswith("**Error:**")


def test_load_wave_reloads_values_or_blanks():
    state.load_app_profile()
    its = items_mod.bank_items(state.PROFILE)
    ex = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))["answers"]
    out = items_ui.load_wave("1")
    assert len(out) == 1 + len(its)
    assert out[0].constructor_args["value"] == "2026-09-14"                # the example wave-1 date
    assert out[1].constructor_args["value"] == ex["IPIP_E1"]
    out2 = items_ui.load_wave("2")
    ex2 = json.loads(config.EXAMPLE_SELF_ANSWERS_RETEST_PATH.read_text(encoding="utf-8"))["answers"]
    assert out2[0].constructor_args["value"] == "2026-09-28"                # the example retest date
    assert out2[1].constructor_args["value"] == ex2["IPIP_E1"]
    items_ui.items_save("1", "2026-10-01", *_example_values())            # real wave 1 now exists, no retest
    out3 = items_ui.load_wave("2")
    assert out3[1].constructor_args["value"] is None                         # blank: a retest never shows day-0 answers
    assert out3[-1].constructor_args["value"] is None
    assert items_ui.load_wave("1")[0].constructor_args["value"] == "2026-10-01"


def test_items_score_and_run_without_a_model(monkeypatch):
    state.load_app_profile()
    rows, md = items_ui.items_score()
    assert rows == [] and md == items_ui.NO_SCORES_NOTE                       # no twin answers yet, still no crash
    assert not config.ITEM_SCORES_PATH.exists()                               # an empty result is never persisted
    ex = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))["answers"]
    results = {state.PROFILE.sha: {"interview": {k: {"answer": v} for k, v in ex.items()}, "meta": {}}}
    config.TWIN_ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.TWIN_ANSWERS_PATH.write_text(json.dumps(results), encoding="utf-8")
    rows, md = items_ui.items_score()
    assert rows and rows[0][:3] == ["interview", "ipip50", "E"] and len(rows[0]) == len(items_mod.SCORE_HEADERS)
    assert md.startswith("**Decision:") and config.ITEM_SCORES_PATH.exists()
    cached_rows, cached_md = items_ui.cached_scores()
    assert cached_rows == rows and cached_md == md
    # the run endpoint is gated by TWIN_NO_WARM (no model call, cached rows returned)
    monkeypatch.setenv("TWIN_NO_WARM", "1")
    note, rows2 = items_ui.items_run("all")
    assert note == f"Run twin (demographic, persona, interview): {items_ui.NO_WARM_NOTE}" and rows2 == rows
    monkeypatch.delenv("TWIN_NO_WARM")
    called = {}

    def fake_run(conditions=("interview",), progress=None, profile=None, resume=True):
        called["conds"] = list(conditions)
        progress("[1/2] retrieval lms_nomic IPIP_E1")
        progress("distribution [interview]:")
        return {"calls": 2, "models": ["qwen3_8k"], "report": ["distribution [interview]:", "  gss: answered 0/37"],
                "entry": {}, "sha": state.PROFILE.sha, "conditions": list(conditions),
                "excluded": [("GOLD_Q-12", "excluded: politics")]}
    monkeypatch.setattr(items_mod, "run_items", fake_run)
    note, rows3 = items_ui.items_run("persona")
    assert called["conds"] == ["persona"] and "2 model calls" in note and "GOLD_Q-12" in note
    assert "gss: answered 0/37" in note and "**Decision:" in note and rows3 == rows


def test_onboarding_statuses_reflect_the_files(monkeypatch, tmp_path: Path):
    state.load_app_profile()
    monkeypatch.setattr(config, "PROFILE_PATH", tmp_path / "twin_profile.md")
    # twin.index binds the transcript paths at import time, so both modules are pointed at tmp_path
    for mod in (config, index):
        monkeypatch.setattr(mod, "TRANSCRIPT_PATH", tmp_path / "interview_transcript.md")
        monkeypatch.setattr(mod, "REDACTED_TRANSCRIPT_PATH", tmp_path / "interview_transcript.redacted.md")
    done, md = onboarding_ui.interview_status()
    assert done is False and "twin_profile.md" in md and "example profile" in md
    done, md = onboarding_ui.redact_status()
    assert done is False and "interview_transcript.md" in md
    done, md = onboarding_ui.items_status()
    assert done is False and "self_answers.json" in md and "Items" in md
    assert onboarding_ui.first_incomplete() == 0
    # files appear
    (tmp_path / "twin_profile.md").write_text(EXAMPLE_PROFILE_V2_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    done, md = onboarding_ui.interview_status()
    assert done is True and md.startswith("**Done.**") and "Mara Ellison" in md and "20 eval questions" in md
    items_ui.items_save("1", "2026-09-14", *_example_values())
    done, md = onboarding_ui.items_status()
    assert done is True and "Wave 1 saved 2026-09-14 (111 answers)" in md and "ceiling pending" in md
    items_ui.items_save("2", "2026-09-28", *_example_values())
    done, md = onboarding_ui.items_status()
    assert done and "Wave 2 saved 2026-09-28" in md
    # a real transcript without a redacted copy -> RedactionRequired text
    (tmp_path / "interview_transcript.md").write_text(config.EXAMPLE_TRANSCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    done, md = onboarding_ui.redact_status()
    assert done is False and "python -m twin.redact" in md
    # index status never calls a model; it reports fresh/stale per index
    done, md = onboarding_ui.index_status()
    assert isinstance(done, bool) and all(f"`{k}`" in md for k in index.INDEX_KEYS) and "digest" in md
    out = onboarding_ui.onboarding_check()
    assert len(out) == 4 and out[0].startswith("**Done.**")
