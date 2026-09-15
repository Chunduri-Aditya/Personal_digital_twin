"""Offline tests for the Eval and Status restyle (docs/PLAN_FINISH.md P4, evals_status lane).

static/tabs/eval.css and static/tabs/status.css style ids and classes that twin/ui/evals.py and twin/ui/status.py set.
These tests pin those hooks and the button hierarchy (Free GPU is the Status tab's only filled button; the Eval model
actions and the Status rebuilds are .twin-caution and never filled), plus what the DEMO CONTRACT freezes on these two
tabs: labels, values and choices, api_names, queues, and the triggers, inputs and outputs of every event.
No network and no model: the GET-only fakes of tests/test_ui_build.py."""
from __future__ import annotations

import re
from pathlib import Path

import gradio as gr
import pytest

from twin import clients, gpu, prompts
from twin.gpu import MANAGER
from twin.pipelines import evals
from twin.ui import evals as evals_ui
from twin.ui import frame, state
from twin.ui import status as status_ui

ROOT = Path(__file__).resolve().parent.parent
PARTIALS = {"eval": ROOT / "static" / "tabs" / "eval.css", "status": ROOT / "static" / "tabs" / "status.css"}
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
_DEMO: dict = {}

EVAL_LABELS = {"use_claude": "Use Claude ceiling judge (needs ANTHROPIC_API_KEY)", "summary": "Voice bake-off",
               "retrieval": "Retrieval bake-off", "candidate": "Candidate", "qid": "Eval question",
               "condition": "Condition", "live_json": "Live result"}
EVAL_BUTTONS = {"refresh_btn": "Refresh", "voice_btn": "Re-run voice bake-off (~6 min)",
                "retrieval_btn": "Re-run retrieval bake-off", "live_btn": "Live: one candidate x one question (~15 s)"}
STATUS_LABELS = {"warm_dd": "Tab to warm", "telemetry": f"Telemetry (last {state.TELEMETRY_ROWS} calls)",
                 "audit": f"Audit tail (last {status_ui.AUDIT_ROWS} requests, newest first)"}
STATUS_BUTTONS = {"free_btn": "Free GPU", "warm_btn": "Warm current tab", "refresh_btn": "Refresh",
                  "rebuild_btn": "Rebuild index + digest", "rebuild_digest_btn": "Rebuild digest (force, qwen3:8b)",
                  "audit_btn": "Refresh audit tail", "redaction_btn": "Refresh redaction report"}


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
    saved = (MANAGER.active_tab, MANAGER.last_model_tab, dict(MANAGER.tab_overrides))
    yield
    MANAGER.active_tab, MANAGER.last_model_tab = saved[0], saved[1]
    MANAGER.tab_overrides.clear()
    MANAGER.tab_overrides.update(saved[2])


def _demo() -> gr.Blocks:
    if "demo" not in _DEMO:
        _DEMO["demo"] = frame.build_app()
    return _DEMO["demo"]


def _descendants(block) -> list:
    out = []
    for child in getattr(block, "children", None) or []:
        out.append(child)
        out.extend(_descendants(child))
    return out


def _by_elem_id(block) -> dict:
    return {b.elem_id: b for b in _descendants(block) if getattr(b, "elem_id", None)}


def _classes(comp) -> list[str]:
    return list(comp.elem_classes or [])


def _ids(comps) -> list[int]:
    return [c._id for c in comps]


def _public(demo) -> dict:
    return {fn.api_name: fn for fn in demo.fns.values() if fn.api_visibility != "private"}


# ---- the DEMO CONTRACT: labels, values, choices ------------------------------------------------------------------
def test_labels_values_and_choices_unchanged():
    parts = _demo().twin_parts
    ev, st = parts["eval"], parts["status"]
    for key, label in EVAL_LABELS.items():
        assert ev[key].label == label, key
    for key, text in EVAL_BUTTONS.items():
        assert ev[key].value == text, key
    for key, label in STATUS_LABELS.items():
        assert st[key].label == label, key
    for key, text in STATUS_BUTTONS.items():
        assert st[key].value == text, key
    assert [c[1] for c in ev["condition"].choices] == list(prompts.CONDITIONS)
    assert ev["condition"].value == prompts.DEFAULT_CONDITION
    assert ev["candidate"].value == evals.CANDIDATES[0]
    assert [c[1] for c in st["warm_dd"].choices] == list(state.WARM_CHOICES) and st["warm_dd"].value == "active"
    assert list(ev["summary"].headers) == list(evals.SUMMARY_HEADERS)
    assert list(ev["retrieval"].headers) == list(evals.RETRIEVAL_HEADERS)
    assert list(st["telemetry"].headers) == list(state.TELEMETRY_HEADERS)
    assert list(st["audit"].headers) == list(status_ui.AUDIT_HEADERS)


