"""Offline tests for the twin.ui split (docs/PLAN_UNIFIED.md 3.8): the api_name set equals the monolith baseline
captured in scripts/dev/view_api_baseline.json, model endpoints sit on the gpu queue, the hooks are private, and
TWIN_NO_WARM=1 gates every warm path. No network: MANAGER.status, the clients and nvidia-smi are faked."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import gradio as gr
import pytest

from twin import clients, config, gpu, index
from twin.gpu import MANAGER
from twin.ui import frame, items, onboarding, state
from twin.ui import status as status_ui

ROOT = Path(__file__).resolve().parent.parent
BASELINE = json.loads((ROOT / "scripts" / "dev" / "view_api_baseline.json").read_text(encoding="utf-8"))

MODEL_ENDPOINTS = {"ask", "decide_b1", "decide_b2", "say_it", "act", "polish", "see", "eval_voice_rerun",
                   "eval_retrieval_rerun", "eval_live", "free_gpu", "warm", "rebuild_index", "rebuild_digest",
                   "persona_switch"}
NO_GPU_ENDPOINTS = {"ask_clear", "eval_show", "status", "persona_import"}
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
_DEMO: dict = {}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """GET-only fakes; any chat/embed/warm/stop call fails the test. MANAGER bookkeeping is reset around each test."""
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
    MANAGER.last_model_tab = None
    MANAGER.tab_overrides.clear()
    yield
    MANAGER.active_tab, MANAGER.last_model_tab = saved[0], saved[1]
    MANAGER.tab_overrides.clear()
    MANAGER.tab_overrides.update(saved[2])


def _demo() -> gr.Blocks:
    if "demo" not in _DEMO:
        _DEMO["demo"] = frame.build_app()
    return _DEMO["demo"]


def _deps(demo):
    return list(demo.fns.values())


def _public(demo) -> dict:
    """api_name -> BlockFunction for the documented endpoints."""
    return {fn.api_name: fn for fn in _deps(demo) if fn.api_visibility != "private"}


def _target_kinds(demo, fn) -> list[tuple[str, str]]:
    return [((type(demo.blocks[i]).__name__ if i in demo.blocks else "Blocks"), ev) for i, ev in fn.targets]


# ---- (a) api_name set equals the monolith baseline (+ the workflow-B names once those tabs are READY) ----
def _all_ready() -> bool:
    return bool(items.READY and onboarding.READY)


def test_api_names_cover_baseline_and_only_the_planned_additions():
    demo = _demo()
    names = set("/" + n for n in _public(demo))
    baseline = set(BASELINE["api_names"])
    assert len(baseline) == 17
    assert baseline <= names, sorted(baseline - names)
    extra = names - baseline
    assert extra <= {"/" + n for n in frame.NEW_API_NAMES}, sorted(extra)


def test_api_names_complete_once_pipelines_landed():
    """Strict equality baseline + NEW_API_NAMES; meaningful only after workflow B (items/onboarding READY)."""
    if not _all_ready():
        pytest.skip("items/onboarding placeholders still in place (workflow B not landed)")
    demo = _demo()
    names = set("/" + n for n in _public(demo))
    assert names == set(BASELINE["api_names"]) | {"/" + n for n in frame.NEW_API_NAMES}


def test_endpoint_shapes_equal_baseline():
    """Inputs (minus gr.State) and outputs (minus gr.State) per endpoint match the captured parameters/returns.
    Plan 3.4: the condition endpoints may carry ONE extra trailing gr.Dropdown (the condition), nothing else."""
    demo = _demo()
    pub = _public(demo)
    for name, ep in BASELINE["endpoints"].items():
        key = name.lstrip("/")
        fn = pub[key]
        ins = [c for c in fn.inputs if not isinstance(c, gr.State)]
        outs = [c for c in fn.outputs if not isinstance(c, gr.State)]
        n_params = len(ep["parameters"])
        if key in frame.CONDITION_ENDPOINTS and len(ins) == n_params + 1:
            assert isinstance(ins[-1], gr.Dropdown), (name, "the extra input must be the condition dropdown")
            assert set(ins[-1].choices and [c[1] for c in ins[-1].choices] or []) == {"demographic", "persona", "interview"}, name
            ins = ins[:-1]
        assert len(ins) == n_params, name
        assert len(outs) == len(ep["returns"]), name
        for comp, p in zip(ins, ep["parameters"]):
            assert type(comp).__name__.lower() == p["component"].lower(), (name, p["parameter_name"])


# ---- (b) gpu queue on every model endpoint ---------------------------------------------------
def test_model_endpoints_use_gpu_queue():
    pub = _public(_demo())
    assert MODEL_ENDPOINTS <= set(pub)
    for name in MODEL_ENDPOINTS:
        assert pub[name].concurrency_id == "gpu", name
    for name in NO_GPU_ENDPOINTS:
        assert pub[name].concurrency_id != "gpu", name


# ---- (c) hooks are private --------------------------------------------------------------------
def test_hooks_are_private():
    demo = _demo()
    seen = {"select": 0, "tick": 0, "load": 0, "submit": 0}
    for fn in _deps(demo):
        kinds = _target_kinds(demo, fn)
        for kind, ev in kinds:
            if (kind, ev) in (("Tab", "select"), ("Timer", "tick"), ("Blocks", "load"), ("Textbox", "submit")):
                assert fn.api_visibility == "private", (kinds, fn.api_name)
                seen[ev] += 1
    ready_extra = int(bool(items.READY)) + int(bool(onboarding.READY))
    assert seen["select"] == 6 + ready_extra   # ask, decide, act, see, eval on the gpu queue + status (+ READY tabs)
    assert seen["tick"] == 3              # Status tab refresh, Status tiles + status strip on the one timer
    assert seen["load"] == 1
    assert seen["submit"] >= 1            # ask_msg.submit (workflow-B tabs may add private submits of their own)
    timers = {i for i, b in demo.blocks.items() if isinstance(b, gr.Timer)}
    assert len(timers) == 1


def test_tab_select_queues_match_monolith():
    demo = _demo()
    by_tab = {}
    for fn in _deps(demo):
        for i, ev in fn.targets:
            if ev == "select" and isinstance(demo.blocks.get(i), gr.Tab):
                by_tab[demo.blocks[i].id] = fn
    expected = {"ask", "decide", "act", "see", "eval", "status"}
    expected |= {t for t, mod in (("items", items), ("onboarding", onboarding)) if mod.READY}
    assert set(by_tab) == expected
    for tab in ("ask", "decide", "act", "see", "eval"):
        assert by_tab[tab].concurrency_id == "gpu"
    for tab in expected - {"ask", "decide", "act", "see", "eval"}:
        assert by_tab[tab].concurrency_id != "gpu", tab      # model-less tabs never take a gpu slot to say so
    ask_submit = [fn for fn in _deps(demo)
                  if any(ev == "submit" and demo.blocks.get(i) is demo.twin_parts["ask"]["msg"] for i, ev in fn.targets)]
    assert len(ask_submit) == 1 and ask_submit[0].concurrency_id == "gpu"


def test_placeholders_add_nothing():
    """While a tab is still a placeholder it renders one card and wires nothing; once READY it must have its tab."""
    demo = _demo()
    parts = demo.twin_parts
    for tab_id, mod in (("items", items), ("onboarding", onboarding)):
        tab = parts[tab_id]["tab"]
        assert isinstance(tab, gr.Tab) and tab.elem_id == f"tab-{tab_id}"
        if mod.READY:
            continue
        assert all(i != tab._id for fn in _deps(demo) for i, _ev in fn.targets)
        assert "placeholder-card" in (parts[tab_id]["card"].elem_classes or [])


def test_frame_elem_ids_and_tab_order():
    demo = _demo()
    ids = {b.elem_id for b in demo.blocks.values() if getattr(b, "elem_id", None)}
    assert {"twin-header", "gpu-note", "status-strip", "twin-tabs"} <= ids
    assert all(f"tab-{t}" in ids for t in frame.TAB_IDS)
    tabs = [b for b in demo.blocks.values() if isinstance(b, gr.Tab)]
    assert [t.id for t in tabs] == list(frame.TAB_IDS)
    assert any(isinstance(b, gr.Sidebar) and b.elem_id == "status-strip" for b in demo.blocks.values())


# ---- (d) TWIN_NO_WARM gates every warm path -----------------------------------------------------
def test_no_warm_gates_every_warm_path(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(MANAGER, "warm", lambda key: calls.append(key))
    monkeypatch.setattr(index, "build_all", _boom)
    monkeypatch.setattr(index, "rebuild_digest", _boom)
    monkeypatch.setattr(gpu.threading, "Thread", _boom)
    monkeypatch.setattr(MANAGER, "_heartbeat", None)
    monkeypatch.setenv("TWIN_NO_WARM", "1")
    assert config.no_warm() and state.no_warm()

    note = frame.make_tab_select("ask")()
    assert "Pre-warm skipped (TWIN_NO_WARM=1)" in note and MANAGER.active_tab == "ask"
    assert "skipped: TWIN_NO_WARM=1" in status_ui.warm_handler("ask")
    assert "skipped: TWIN_NO_WARM=1" in status_ui.warm_handler("active")
    md, header = status_ui.rebuild_index_handler()
    assert "skipped: TWIN_NO_WARM=1" in md and header.startswith("## Digital twin")
    md, header = status_ui.rebuild_digest_handler()
    assert "skipped: TWIN_NO_WARM=1" in md and header.startswith("## Digital twin")
    MANAGER.start_heartbeat()
    assert MANAGER._heartbeat is None
    assert MANAGER.heartbeat_tick() is None
    assert "Status open" in frame.make_tab_select("status")()
    assert calls == []

    monkeypatch.delenv("TWIN_NO_WARM")
    note = frame.make_tab_select("ask")()
    assert calls == ["stheno_q4"] and "Pre-warmed stheno_q4" in note


def test_no_warm_env_values():
    for v, want in (("1", True), ("true", True), ("yes", True), ("0", False), ("false", False), ("", False)):
        import os
        os.environ["TWIN_NO_WARM"] = v
        try:
            assert config.no_warm() is want, v
        finally:
            del os.environ["TWIN_NO_WARM"]


# ---- (e) tab ids, labels, JS ----------------------------------------------------------------------
def test_tab_ids_and_js_labels(monkeypatch):
    assert frame.TAB_IDS == ("onboarding", "ask", "decide", "act", "see", "items", "eval", "status")
    assert set(frame.TAB_LABELS) == set(frame.TAB_IDS)
    for label in frame.TAB_LABELS.values():
        assert json.dumps(label) in frame.TAB_JS
    assert "button[role=\"tab\"]" in frame.TAB_JS
    assert "params.get('nomotion') === '1'" in frame.TAB_JS and "transition: none !important" in frame.TAB_JS
    # narrow viewports collapse the status-strip sidebar (scoped to our elem_id, no Gradio internals)
    assert "window.innerWidth > 600" in frame.TAB_JS and "#status-strip button" in frame.TAB_JS
    assert '"dark"' in frame.tab_js("dark") and "classList.toggle('dark'" in frame.tab_js("dark")
    assert frame.tab_js("") .count('const forcedTheme = "";') == 1
    monkeypatch.setenv("TWIN_THEME", "dark")
    assert 'const forcedTheme = "dark";' in frame.tab_js()
    # without a valid TWIN_THEME the token sheet's default_theme applies (docs/design/tokens.md: dark)
    monkeypatch.setenv("TWIN_THEME", "bogus")
    assert frame.sheet_default_theme() in ("light", "dark")
    assert f"const forcedTheme = {json.dumps(frame.sheet_default_theme())};" in frame.tab_js()


# ---- page load, header, strip, busy flag -----------------------------------------------------------
def test_page_load_honours_tab_param_and_marks_active_once(monkeypatch, tmp_path):
    # With the real profile present the first tab is Ask (phase-1 behaviour); the missing-profile case is below.
    monkeypatch.setattr(config, "PROFILE_PATH", config.EXAMPLE_PROFILE_V2_PATH)
    req = SimpleNamespace(query_params={"tab": "status"})
    out = frame._on_page_load(req)
    assert out.selected == "status" and MANAGER.active_tab is None
    out = frame._on_page_load(SimpleNamespace(query_params={"tab": "nope"}))
    assert out.selected == "ask" and MANAGER.active_tab == "ask"
    MANAGER.set_active_tab("see")
    out = frame._on_page_load(SimpleNamespace(query_params={"tab": "decide"}))
    assert out.selected == "decide" and MANAGER.active_tab == "see"   # a second window never hijacks
    assert frame._on_page_load(None).selected == "ask"
    assert frame.default_tab() == "ask"
    # No data/twin_profile.md and a functional Onboarding tab: the app opens on Onboarding (no model tab activated).
    monkeypatch.setattr(config, "PROFILE_PATH", tmp_path / "missing_twin_profile.md")
    MANAGER.active_tab = None
    if onboarding.READY:
        assert frame.default_tab() == "onboarding"
        assert frame._on_page_load(None).selected == "onboarding" and MANAGER.active_tab is None
        assert frame._on_page_load(SimpleNamespace(query_params={"tab": "ask"})).selected == "ask"
    else:
        assert frame.default_tab() == "ask"


def test_header_and_strip_text():
    state.load_app_profile()
    md = state.header_markdown()
    assert md.startswith("## Digital twin: ")
    if state.PROFILE is not None:   # masthead readings and the profile disclosure (docs/design/tokens.md section 5)
        assert '<dl class="twin-readings">' in md and "<dt>Indexes</dt>" in md and "<summary>Profile file" in md
    assert state._inline_html("**Warning:** run `a<b>`") == "<strong>Warning:</strong> run <code>a&lt;b&gt;</code>"
    strip = frame.strip_markdown()
    assert "**GPU:**" in strip and "**Heartbeat:** idle" in strip and "**Active tab:**" in strip
    st = {"gpu": "1234 MiB, 8192 MiB, 3 %", "ollama_ps": [{"name": "qwen3-8b-8k:latest", "size": 100, "size_vram": 100,
                                                          "context_length": 8192}],
          "lms_models": [{"id": "l3-8b-stheno-v3.2", "type": "llm", "state": "loaded"}],
          "active_tab": "ask", "active_key": "stheno_q4", "busy": False, "busy_key": None}
    assert frame.heartbeat_state(st) == "ready"
    assert frame.heartbeat_state({**st, "busy": True, "busy_key": "stheno_q4"}) == "busy"
    assert frame.heartbeat_state({**st, "busy": True, "busy_key": "hermes3"}) == "loading"
    assert frame.heartbeat_state({**st, "active_key": "hermes3"}) == "idle"
    assert frame._gpu_mib(st["gpu"]) == (1234, 8192, 3)
    assert frame._gpu_mib("") == (None, None, None)
    lms, oll = frame._loaded_lists(st)
    assert lms == ["l3-8b-stheno-v3.2"] and oll == ["`qwen3-8b-8k:latest` (100% GPU, ctx 8192)"]


def test_busy_flag_and_status_keys():
    m = gpu.ModelManager()
    assert m.busy is False and m.busy_key is None
    with m.session("llama32_1b", tab="test"):
        assert m.busy is True and m.busy_key == "llama32_1b"
        with m.session("llama32_3b"):
            assert m.busy_key == "llama32_3b"
        assert m.busy is True and m.busy_key == "llama32_1b"
    assert m.busy is False and m.busy_key is None
    st = m.status()
    assert st["busy"] is False and st["busy_key"] is None and "active_tab" in st


def test_app_module_reexports():
    import app
    assert app.build_app is frame.build_app and app.TAB_IDS is frame.TAB_IDS and app.TAB_JS == frame.TAB_JS
    assert app.load_app_profile is state.load_app_profile
    state.load_app_profile()
    assert app.PROFILE is state.PROFILE and app.PROFILE_ERROR == state.PROFILE_ERROR
    assert callable(app.pick_port) and app.PORT_TRIES == 10
