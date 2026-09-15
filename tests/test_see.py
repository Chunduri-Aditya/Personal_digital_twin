"""Mocked tests for twin.pipelines.see. No network, no GPU: clients, the GPU manager's ensure(),
the index search and the digest loader are all replaced with recorders. Request bodies are built with
the REAL OllamaClient._chat_body so the assertions cover exactly what the server would receive."""
from __future__ import annotations

import base64
import io
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from twin import clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.pipelines import digest, see

VISION_NAME = "qwen3.5:4b-q8_0"
FALLBACK_NAME = "llama3.2:3b"

# Pure request-body builder (no request is ever sent through it).
_BODY = clients.OllamaClient()

CHUNKS = [
    {"id": "Preferences/Free time", "section": "Preferences", "subsection": "Free time", "title": "Free time",
     "text": "weekend bike rides when it doesn't rain", "score": 0.81},
    {"id": "Voice/Sample 5", "section": "Voice", "subsection": "Sample 5", "title": "Sample 5",
     "text": "lol the dog ate the corner of my laptop sleeve. she has taste at least", "score": 0.77},
]
DIGEST_TEXT = "Ari is a dry, understated backend developer who over-researches purchases."


def _ollama_reply(content: str, model: str = VISION_NAME) -> dict:
    return {"model": model, "message": {"role": "assistant", "content": content, "tool_calls": []},
            "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5,
            "eval_duration": 1e9, "load_duration": 0}


def _lms_reply(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=12),
    )


class FakeOllama:
    """Records every chat/stop call with the exact body the real client would post."""

    def __init__(self, log: list, replies: list | None = None, raise_on_chat: Exception | None = None):
        self.log = log
        self.replies = list(replies or [])
        self.raise_on_chat = raise_on_chat
        self.chats: list[dict] = []
        self.stops: list[str] = []

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None,
             stream=False, images_on_last_user=None, tab=""):
        _, body = _BODY._chat_body(key, messages, options, format, tools, num_predict, stream, images_on_last_user)
        self.chats.append({"key": key, "tab": tab, "body": body})
        self.log.append(("ollama.chat", key))
        if self.raise_on_chat is not None:
            raise self.raise_on_chat
        if not self.replies:
            raise AssertionError("FakeOllama ran out of canned replies")
        return self.replies.pop(0)

    def stop(self, name):
        self.stops.append(name)
        self.log.append(("ollama.stop", name))


class FakeLMS:
    """Records every chat call's kwargs; alive() is configurable."""

    def __init__(self, log: list, replies: list | None = None, alive: bool = True,
                 raise_on_chat: Exception | None = None):
        self.log = log
        self.replies = list(replies or [])
        self._alive = alive
        self.raise_on_chat = raise_on_chat
        self.chats: list[dict] = []

    def alive(self):
        self.log.append(("lms.alive", self._alive))
        return self._alive

    def chat(self, key, messages, *, temperature=None, max_tokens=300, stream=False, extra=None, tab=""):
        self.chats.append({"key": key, "messages": [dict(m) for m in messages], "temperature": temperature,
                           "max_tokens": max_tokens, "stream": stream, "extra": extra, "tab": tab})
        self.log.append(("lms.chat", key))
        if self.raise_on_chat is not None:
            raise self.raise_on_chat
        if not self.replies:
            raise AssertionError("FakeLMS ran out of canned replies")
        return self.replies.pop(0)


@pytest.fixture
def env(monkeypatch):
    """Hermetic environment: fakes for both clients, a recording no-op ensure(), fixed retrieval, short digest."""
    log: list = []
    ensured: list[str] = []
    searches: list[dict] = []

    def make(ollama_replies=None, lms_replies=None, lms_alive=True, ollama_raise=None, lms_raise=None):
        fake_ollama = FakeOllama(log, ollama_replies, raise_on_chat=ollama_raise)
        fake_lms = FakeLMS(log, lms_replies, alive=lms_alive, raise_on_chat=lms_raise)
        monkeypatch.setattr(clients, "ollama", fake_ollama)
        monkeypatch.setattr(clients, "lms", fake_lms)

        def ensure(key):
            assert gpu.MANAGER.lock._is_owned(), "ensure() must run inside the manager lock"
            ensured.append(key)
            log.append(("ensure", key))

        monkeypatch.setattr(gpu.MANAGER, "ensure", ensure)

        def search_chunks(index_key, query, k=5, boost=None, tab=""):
            searches.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
            return [dict(c) for c in CHUNKS]

        monkeypatch.setattr(index, "search_chunks", search_chunks)
        monkeypatch.setattr(digest, "load_digest", lambda: DIGEST_TEXT)
        return SimpleNamespace(ollama=fake_ollama, lms=fake_lms, log=log, ensured=ensured, searches=searches)

    # Pin the profile to the example file so the tests do not depend on data/twin_profile.md existing.
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: config.EXAMPLE_PROFILE_PATH)
    see._PROFILE_CACHE.clear()
    return make