# ---- the DEMO CONTRACT: api_names, queues, triggers, inputs and outputs -------------------------------------------
def test_event_wiring_unchanged():
    demo = _demo()
    ev, st = demo.twin_parts["eval"], demo.twin_parts["status"]
    header_md = next(b for b in demo.blocks.values() if getattr(b, "elem_id", None) == "twin-header")
    pub = _public(demo)
    expected = {   # api_name: (trigger, inputs, outputs, on the gpu queue)
        "eval_show": (ev["refresh_btn"], [], [ev["summary"], ev["retrieval"]], False),
        "eval_voice_rerun": (ev["voice_btn"], [ev["use_claude"]], [ev["summary"], ev["retrieval"], ev["note"]], True),
        "eval_retrieval_rerun": (ev["retrieval_btn"], [], [ev["summary"], ev["retrieval"], ev["note"]], True),
        "eval_live": (ev["live_btn"], [ev["candidate"], ev["qid"], ev["condition"]], [ev["live_json"]], True),
        "status": (st["refresh_btn"], [], [st["md"], st["telemetry"]], False),
        "free_gpu": (st["free_btn"], [], [st["md"]], True),
        "warm": (st["warm_btn"], [st["warm_dd"]], [st["md"]], True),
        "rebuild_index": (st["rebuild_btn"], [], [st["md"], header_md], True),
        "rebuild_digest": (st["rebuild_digest_btn"], [], [st["md"], header_md], True),
        "audit_tail": (st["audit_btn"], [], [st["audit"], st["audit_counts"]], False),
        "redaction_report": (st["redaction_btn"], [], [st["redaction"]], False),
    }
    for name, (trigger, ins, outs, gpu_queue) in expected.items():
        fn = pub[name]
        assert list(fn.targets) == [(trigger._id, "click")], name
        assert _ids(fn.inputs) == _ids(ins), name
        assert _ids(fn.outputs) == _ids(outs), name
        assert (fn.concurrency_id == "gpu") is gpu_queue, name
    private = [fn for fn in demo.fns.values() if fn.api_visibility == "private"]
    follow_ups = [fn for fn in private if _ids(fn.outputs) == [ev["probes"]._id]]
    assert len(follow_ups) == 2
    assert all(fn.fn is evals_ui.probes_markdown and fn.trigger_after is not None for fn in follow_ups)
    assert {pub["eval_show"]._id, pub["eval_voice_rerun"]._id} == {fn.trigger_after for fn in follow_ups}
    ticks = [fn for fn in private if _ids(fn.outputs) == _ids([st["md"], st["telemetry"]])]
    assert len(ticks) == 1 and ticks[0].fn is status_ui.status_refresh and ticks[0].concurrency_id != "gpu"
    assert all(isinstance(demo.blocks[i], gr.Timer) and e == "tick" for i, e in ticks[0].targets)
    # the Nocturne tiles add one private, GET-only tick on the same timer (docs/design/tokens.md section 5)
    tile_ticks = [fn for fn in private if _ids(fn.outputs) == [st["tiles"]._id]]
    assert len(tile_ticks) == 1 and tile_ticks[0].fn is status_ui.status_tiles_handler
    assert tile_ticks[0].concurrency_id != "gpu" and tile_ticks[0].targets == ticks[0].targets
    # only the two probes follow-ups and the two ticks write to these tabs privately
    mine = {c._id for c in list(ev.values()) + list(st.values())}
    assert len([fn for fn in private if {c._id for c in fn.outputs} & mine]) == 4


def test_status_tiles_html_reads_the_status_dict():
    st = {**FIXED_STATUS, "gpu": "3174 MiB, 8192 MiB, 12 %", "active_tab": "ask", "active_key": "stheno_q4",
          "lms_models": [{"id": "l3-8b-stheno-v3.2", "type": "llm", "state": "loaded"}]}
    out = status_ui.status_tiles_html(st)
    assert out.startswith("<dl>") and out.endswith("</dl>")
    assert "<dt>GPU memory</dt><dd>3.1 of 8 GB" in out and 'style="width: 39%"' in out and "12% utilisation" in out
    assert '<div data-state="ok"><dt>Heartbeat</dt><dd>ready</dd><dd>active tab ask, stheno_q4</dd>' in out
    assert "<dd>1 loaded</dd><dd>l3-8b-stheno-v3.2</dd>" in out and "<dt>Ollama</dt><dd>nothing loaded</dd>" in out
    empty = status_ui.status_tiles_html(dict(FIXED_STATUS))
    assert "<dd>n/a</dd>" in empty and "data-meter" not in empty and "<div><dt>Heartbeat</dt><dd>idle</dd>" in empty
    assert status_ui.status_tiles_handler() == empty


