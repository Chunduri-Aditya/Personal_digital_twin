"""Mocked tests for twin.gpu / twin.config name matching. No network."""
from __future__ import annotations

import pytest

from twin import clients, gpu
from twin.config import by_name


def test_by_name_accepts_latest_suffix():
    assert by_name("nomic-embed-text:latest").key == "nomic_ollama"
    assert by_name("qwen3-8b-8k:latest").key == "qwen3_8k"
    assert by_name("qwen3-8b-8k").key == "qwen3_8k"
    assert by_name("fluffy/l3-8b-stheno-v3.2:q8_0").key == "stheno_q8"
    assert by_name("") is None
    assert by_name("nope:latest") is None


def test_is_big_ollama_classifies_ps_entries():
    assert gpu._is_big_ollama({"name": "nomic-embed-text:latest"}) is False
    assert gpu._is_big_ollama({"name": "llama3.2:1b"}) is False
    assert gpu._is_big_ollama({"name": "qwen3-8b-8k:latest"}) is True
    assert gpu._is_big_ollama({"name": "unknown-model:latest"}) is True  # unknown -> big


def test_ensure_stheno_q4_stops_only_big_ollama(monkeypatch):
    stopped: list[str] = []
    monkeypatch.setattr(clients.ollama, "ps", lambda: [
        {"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest"},
        {"name": "qwen3-8b-8k:latest", "model": "qwen3-8b-8k:latest"},
    ])
    monkeypatch.setattr(clients.ollama, "stop", lambda name: stopped.append(name))
    gpu.ModelManager().ensure("stheno_q4")
    assert stopped == ["qwen3-8b-8k:latest"]


def test_tab_override_and_active_key():
    m = gpu.ModelManager()
    assert m.active_key() is None
    m.set_active_tab("ask")
    assert m.active_key() == "stheno_q4" and m.last_model_tab == "ask"
    m.set_tab_model("ask", "stheno_q8")
    assert m.active_key() == "stheno_q8" and m.tab_key("ask") == "stheno_q8"
    m.set_tab_model("ask", "stheno_q4")          # back to the default clears the override
    assert m.tab_overrides == {} and m.active_key() == "stheno_q4"
    m.set_active_tab("status")                   # monitoring tab: no model, last model tab is kept
    assert m.active_key() is None and m.last_model_tab == "ask"


def test_heartbeat_does_not_stop_stheno_q8_while_ask_uses_q8(monkeypatch):
    stopped: list[str] = []
    warmed: list[str] = []
    unloaded: list[str] = []
    monkeypatch.setattr(clients.ollama, "ps", lambda: [
        {"name": "fluffy/l3-8b-stheno-v3.2:q8_0", "model": "fluffy/l3-8b-stheno-v3.2:q8_0"}])
    monkeypatch.setattr(clients.ollama, "stop", lambda name: stopped.append(name))
    monkeypatch.setattr(clients.ollama, "warm", lambda key: warmed.append(key))
    monkeypatch.setattr(clients.lms, "loaded", lambda: [])
    monkeypatch.setattr(clients.lms, "unload_all", lambda: unloaded.append("all") or "")
    monkeypatch.setattr(clients.lms, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LM Studio chat")))
    m = gpu.ModelManager()
    m.set_active_tab("ask")
    m.set_tab_model("ask", "stheno_q8")
    assert m.heartbeat_tick() == "stheno_q8"
    assert warmed == ["stheno_q8"] and stopped == [] and unloaded == []
    # without the override the tick would re-warm Q4 and evict Q8
    m.set_tab_model("ask", None)
    monkeypatch.setattr(clients.lms, "chat", lambda *a, **k: warmed.append("lms:" + a[0]))
    assert m.heartbeat_tick() == "stheno_q4"
    assert stopped == ["fluffy/l3-8b-stheno-v3.2:q8_0"]


def test_heartbeat_tick_skips_when_no_model_tab():
    m = gpu.ModelManager()
    m.set_active_tab("status")
    assert m.heartbeat_tick() is None


def test_stheno_q8_requires_system_message():
    with pytest.raises(ValueError):
        clients.ollama._chat_body("stheno_q8", [{"role": "user", "content": "hi"}],
                                  None, None, None, None, False, None)
    s, body = clients.ollama._chat_body(
        "stheno_q8", [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}],
        {"num_ctx": 4096}, None, None, None, False, None)
    assert body["options"]["num_ctx"] == s.num_ctx == 8192


def test_runtime_mismatch_raises():
    with pytest.raises(ValueError):
        clients.ollama._chat_body("stheno_q4", [{"role": "user", "content": "hi"}],
                                  None, None, None, None, False, None)
    with pytest.raises(ValueError):
        clients.lms.chat("qwen3_8k", [{"role": "user", "content": "hi"}])
