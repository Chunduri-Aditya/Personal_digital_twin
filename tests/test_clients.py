"""Tests for twin.clients request bodies without any network: `_chat_body` is pure, `embed` goes through an
httpx.MockTransport, LMSClient uses a fake OpenAI client, and GET helpers use a fake httpx.get.
Telemetry is redirected to a list so data/telemetry.jsonl is never written.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from twin import clients, telemetry
from twin.config import spec

USER = [{"role": "user", "content": "hi"}]
SYS_USER = [{"role": "system", "content": "You are X."}, {"role": "user", "content": "hi"}]


@pytest.fixture
def recs(monkeypatch):
    out: list = []
    monkeypatch.setattr(telemetry, "record", lambda rec: out.append(rec))
    return out


def body_for(key, messages, options=None, format=None, tools=None, num_predict=None, stream=False, images=None):
    return clients.ollama._chat_body(key, messages, options, format, tools, num_predict, stream, images)


# ---------------------------------------------------------------------------
# OllamaClient._chat_body
# ---------------------------------------------------------------------------

def test_chat_body_qwen3_8k_defaults():
    s, b = body_for("qwen3_8k", USER)
    assert s.key == "qwen3_8k" and b["model"] == "qwen3-8b-8k"
    assert b["think"] is False
    assert b["options"] == {"temperature": 0.2, "num_ctx": 8192}
    assert b["keep_alive"] == "10m" and b["stream"] is False
    assert b["messages"] == USER and b["messages"] is not USER
    assert "format" not in b and "tools" not in b
    assert set(b) == {"model", "messages", "stream", "options", "keep_alive", "think"}


def test_chat_body_merges_samplers_under_caller_options_and_pins_num_ctx():
    _, b = body_for("qwen3_8k", USER, options={"temperature": 0, "top_p": 0.9, "num_ctx": 999}, num_predict=200)
    assert b["options"] == {"temperature": 0, "top_p": 0.9, "num_ctx": 8192, "num_predict": 200}
    _, b2 = body_for("stheno_q8", SYS_USER, options={"temperature": 1.0})
    assert b2["options"] == {"temperature": 1.0, "min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1, "num_ctx": 8192}
    assert b2["keep_alive"] == "10m" and "think" not in b2
    _, b3 = body_for("qwen3_long", USER, num_predict=400)
    assert b3["options"] == {"temperature": 0.3, "num_ctx": 40960, "num_predict": 400}
    assert b3["keep_alive"] == 0 and b3["think"] is False
    _, b4 = body_for("llama32_3b", USER, options={"temperature": 0.8}, num_predict=300)
    assert b4["options"] == {"temperature": 0.8, "num_ctx": 4096, "num_predict": 300} and b4["keep_alive"] == "30m"
    assert "think" not in b4


@pytest.mark.parametrize("key", ["llama31", "qwen25", "hermes3", "llama32_1b", "stheno_q8"])
def test_chat_body_think_only_when_spec_says_false(key):
    msgs = SYS_USER if key == "stheno_q8" else USER
    _, b = body_for(key, msgs)
    assert "think" not in b, key
    assert b["options"]["num_ctx"] == spec(key).num_ctx
    assert b["keep_alive"] == spec(key).keep_alive
    assert b["model"] == spec(key).name


def test_chat_body_stheno_q8_requires_system_message():
    with pytest.raises(ValueError, match="system message"):
        body_for("stheno_q8", USER)
    with pytest.raises(ValueError):
        body_for("stheno_q8", [])
    _, b = body_for("stheno_q8", SYS_USER)
    assert b["messages"][0]["role"] == "system"


def test_chat_body_rejects_non_ollama_keys():
    for key in ("stheno_q4", "nomic_lms", "claude"):
        with pytest.raises(ValueError, match="not an Ollama model"):
            body_for(key, USER)


def test_chat_body_format_tools_and_images_placement():
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {}}}}]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "first"},
            {"role": "assistant", "content": "a"}, {"role": "user", "content": "look"}]
    _, b = body_for("hermes3", msgs, format=schema, tools=tools, stream=True, images=["QUJD"])
    assert b["format"] == schema and b["tools"] == tools and b["stream"] is True
    assert b["messages"][-1] == {"role": "user", "content": "look", "images": ["QUJD"]}
    assert "images" not in b["messages"][1] and "images" not in b["messages"][2]
    assert "images" not in msgs[-1], "the caller's messages are not mutated"
    _, b2 = body_for("hermes3", msgs, format="json")
    assert b2["format"] == "json" and "tools" not in b2
    _, b3 = body_for("hermes3", msgs, images=[])
    assert all("images" not in m for m in b3["messages"])


# ---------------------------------------------------------------------------
# OllamaClient.embed (httpx.MockTransport)
# ---------------------------------------------------------------------------

def _embed_client(handler) -> clients.OllamaClient:
    c = clients.OllamaClient()
    c._http = httpx.Client(transport=httpx.MockTransport(handler), base_url=c.base_url)
    return c


def test_embed_batches_of_32_with_num_ctx_and_keep_alive(recs):
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"path": request.url.path, "body": body})
        vecs = [[float(i), 1.0, 0.0, 0.0] for i, _ in enumerate(body["input"])]
        return httpx.Response(200, json={"model": body["model"], "embeddings": vecs, "load_duration": 5_000_000,
                                         "prompt_eval_count": len(body["input"])})

    c = _embed_client(handler)
    inputs = [f"search_document: text {i}" for i in range(70)]
    out = c.embed("nomic_ollama", inputs, tab="index")
    assert isinstance(out, np.ndarray) and out.dtype == np.float32 and out.shape == (70, 4)
    assert [len(r["body"]["input"]) for r in requests] == [32, 32, 6]
    assert [r["path"] for r in requests] == ["/api/embed"] * 3
    for r in requests:
        b = r["body"]
        assert b["model"] == "nomic-embed-text"
        assert b["options"] == {"num_ctx": 2048} and b["keep_alive"] == "30m"
        assert set(b) == {"model", "input", "options", "keep_alive"}
    assert requests[0]["body"]["input"][0] == inputs[0] and requests[2]["body"]["input"][-1] == inputs[-1]
    assert out[33].tolist() == [1.0, 1.0, 0.0, 0.0]      # second batch, second row
    assert len(recs) == 3 and all(r.ok and r.model == "nomic-embed-text" and r.tab == "index" for r in recs)
    assert recs[0].prompt_tokens == 32


def test_embed_gemma_spec_and_empty_input(recs):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"embeddings": [[0.5, 0.5]] * len(body["input"])})

    c = _embed_client(handler)
    assert c.embed("embeddinggemma", ["a", "b"]).shape == (2, 2)
    assert seen[0]["model"] == "embeddinggemma:300m-qat-q4_0" and seen[0]["options"] == {"num_ctx": 2048}
    assert seen[0]["keep_alive"] == "30m"
    empty = c.embed("embeddinggemma", [])
    assert empty.shape == (0, 0) and len(seen) == 1, "no request for an empty batch"


def test_embed_http_error_and_runtime_mismatch(recs):
    c = _embed_client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(clients.OllamaError, match="HTTP 500"):
        c.embed("nomic_ollama", ["x"])
    assert len(recs) == 1 and recs[0].ok is False and "HTTP 500" in recs[0].error
    with pytest.raises(ValueError, match="not an Ollama model"):
        c.embed("nomic_lms", ["x"])
    with pytest.raises(ValueError):
        c.embed("stheno_q4", ["x"])


def test_chat_posts_body_and_records_telemetry(recs):
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append({"path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(200, json={"model": "qwen3-8b-8k", "message": {"role": "assistant", "content": "ok"},
                                         "done": True, "prompt_eval_count": 7, "eval_count": 3, "eval_duration": 1e9,
                                         "load_duration": 2e6})

    c = _embed_client(handler)
    data = c.chat("qwen3_8k", USER, options={"temperature": 0}, num_predict=40, tab="decide")
    assert data["message"]["content"] == "ok"
    assert posted[0]["path"] == "/api/chat"
    assert posted[0]["body"] == body_for("qwen3_8k", USER, options={"temperature": 0}, num_predict=40)[1]
    assert len(recs) == 1 and recs[0].ok and recs[0].prompt_tokens == 7 and recs[0].eval_tokens == 3
    assert recs[0].tab == "decide" and recs[0].runtime == "ollama"


# ---------------------------------------------------------------------------
# LMSClient
# ---------------------------------------------------------------------------

class FakeOpenAI:
    def __init__(self, content="yo"):
        self.kwargs: list[dict] = []
        self.content = content
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)
        self.embeddings = SimpleNamespace(create=self._embed)

    def _create(self, **kw):
        self.kwargs.append(kw)
        if kw.get("stream"):
            return iter([])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
                               usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4))

    def _embed(self, **kw):
        self.kwargs.append(kw)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 0.0]) for _ in kw["input"]],
                               usage=SimpleNamespace(prompt_tokens=3))


def _lms(fake: FakeOpenAI, loaded: bool = True) -> clients.LMSClient:
    c = clients.LMSClient()
    c._client = fake
    c._is_loaded = lambda name: loaded  # no GET /api/v0/models from the body tests
    return c


def test_lms_load_ms_from_models_v0_state(recs, monkeypatch):
    """LM Studio reports no load time: a call on a not-loaded model records its wall time as load_ms."""
    state = {"l3-8b-stheno-v3.2": "not-loaded", "text-embedding-nomic-embed-text-v1.5": "not-loaded"}
    urls: list[tuple] = []

    def fake_get(url, timeout=None, **kw):
        urls.append((url, timeout))
        data = [{"id": k, "state": v} for k, v in state.items()]
        return SimpleNamespace(status_code=200, json=lambda: {"data": data})

    monkeypatch.setattr(clients.httpx, "get", fake_get)
    fake = FakeOpenAI()
    c = clients.LMSClient()
    c._client = fake
    c.chat("stheno_q4", SYS_USER, tab="ask")
    assert urls == [("http://127.0.0.1:1234/api/v0/models", 2.0)]
    assert recs[-1].load_ms > 0 and recs[-1].load_ms <= recs[-1].wall_ms
    state["l3-8b-stheno-v3.2"] = "loaded"
    c.chat("stheno_q4", SYS_USER, tab="ask")
    assert recs[-1].load_ms == 0.0
    c.chat("stheno_q4", SYS_USER, stream=True)
    assert recs[-1].load_ms == 0.0
    # embed: only the first batch carries the load
    c.embed("nomic_lms", [f"t{i}" for i in range(40)], tab="act")
    assert [r.load_ms > 0 for r in recs[-2:]] == [True, False]
    # request bodies are untouched
    assert set(fake.kwargs[0]) == {"model", "messages", "temperature", "max_tokens", "stream", "extra_body"}
    # the state endpoint failing never attributes a load
    monkeypatch.setattr(clients.httpx, "get", lambda url, timeout=None, **kw: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    state["l3-8b-stheno-v3.2"] = "not-loaded"
    c.chat("stheno_q4", SYS_USER)
    assert recs[-1].load_ms == 0.0 and recs[-1].ok


def test_lms_chat_extra_body_and_defaults(recs):
    fake = FakeOpenAI()
    c = _lms(fake)
    resp = c.chat("stheno_q4", SYS_USER, tab="ask")
    assert resp.choices[0].message.content == "yo"
    kw = fake.kwargs[0]
    assert kw["model"] == "l3-8b-stheno-v3.2"
    assert kw["messages"] == SYS_USER
    assert kw["temperature"] == 1.15 and kw["max_tokens"] == 300 and kw["stream"] is False
    assert kw["extra_body"] == {"min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1}
    assert set(kw) == {"model", "messages", "temperature", "max_tokens", "stream", "extra_body"}
    assert len(recs) == 1 and recs[0].ok and recs[0].model == "l3-8b-stheno-v3.2" and recs[0].runtime == "lms"
    assert recs[0].prompt_tokens == 11 and recs[0].eval_tokens == 4 and recs[0].tab == "ask"


def test_lms_chat_overrides_and_stream(recs):
    fake = FakeOpenAI()
    c = _lms(fake)
    c.chat("stheno_q4", SYS_USER, temperature=1.22, max_tokens=120, extra={"top_k": 40, "seed": 7})
    kw = fake.kwargs[0]
    assert kw["temperature"] == 1.22 and kw["max_tokens"] == 120
    assert kw["extra_body"] == {"min_p": 0.075, "top_k": 40, "repeat_penalty": 1.1, "seed": 7}
    out = c.chat("stheno_q4", SYS_USER, stream=True)
    assert fake.kwargs[1]["stream"] is True and hasattr(out, "__next__")
    assert len(recs) == 2 and all(r.ok for r in recs)


def test_lms_chat_rejects_non_lms_keys_and_records_errors(recs):
    c = _lms(FakeOpenAI())
    with pytest.raises(ValueError, match="not an LM Studio model"):
        c.chat("qwen3_8k", USER)
    assert recs == []

    class Boom(FakeOpenAI):
        def _create(self, **kw):
            raise RuntimeError("connection refused")

    with pytest.raises(RuntimeError):
        _lms(Boom()).chat("stheno_q4", SYS_USER, tab="ask")
    assert len(recs) == 1 and recs[0].ok is False and "connection refused" in recs[0].error


def test_lms_embed_batches_and_model(recs):
    fake = FakeOpenAI()
    c = _lms(fake)
    out = c.embed("nomic_lms", [f"t{i}" for i in range(40)], tab="act")
    assert out.shape == (40, 2) and out.dtype == np.float32
    assert [len(k["input"]) for k in fake.kwargs] == [32, 8]
    assert all(k["model"] == "text-embedding-nomic-embed-text-v1.5" for k in fake.kwargs)
    assert c.embed("nomic_lms", []).shape == (0, 0)
    with pytest.raises(ValueError):
        c.embed("nomic_ollama", ["x"])


def test_models_v0_and_loaded_parse_fake_response(monkeypatch):
    payload = {"data": [
        {"id": "l3-8b-stheno-v3.2", "state": "loaded", "type": "llm"},
        {"id": "text-embedding-nomic-embed-text-v1.5", "state": "not-loaded", "type": "embeddings"},
        {"id": "hermes3", "state": "loaded"},
    ]}
    urls: list[tuple] = []

    class FakeResp:
        def __init__(self, status=200, data=None):
            self.status_code = status
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("bad", request=None, response=None)

        def json(self):
            return self._data

    def fake_get(url, timeout=None, **kw):
        urls.append((url, timeout))
        if url.endswith("/api/v0/models"):
            return FakeResp(200, payload)
        if url.endswith("/v1/models"):
            return FakeResp(200, {"data": [{"id": "a"}, {"id": "b"}, "junk"]})
        return FakeResp(404, {})

    monkeypatch.setattr(clients.httpx, "get", fake_get)
    c = clients.LMSClient()
    assert c.models_v0() == payload["data"]
    assert c.loaded() == ["l3-8b-stheno-v3.2", "hermes3"]
    assert c.models_v1() == ["a", "b"]
    assert c.alive() is True
    assert urls[0] == ("http://127.0.0.1:1234/api/v0/models", 10.0)
    assert urls[-1] == ("http://127.0.0.1:1234/api/v0/models", 2.0)
    monkeypatch.setattr(clients.httpx, "get", lambda url, timeout=None, **kw: FakeResp(200, {}))
    assert clients.LMSClient().models_v0() == [] and clients.LMSClient().loaded() == []

    def down(url, timeout=None, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(clients.httpx, "get", down)
    assert clients.LMSClient().alive() is False
    assert clients.OllamaClient.alive(SimpleNamespace(base_url="http://127.0.0.1:11434")) is False
    with pytest.raises(httpx.ConnectError):
        clients.LMSClient().models_v0()


def test_ollama_ps_tags_show_parse_fake_http():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen3-8b-8k:latest"}]})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": None})
        return httpx.Response(200, json={"details": {"family": "qwen3"}})

    c = _embed_client(handler)
    assert c.ps() == [{"name": "qwen3-8b-8k:latest"}]
    assert c.tags() == []
    assert c.show("qwen3-8b-8k")["details"]["family"] == "qwen3"
    assert seen == ["GET /api/ps", "GET /api/tags", "POST /api/show"]


# ---------------------------------------------------------------------------
# AnthropicClient
# ---------------------------------------------------------------------------

def test_anthropic_available_false_without_env_var_and_never_prints_the_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = clients.AnthropicClient()
    assert c.available() is False
    dummy = "sk-ant-test-dummy-value-not-a-real-key-0000"
    monkeypatch.setenv("ANTHROPIC_API_KEY", dummy)
    try:
        import anthropic  # noqa: F401
        installed = True
    except ImportError:
        installed = False
    assert c.available() is installed
    out = capsys.readouterr()
    assert dummy not in out.out and dummy not in out.err
    assert "sk-ant" not in out.out and "sk-ant" not in out.err
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert c.available() is False


def test_module_level_clients_exist():
    assert isinstance(clients.ollama, clients.OllamaClient)
    assert isinstance(clients.lms, clients.LMSClient)
    assert isinstance(clients.anthropic_client, clients.AnthropicClient)
    assert clients.ollama.base_url == "http://127.0.0.1:11434" and clients.lms.base_url == "http://127.0.0.1:1234"
    assert clients._BATCH == 32
