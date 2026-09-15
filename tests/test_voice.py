"""Hermetic tests for twin.pipelines.voice.reply_in_voice: exact LM Studio and Ollama fallback request bodies.

The LM Studio fake builds the body LMSClient.chat would send; the Ollama fake uses the real client's pure
`_chat_body`. No network, no GPU.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from twin import clients, gpu
from twin.config import spec
from twin.pipelines import voice

_REAL_OLLAMA = clients.ollama
MESSAGES = [{"role": "system", "content": "You are Ari."}, {"role": "user", "content": "say it"}]


class FakeLMS:
    def __init__(self, replies=("yo. the boring one",), alive=True):
        self.calls: list[dict] = []
        self.replies = list(replies)
        self.alive_flag = alive
        self.raise_exc: BaseException | None = None

    def alive(self) -> bool:
        return self.alive_flag

    def chat(self, key, messages, *, temperature=None, max_tokens=300, stream=False, extra=None, tab=""):
        s = spec(key)
        assert s.runtime == "lms", key
        extra_body = {k: v for k, v in s.samplers.items() if k in ("min_p", "top_k", "repeat_penalty")}
        extra_body.update(extra or {})
        if temperature is None:
            temperature = s.samplers.get("temperature", 1.0)
        body = {"model": s.name, "messages": copy.deepcopy(messages), "temperature": temperature,
                "max_tokens": max_tokens, "stream": stream, "extra_body": extra_body}
        self.calls.append({"key": key, "body": body, "tab": tab})
        if self.raise_exc is not None:
            raise self.raise_exc
        content = self.replies.pop(0) if self.replies else "yo. lms reply"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class FakeOllama:
    def __init__(self, replies=("the boring one, lasts four years",)):
        self.calls: list[dict] = []
        self.replies = list(replies)

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = _REAL_OLLAMA._chat_body(key, messages, options, format, tools, num_predict, stream,
                                          images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        content = self.replies.pop(0) if self.replies else "ok"
        return {"model": s.name, "message": {"role": "assistant", "content": content}, "done": True,
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9,
                "load_duration": 0}


@pytest.fixture
def env(monkeypatch):
    lms = FakeLMS()
    ollama = FakeOllama()
    ensured: list[str] = []
    monkeypatch.setattr(clients, "lms", lms)
    monkeypatch.setattr(clients, "ollama", ollama)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    return SimpleNamespace(lms=lms, ollama=ollama, ensured=ensured)


def test_lms_path_request_body(env):
    text, key = voice.reply_in_voice(MESSAGES, max_tokens=120, tab="decide", temperature=1.0)
    assert (text, key) == ("yo. the boring one", "stheno_q4")
    assert env.ollama.calls == []
    assert len(env.lms.calls) == 1
    c = env.lms.calls[0]
    assert c["key"] == "stheno_q4" and c["tab"] == "decide"
    b = c["body"]
    assert b["model"] == "l3-8b-stheno-v3.2"
    assert b["temperature"] == 1.0 and b["max_tokens"] == 120 and b["stream"] is False
    assert b["extra_body"] == {"min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1}
    assert b["messages"] == MESSAGES
    assert env.ensured == ["stheno_q4"], "the call runs inside MANAGER.session('stheno_q4')"


def test_lms_path_temperature_passthrough_and_default(env):
    voice.reply_in_voice(MESSAGES, max_tokens=50, tab="act", temperature=1.22)
    assert env.lms.calls[0]["body"]["temperature"] == 1.22 and env.lms.calls[0]["tab"] == "act"
    voice.reply_in_voice(MESSAGES, max_tokens=50, tab="act")
    assert env.lms.calls[1]["body"]["temperature"] == 1.0


def test_lms_path_retries_once_on_empty_then_returns_empty(env):
    env.lms.replies = ["", "second try"]
    text, key = voice.reply_in_voice(MESSAGES, max_tokens=80, tab="decide")
    assert (text, key) == ("second try", "stheno_q4")
    assert len(env.lms.calls) == 2
    assert env.lms.calls[0]["body"] == env.lms.calls[1]["body"]
    assert env.ensured == ["stheno_q4"], "the retry stays inside the same session"
    assert env.ollama.calls == []
    env.lms.calls.clear()
    env.lms.replies = ["", "   "]
    text, key = voice.reply_in_voice(MESSAGES, max_tokens=80, tab="decide")
    assert key == "stheno_q4" and text.strip() == ""
    assert len(env.lms.calls) == 2, "exactly one retry, and an empty LM Studio reply does not fall back"
    assert env.ollama.calls == []


def test_fallback_when_lms_is_down(env):
    env.lms.alive_flag = False
    text, key = voice.reply_in_voice(MESSAGES, max_tokens=120, tab="decide")
    assert (text, key) == ("the boring one, lasts four years", "llama32_3b")
    assert env.lms.calls == []
    assert len(env.ollama.calls) == 1
    c = env.ollama.calls[0]
    assert c["key"] == "llama32_3b" and c["tab"] == "decide"
    b = c["body"]
    assert b["model"] == "llama3.2:3b"
    assert b["options"] == {"temperature": 0.8, "num_ctx": 4096, "num_predict": 120}
    assert b["keep_alive"] == "30m" and b["stream"] is False
    assert "think" not in b and "format" not in b and "tools" not in b
    assert b["messages"] == MESSAGES
    assert env.ensured == ["llama32_3b"]


def test_fallback_when_lms_call_raises(env):
    env.lms.raise_exc = RuntimeError("connection refused")
    text, key = voice.reply_in_voice(MESSAGES, max_tokens=90, tab="act", temperature=1.15)
    assert key == "llama32_3b" and text == "the boring one, lasts four years"
    assert len(env.lms.calls) == 1, "LM Studio was tried once"
    b = env.ollama.calls[0]["body"]
    assert b["options"] == {"temperature": 0.8, "num_ctx": 4096, "num_predict": 90}
    assert b["keep_alive"] == "30m" and b["model"] == "llama3.2:3b"
    assert env.ensured == ["stheno_q4", "llama32_3b"]
    assert gpu.MANAGER.lock.acquire(blocking=False), "the LM Studio session released the lock"
    gpu.MANAGER.lock.release()


def test_fallback_retries_once_on_empty(env):
    env.lms.alive_flag = False
    env.ollama.replies = ["", "second"]
    text, key = voice.reply_in_voice(MESSAGES, max_tokens=60, tab="decide")
    assert (text, key) == ("second", "llama32_3b")
    assert len(env.ollama.calls) == 2
    assert env.ollama.calls[0]["body"] == env.ollama.calls[1]["body"]
    assert env.ensured == ["llama32_3b"]
    env.ollama.calls.clear()
    env.ollama.replies = ["", ""]
    assert voice.reply_in_voice(MESSAGES, max_tokens=60, tab="decide") == ("", "llama32_3b")
    assert len(env.ollama.calls) == 2


def test_lms_down_semantics(env, monkeypatch):
    assert voice.lms_down() is False
    env.lms.alive_flag = False
    assert voice.lms_down() is True
    monkeypatch.setattr(clients, "lms", SimpleNamespace(chat=env.lms.chat))   # a fake without alive() counts as up
    assert voice.lms_down() is False


def test_constants():
    assert voice.VOICE_KEY == "stheno_q4" and voice.FALLBACK_VOICE_KEY == "llama32_3b"
    assert voice.FALLBACK_TEMPERATURE == 0.8
    assert spec(voice.VOICE_KEY).runtime == "lms" and spec(voice.FALLBACK_VOICE_KEY).runtime == "ollama"