def _img(w=2000, h=1000, color=(200, 30, 30)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


# ---- prepare_image --------------------------------------------------------------
def test_prepare_image_resizes_long_side_and_encodes_jpeg():
    b64 = see.prepare_image(_img(2000, 1000))
    assert isinstance(b64, str) and not b64.startswith("data:")
    raw = base64.b64decode(b64, validate=True)
    assert raw[:2] == b"\xff\xd8"  # JPEG SOI marker
    out = Image.open(io.BytesIO(raw))
    assert out.format == "JPEG"
    assert out.size == (1024, 512)  # aspect ratio kept, longest side capped
    assert max(out.size) <= 1024


def test_prepare_image_keeps_small_images_converts_rgb_and_accepts_paths(tmp_path):
    rgba = Image.new("RGBA", (300, 200), (10, 20, 30, 255))
    raw = base64.b64decode(see.prepare_image(rgba))
    out = Image.open(io.BytesIO(raw))
    assert out.size == (300, 200) and out.mode == "RGB"

    p = tmp_path / "tall.png"
    Image.new("RGB", (500, 1500), (1, 2, 3)).save(p)
    raw2 = base64.b64decode(see.prepare_image(str(p)))
    assert raw2[:2] == b"\xff\xd8"
    assert Image.open(io.BytesIO(raw2)).size == (341, 1024)

    with pytest.raises(TypeError):
        see.prepare_image(12345)


# ---- describe_image -------------------------------------------------------------
def test_describe_image_request_body_and_stop(env):
    e = env(ollama_replies=[_ollama_reply("A red rectangle fills the frame.")])
    img = _img()
    out = see.describe_image(img)

    assert out["description"] == "A red rectangle fills the frame."
    assert out["model"] == VISION_NAME
    assert isinstance(out["timing_ms"], float)

    assert len(e.ollama.chats) == 1
    call = e.ollama.chats[0]
    body = call["body"]
    assert call["key"] == "qwen35_vision" and call["tab"] == "see"
    assert body["model"] == VISION_NAME
    assert body["think"] is False
    assert body["stream"] is False
    assert body["keep_alive"] == "10m"
    assert body["options"]["num_ctx"] == 8192
    assert body["options"]["temperature"] == 0.7
    assert body["options"]["num_predict"] == 300
    assert "format" not in body and "tools" not in body
    assert body["messages"][-1]["role"] == "user"
    assert body["messages"][-1]["content"] == prompts.VISION_PROMPT
    assert body["messages"][-1]["images"] == [see.prepare_image(img)]
    assert not any(m["role"] == "system" for m in body["messages"])

    # qwen3.5 is stopped right after the call so Stheno can load next
    assert e.ollama.stops == [VISION_NAME]
    assert e.log == [("ensure", "qwen35_vision"), ("ollama.chat", "qwen35_vision"), ("ollama.stop", VISION_NAME)]


def test_describe_image_stops_vision_model_even_when_chat_raises(env):
    e = env(ollama_raise=clients.OllamaError("HTTP 500: boom"))
    with pytest.raises(clients.OllamaError):
        see.describe_image(_img())
    assert e.ollama.stops == [VISION_NAME]
    assert e.log == [("ensure", "qwen35_vision"), ("ollama.chat", "qwen35_vision"), ("ollama.stop", VISION_NAME)]


def test_describe_image_retries_exactly_once_on_empty_content(env):
    e = env(ollama_replies=[_ollama_reply(""), _ollama_reply("Second try worked.")])
    out = see.describe_image(_img())
    assert out["description"] == "Second try worked."
    assert [c["key"] for c in e.ollama.chats] == ["qwen35_vision", "qwen35_vision"]
    assert e.ollama.chats[0]["body"] == e.ollama.chats[1]["body"]  # identical retry
    assert e.ollama.stops == [VISION_NAME]

    # two empties: still only two attempts, empty description, still stopped
    e2 = env(ollama_replies=[_ollama_reply(""), _ollama_reply("   ")])
    out2 = see.describe_image(_img())
    assert out2["description"] == ""
    assert len(e2.ollama.chats) == 2
    assert e2.ollama.stops == [VISION_NAME]


def test_describe_image_swallows_stop_failure(env):
    e = env(ollama_replies=[_ollama_reply("Fine.")])

    def bad_stop(name):
        e.ollama.stops.append(name)
        raise clients.OllamaError("stop failed")

    e.ollama.stop = bad_stop
    out = see.describe_image(_img())
    assert out["description"] == "Fine." and out["stopped"] is False
    assert e.ollama.stops == [VISION_NAME]


# ---- react ----------------------------------------------------------------------
def test_react_uses_stheno_with_voice_system_and_postprocesses(env):
    e = env(lms_replies=[_lms_reply("*laughs* Ari: nice")])
    out = see.react("A dog chewing a laptop sleeve on a sofa.")

    assert out["reaction"] == "nice"
    assert out["voice_model"] == "l3-8b-stheno-v3.2"
    assert out["chunk_ids"] == ["Preferences/Free time", "Voice/Sample 5"]
    assert out["fallback_reason"] == ""

    # retrieval on the description with nomic, k=5, tab see
    assert e.searches == [{"index_key": "nomic", "query": "A dog chewing a laptop sleeve on a sofa.",
                           "k": 5, "boost": None, "tab": "see"}]

    assert len(e.lms.chats) == 1
    call = e.lms.chats[0]
    assert call["key"] == "stheno_q4"
    assert call["temperature"] == 1.0
    assert call["max_tokens"] == 150
    assert call["stream"] is False
    assert call["tab"] == "see"
    system, user = call["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert system["content"].startswith("You are Ari")
    assert "CONTEXT:" in system["content"]
    assert DIGEST_TEXT in system["content"]
    assert "weekend bike rides when it doesn't rain" in system["content"]
    assert system["content"] == prompts.build_voice_system(
        profile_mod.load_profile(config.EXAMPLE_PROFILE_PATH), DIGEST_TEXT, CHUNKS)
    assert user["content"].startswith("You just saw: A dog chewing a laptop sleeve on a sofa.")
    assert "React to it in one or two sentences, as yourself." in user["content"]

    assert e.ensured == ["stheno_q4"]
    assert e.ollama.chats == [] and e.ollama.stops == []


def test_react_retries_stheno_once_on_empty_content(env):
    e = env(lms_replies=[_lms_reply(""), _lms_reply("ha, she has taste")])
    out = see.react("A dog.")
    assert out["reaction"] == "ha, she has taste"
    assert [c["key"] for c in e.lms.chats] == ["stheno_q4", "stheno_q4"]


def test_lms_down_falls_back_to_llama32_3b(env):
    e = env(lms_alive=False, ollama_replies=[_ollama_reply("nice, my dog would do that", model=FALLBACK_NAME)])
    out = see.react("A dog chewing a laptop sleeve.")

    assert out["reaction"] == "nice, my dog would do that"
    assert out["voice_model"] == FALLBACK_NAME
    assert out["fallback_reason"]
    assert e.lms.chats == []  # Stheno never asked
    assert e.ensured == ["llama32_3b"]  # and never stheno_q4 (no needless Ollama evictions)

    assert len(e.ollama.chats) == 1
    call = e.ollama.chats[0]
    body = call["body"]
    assert call["key"] == "llama32_3b" and call["tab"] == "see"
    assert body["model"] == FALLBACK_NAME
    assert body["stream"] is False
    assert body["keep_alive"] == "30m"
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["temperature"] == 0.8
    assert body["options"]["num_predict"] == 150
    assert "think" not in body and "format" not in body and "tools" not in body
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"].startswith("You are Ari")
    assert "CONTEXT:" in body["messages"][0]["content"]
    assert body["messages"][1]["content"].startswith("You just saw: A dog chewing a laptop sleeve.")
    assert "images" not in body["messages"][1]


def test_lms_chat_failure_also_falls_back(env):
    e = env(lms_alive=True, lms_raise=ConnectionError("refused"),
            ollama_replies=[_ollama_reply(""), _ollama_reply("eh, fine", model=FALLBACK_NAME)])
    out = see.react("A rainy street.")
    assert out["reaction"] == "eh, fine"
    assert out["voice_model"] == FALLBACK_NAME
    assert out["fallback_reason"] == see.FALLBACK_REASON == "LM Studio down or the call failed: fell back to llama3.2:3b"
    assert out["voice_key"] == "llama32_3b"
    assert len(e.lms.chats) == 1
    # fallback Ollama call gets its own single retry on empty content
    assert [c["key"] for c in e.ollama.chats] == ["llama32_3b", "llama32_3b"]
    assert e.ensured == ["stheno_q4", "llama32_3b"]


# ---- see_turn -------------------------------------------------------------------
def test_see_turn_orders_vision_then_stheno_and_returns_trace(env):
    e = env(ollama_replies=[_ollama_reply("A dog on a sofa chewing a laptop sleeve.")],
            lms_replies=[_lms_reply("Ari: \"lol she has taste at least\"")])
    out = see.see_turn(_img())

    assert out["description"] == "A dog on a sofa chewing a laptop sleeve."
    assert out["reaction"] == "lol she has taste at least"
    assert out["chunk_ids"] == ["Preferences/Free time", "Voice/Sample 5"]
    assert out["voice_model"] == "l3-8b-stheno-v3.2"
    assert isinstance(out["trace"], list) and all(isinstance(t, str) for t in out["trace"])
    assert any(t.startswith(f"vision {VISION_NAME}") and "ms" in t for t in out["trace"])
    assert any(t.startswith(f"stop {VISION_NAME}") for t in out["trace"])
    assert any(t.startswith("retrieval nomic k=5") and "Preferences/Free time" in t for t in out["trace"])
    assert any(t.startswith("voice l3-8b-stheno-v3.2") and "ms" in t for t in out["trace"])
    assert any(t.startswith("total ") for t in out["trace"])

    # MANAGER.ensure order: vision first, then Stheno; qwen3.5 stopped before Stheno is asked
    assert e.ensured == ["qwen35_vision", "stheno_q4"]
    assert e.log == [
        ("ensure", "qwen35_vision"),
        ("ollama.chat", "qwen35_vision"),
        ("ollama.stop", VISION_NAME),
        ("lms.alive", True),
        ("ensure", "stheno_q4"),
        ("lms.chat", "stheno_q4"),
    ]
    # the retrieval query is the description
    assert e.searches[0]["query"] == "A dog on a sofa chewing a laptop sleeve."


def test_see_turn_skips_reaction_when_vision_returns_nothing(env):
    e = env(ollama_replies=[_ollama_reply(""), _ollama_reply("")])
    out = see.see_turn(_img())
    assert out["description"] == "" and out["reaction"] == "" and out["chunk_ids"] == []
    assert any("empty" in t for t in out["trace"])
    assert e.lms.chats == [] and e.searches == []
    assert e.ensured == ["qwen35_vision"]
    assert e.ollama.stops == [VISION_NAME]


def test_see_turn_releases_manager_lock(env):
    env(ollama_replies=[_ollama_reply("A cat.")], lms_replies=[_lms_reply("cute")])
    see.see_turn(_img())
    got = []

    def probe():
        got.append(gpu.MANAGER.lock.acquire(blocking=False))
        if got[-1]:
            gpu.MANAGER.lock.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join(2)
    assert got == [True]


def test_see_turn_holds_manager_lock_between_vision_and_voice(env, monkeypatch):
    """The lock must stay held across the lock-free gap (digest, retrieval, lms.alive probe) so the
    heartbeat thread cannot re-warm qwen3.5 between the two sessions."""
    e = env(ollama_replies=[_ollama_reply("A cat.")], lms_replies=[_lms_reply("cute")])
    held: list[bool] = []

    def alive():
        held.append(gpu.MANAGER.lock._is_owned())
        return True

    monkeypatch.setattr(e.lms, "alive", alive)
    see.see_turn(_img())
    assert held == [True]


def test_env_uses_example_profile_even_when_real_profile_exists(env, monkeypatch, tmp_path):
    """The fixture pins resolve_profile_path to the example file; a differently-named real profile
    on disk must not leak into the assertions."""
    other = tmp_path / "twin_profile.md"
    other.write_text(config.EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8").replace("Ari", "Bob", 1),
                     encoding="utf-8")
    monkeypatch.setattr(config, "PROFILE_PATH", other, raising=False)
    env(lms_replies=[_lms_reply("Ari: fine")])
    assert see._get_profile().name == "Ari"
    assert see.react("x")["reaction"] == "fine"


# ---- profile cache --------------------------------------------------------------
def test_profile_cached_by_sha(env, monkeypatch, tmp_profile):
    env(lms_replies=[_lms_reply("ok"), _lms_reply("ok")])
    calls = []
    real = profile_mod.load_profile

    def counting(path=None):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(profile_mod, "load_profile", counting)
    see._PROFILE_CACHE.clear()
    p1 = see._get_profile()
    p2 = see._get_profile()
    assert p1 is p2 and p1.name == "Ari"
    assert len(calls) == 1
    assert list(see._PROFILE_CACHE) == [p1.sha]
    see.react("x")
    see.react("y")
    assert len(calls) == 1  # react() reuses the cached profile
    # a changed file (new sha) triggers exactly one re-parse
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: tmp_profile)
    p3 = see._get_profile()
    assert p3 is not p1 and p3.name == "Ari"
    assert len(calls) == 2
    assert list(see._PROFILE_CACHE) == [p3.sha]


@pytest.fixture
def tmp_profile(tmp_path):
    p = tmp_path / "twin_profile.md"
    p.write_bytes(config.EXAMPLE_PROFILE_PATH.read_bytes() + b"\n# Goals\n- one more line\n")
    return p