# ---- restyle hooks: Eval ------------------------------------------------------------------------------------------
def test_eval_ids_classes_and_hierarchy():
    ev = _demo().twin_parts["eval"]
    assert ev["tab"].elem_id == "tab-eval"
    assert ev["probes"].elem_id == "eval-probes" and ev["condition"].elem_id == "eval-condition"
    assert ev["summary"].elem_id == "eval-summary" and ev["retrieval"].elem_id == "eval-retrieval"
    for key in ("summary", "retrieval"):
        assert "twin-table" in _classes(ev[key]), key
    assert "eval-md-table" in _classes(ev["probes"])
    assert {"twin-hint", "eval-md-table"} <= set(_classes(ev["note"]))
    assert ev["refresh_btn"].elem_id == "eval-refresh" and ev["refresh_btn"].variant == "secondary"
    for key in ("voice_btn", "retrieval_btn", "live_btn"):
        assert "twin-caution" in _classes(ev[key]) and ev[key].variant != "primary", key
    blocks = _by_elem_id(ev["tab"])
    assert {"eval-intro", "eval-options", "eval-use-claude", "eval-actions", "eval-note", "eval-live",
            "eval-live-controls", "eval-live-run", "eval-live-result"} <= set(blocks)
    assert "twin-intro" in _classes(blocks["eval-intro"]) and "twin-panel" in _classes(blocks["eval-live"])
    assert ev["use_claude"] in _descendants(blocks["eval-options"])
    buttons = [b for b in _descendants(ev["tab"]) if isinstance(b, gr.Button)]
    assert len(buttons) == 4 and [b.value for b in buttons if b.variant == "primary"] == []
    # Refresh first, the two re-runs after it in the same action row (DEMO.md B7.1)
    row = blocks["eval-actions"]
    assert "twin-actions" in _classes(row)
    assert [b.value for b in _descendants(row) if isinstance(b, gr.Button)] == [
        "Refresh", "Re-run voice bake-off (~6 min)", "Re-run retrieval bake-off"]
    assert [b.value for b in _descendants(blocks["eval-live-controls"]) if isinstance(b, gr.Button)] == [
        "Live: one candidate x one question (~15 s)"]


# ---- restyle hooks: Status ----------------------------------------------------------------------------------------
def test_status_ids_classes_and_hierarchy():
    st = _demo().twin_parts["status"]
    assert st["tab"].elem_id == "tab-status"
    assert st["md"].elem_id == "status-md" and "twin-card" in _classes(st["md"])
    for key in ("audit", "telemetry"):
        assert "twin-table" in _classes(st[key]), key
    assert st["free_btn"].variant == "primary" and st["free_btn"].elem_id == "status-free-gpu"
    buttons = [b for b in _descendants(st["tab"]) if isinstance(b, gr.Button)]
    assert len(buttons) == 9 and [b.value for b in buttons if b.variant == "primary"] == ["Free GPU"]
    for key in ("rebuild_btn", "rebuild_digest_btn", "persona_switch_btn"):
        assert "twin-caution" in _classes(st[key]), key
    assert "twin-caution" not in _classes(st["persona_import_btn"])
    assert "twin-quiet" in _classes(st["refresh_btn"])
    blocks = _by_elem_id(st["tab"])
    assert {"status-safeguards", "status-audit", "status-redaction", "status-audit-counts", "status-audit-tail",
            "status-redaction-report", "status-controls", "status-maintenance", "status-persona",
            "status-telemetry"} <= set(blocks)
    assert "twin-split" in _classes(blocks["status-safeguards"])
    # Free GPU is the first control of its row, then the dropdown, Warm current tab and Refresh (DEMO.md B8.2)
    controls = [c for c in _descendants(blocks["status-controls"]) if isinstance(c, (gr.Button, gr.Dropdown))]
    assert [c.label if isinstance(c, gr.Dropdown) else c.value for c in controls] == [
        "Free GPU", "Tab to warm", "Warm current tab", "Refresh"]
    assert [b.value for b in _descendants(blocks["status-maintenance"]) if isinstance(b, gr.Button)] == [
        "Rebuild index + digest", "Rebuild digest (force, qwen3:8b)"]
    # Persona dropdown, Switch, the .md file uploader and Import, in that order (this task's persona switcher)
    persona_controls = [c for c in _descendants(blocks["status-persona"]) if isinstance(c, (gr.Button, gr.Dropdown))]
    assert [c.label if isinstance(c, gr.Dropdown) else c.value for c in persona_controls] == [
        "Persona", "Switch persona", "Import persona"]
    assert st["persona_file"].label == "Import persona (.md)"


# ---- the partials target only what the tabs render ----------------------------------------------------------------
def test_partials_target_ids_and_classes_the_tabs_render():
    demo = _demo()
    ids = {b.elem_id for b in demo.blocks.values() if getattr(b, "elem_id", None)}
    for tab, path in PARTIALS.items():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        used_ids = set(re.findall(r"#([A-Za-z][\w-]*)", css))
        assert f"tab-{tab}" in used_ids, path.name
        assert used_ids <= ids, (path.name, sorted(used_ids - ids))
        tab_classes = {c for b in _descendants(demo.twin_parts[tab]["tab"]) for c in (getattr(b, "elem_classes", None) or [])}
        used_classes = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
        assert used_classes <= tab_classes, (path.name, sorted(used_classes - tab_classes))


def test_partials_keep_selector_lists_at_the_top_level():
    """Gradio 6.27 re-emits custom CSS under a prefix and splits comma lists inside :is()/:not()/:where()/:has(), which
    inflates the specificity of the prefixed copy; these partials write selector lists out at the top level instead."""
    for path in PARTIALS.values():
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for m in re.finditer(r":(?:is|not|where|has)\(([^()]*)\)", css):
            assert "," not in m.group(1), (path.name, m.group(0))
