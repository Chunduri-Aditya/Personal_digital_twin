"""Hermetic tests for twin.pipelines.ask: fakes record every request body; no network, no GPU."""
from __future__ import annotations

import copy
import os
import re
import shutil
from types import SimpleNamespace

import pytest

from twin import audit, clients, gpu, index, prompts
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_PATH, spec
from twin.pipelines import ask, digest

DIGEST = "Ari is a quiet backend developer who picks boring, reliable options and hedges a lot."
CHUNKS = [
    {"id": "Decisions/D-01", "section": "Decisions", "subsection": "D-01", "title": "D-01: Bought the boring phone",
     "text": "Situation: needed a phone. Choice: the boring one. Why: it lasts four years.", "score": 0.71},
    {"id": "Values", "section": "Values", "subsection": "", "title": "Values",
     "text": "boring reliability: i pick the option that still works in four years.", "score": 0.66},
    {"id": "Preferences/Tech and tools", "section": "Preferences", "subsection": "Tech and tools",
     "title": "Tech and tools", "text": "boring frameworks, one editor, no new tool without a reason.", "score": 0.61},
]
ROUTER_ABOUT_ME = '{"intent": "about_me"}'
CHECKER_OK = '{"consistent": true, "unsupported_claims": [], "contradictions": []}'
DEFAULT_REPLIES = {
    "llama32_1b": ROUTER_ABOUT_ME,
    "llama32_3b": "why did ari buy the boring phone",
    "qwen25": CHECKER_OK,
    "stheno_q8": "the boring one. it'll last four years, that's the whole review",
}
LMS_DEFAULT = "yeah the boring one. camera's fine and it'll last four years"


# ---- fakes -----------------------------------------------------------------------
class _Forbidden:
    """Any attribute access means a real HTTP call was attempted."""

    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via _http.{name}")


def _pieces(text: str) -> list[str]:
    return re.findall(r"\S+\s*", text)


def ollama_reply(text: str, model: str) -> dict:
    return {"model": model, "message": {"role": "assistant", "content": text, "tool_calls": []}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9, "load_duration": 0}


def ollama_stream(text: str, model: str):
    chunks = [{"model": model, "message": {"role": "assistant", "content": p}, "done": False} for p in _pieces(text)]
    chunks.append({"model": model, "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop",
                   "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9, "load_duration": 0})
    return iter(chunks)


def _next_script(scripts: dict, key: str, default: str) -> str:
    q = scripts.get(key)
    if q is None:
        return default
    if len(q) > 1:
        return q.pop(0)
    return q[0]


class FakeOllama(clients.OllamaClient):
    """Records kwargs and the exact body the real client would send (via the real _chat_body); no HTTP."""

    def __init__(self, log: list, scripts: dict | None = None):
        # deliberately no super().__init__(): no httpx client is ever created
        self.base_url = "http://127.0.0.1:11434"
        self.timeout = 300.0
        self._http = _Forbidden()
        self.log = log
        self.calls: list[SimpleNamespace] = []
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None,
             stream=False, images_on_last_user=None, tab=""):
        s, body = self._chat_body(key, messages, options, format, tools, num_predict, stream, images_on_last_user)
        call = SimpleNamespace(key=key, name=s.name, spec=s, body=copy.deepcopy(body), messages=copy.deepcopy(messages),
                               options=copy.deepcopy(options), format=format, tools=tools, num_predict=num_predict,
                               stream=bool(stream), images=images_on_last_user, tab=tab)
        self.calls.append(call)
        self.log.append(("ollama.chat", key, bool(stream)))
        text = _next_script(self.scripts, key, DEFAULT_REPLIES.get(key, "ok"))
        done_reason = "stop"
        if isinstance(text, tuple):      # (text, done_reason) scripts a truncated reply
            text, done_reason = text
        if stream:
            return ollama_stream(text, s.name)
        resp = ollama_reply(text, s.name)
        resp["done_reason"] = done_reason
        return resp

    def for_key(self, key: str) -> list[SimpleNamespace]:
        return [c for c in self.calls if c.key == key]


class FakeLMS:
    """Records every chat kwarg; returns OpenAI-SDK-shaped objects."""

    def __init__(self, log: list, scripts: list[str] | None = None, alive: bool = True):
        self.log = log
        self.calls: list[SimpleNamespace] = []
        self.scripts = {"stheno_q4": list(scripts)} if scripts else {}
        self.alive_flag = alive
        self.raise_exc: BaseException | None = None

    def alive(self) -> bool:
        return self.alive_flag

    def chat(self, key, messages, *, temperature=None, max_tokens=300, stream=False, extra=None, tab=""):
        s = spec(key)
        assert s.runtime == "lms", key
        self.calls.append(SimpleNamespace(key=key, name=s.name, messages=copy.deepcopy(messages), temperature=temperature,
                                          max_tokens=max_tokens, stream=bool(stream), extra=extra, tab=tab))
        self.log.append(("lms.chat", key, bool(stream)))
        if self.raise_exc is not None:
            raise self.raise_exc
        text = _next_script(self.scripts, key, LMS_DEFAULT)
        if stream:
            return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=p))]) for p in _pieces(text)]
                        + [SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class FakeSearch:
    def __init__(self, log: list):
        self.log = log
        self.calls: list[SimpleNamespace] = []
        self.results = copy.deepcopy(CHUNKS)
        self.raise_exc: BaseException | None = None

    def __call__(self, index_key, query, k=5, boost=None, tab=""):
        self.calls.append(SimpleNamespace(index_key=index_key, query=query, k=k, boost=boost, tab=tab))
        self.log.append(("search", index_key))
        if self.raise_exc is not None:
            raise self.raise_exc
        return copy.deepcopy(self.results)


@pytest.fixture
def env(monkeypatch, tmp_path):
    log: list = []
    fo = FakeOllama(log)
    fl = FakeLMS(log)
    fs = FakeSearch(log)
    monkeypatch.setattr(clients, "ollama", fo)
    monkeypatch.setattr(clients, "lms", fl)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: log.append(("ensure", key)))
    monkeypatch.setattr(index, "search_chunks", fs)
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST)
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")   # the turn's audit line never hits data/
    ask.reset_profile_cache()
    yield SimpleNamespace(ollama=fo, lms=fl, search=fs, log=log, audit_path=tmp_path / "audit.jsonl")
    ask.reset_profile_cache()


def run(message, history=(), **kw) -> list[dict]:
    return list(ask.ask_turn(message, list(history), **kw))


def done_of(events: list[dict]) -> dict:
    assert events[-1]["kind"] == "done"
    return events[-1]


def tokens_of(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["kind"] == "token")


HISTORY = [{"role": "user", "content": "what phone did you buy"},
           {"role": "assistant", "content": "the boring one"}]


# ---- router ----------------------------------------------------------------------
def test_router_request_body(env):
    events = run("what do you do for work?")
    call = env.ollama.calls[0]
    s = spec("llama32_1b")
    assert call.key == "llama32_1b" and call.body["model"] == s.name == "llama3.2:1b"
    assert call.format is prompts.ROUTER_SCHEMA and call.body["format"] == prompts.ROUTER_SCHEMA
    assert call.options == {"temperature": 0}
    assert call.body["options"]["temperature"] == 0
    assert call.body["options"]["num_ctx"] == s.num_ctx == 4096
    assert call.body["keep_alive"] == s.keep_alive == "30m"
    assert call.num_predict == 40 and call.body["options"]["num_predict"] == 40
    assert call.stream is False and call.body["stream"] is False
    assert "think" not in call.body and call.tools is None and call.images is None
    assert call.messages == [{"role": "system", "content": prompts.ROUTER_SYSTEM},
                             {"role": "user", "content": "what do you do for work?"}]
    assert call.tab == "ask"
    assert done_of(events)["data"]["intent"] == "about_me"
    assert any(e["kind"] == "trace" and e["text"].startswith("router: about_me") for e in events)


@pytest.mark.parametrize("bad", ["not json at all", '{"intent": "banana"}', '{"intent": 5}', '["about_me"]'])
def test_router_failure_defaults_to_about_me(env, bad):
    env.ollama.scripts["llama32_1b"] = [bad]
    events = run("hey")
    assert done_of(events)["data"]["intent"] == "about_me"
    assert not [e for e in events if e["kind"] == "hint"]
    assert env.search.calls[0].boost is None


def test_router_exception_defaults_to_about_me(env, monkeypatch):
    real_chat = env.ollama.chat

    def boom(key, messages, **kw):
        if key == "llama32_1b":
            raise clients.OllamaError("HTTP 500")
        return real_chat(key, messages, **kw)

    monkeypatch.setattr(env.ollama, "chat", boom)
    events = run("hey")
    assert done_of(events)["data"]["intent"] == "about_me"
    assert any("router failed" in e["text"] for e in events if e["kind"] == "trace")


def test_router_retries_once_on_empty_content(env):
    env.ollama.scripts["llama32_1b"] = ["", '{"intent": "smalltalk"}']
    events = run("hey")
    assert [c.key for c in env.ollama.calls if c.key == "llama32_1b"] == ["llama32_1b", "llama32_1b"]
    assert done_of(events)["data"]["intent"] == "smalltalk"


def test_router_gives_up_after_one_retry(env):
    env.ollama.scripts["llama32_1b"] = ["", "", ""]
    events = run("hey")
    assert len(env.ollama.for_key("llama32_1b")) == 2
    assert done_of(events)["data"]["intent"] == "about_me"


# ---- rewrite ---------------------------------------------------------------------
def test_rewrite_skipped_without_history(env):
    events = run("what phone did you buy")
    assert env.ollama.for_key("llama32_3b") == []
    assert done_of(events)["data"]["query"] == "what phone did you buy"
    assert env.search.calls[0].query == "what phone did you buy"
    assert any(e["text"] == "rewrite: skipped (no history)" for e in events if e["kind"] == "trace")


def test_rewrite_request_body_and_query_used_for_retrieval(env):
    env.ollama.scripts["llama32_3b"] = ['"why did ari buy the boring phone"']
    events = run("and why?", HISTORY)
    calls = env.ollama.for_key("llama32_3b")
    assert len(calls) == 1
    call = calls[0]
    s = spec("llama32_3b")
    assert call.body["model"] == s.name == "llama3.2:3b"
    assert call.options == {"temperature": 0} and call.body["options"]["temperature"] == 0
    assert call.body["options"]["num_ctx"] == s.num_ctx == 4096
    assert call.body["keep_alive"] == s.keep_alive == "30m"
    assert call.num_predict == 60 and call.format is None and call.stream is False and "think" not in call.body
    assert call.messages[0] == {"role": "system", "content": prompts.REWRITE_SYSTEM}
    assert call.messages[1]["role"] == "user"
    assert call.messages[1]["content"] == ("user: what phone did you buy\nassistant: the boring one\nlatest: and why?")
    # quotes stripped; the rewritten query is what retrieval sees
    assert done_of(events)["data"]["query"] == "why did ari buy the boring phone"
    assert env.search.calls[0].query == "why did ari buy the boring phone"
    # order: router, rewrite, then search
    kinds = [(e[0], e[1]) for e in env.log if e[0] in ("ollama.chat", "search")]
    assert kinds[:3] == [("ollama.chat", "llama32_1b"), ("ollama.chat", "llama32_3b"), ("search", "nomic")]


@pytest.mark.parametrize("raw", [
    "Here is the standalone query: why the boring phone",
    "Standalone query: why the boring phone",
    "Query: \"why the boring phone\"",
    "Sure! Rewritten search query: why the boring phone\nsecond line ignored",
    "why the boring phone",
])
def test_rewrite_strips_prose_preamble_and_label(env, raw):
    env.ollama.scripts["llama32_3b"] = [raw]
    events = run("and why?", HISTORY)
    assert done_of(events)["data"]["query"] == "why the boring phone"
    assert env.search.calls[0].query == "why the boring phone"


def test_rewrite_empty_falls_back_to_message(env):
    env.ollama.scripts["llama32_3b"] = ["", ""]
    events = run("and why?", HISTORY)
    assert len(env.ollama.for_key("llama32_3b")) == 2   # one retry on empty content
    assert done_of(events)["data"]["query"] == "and why?"
    assert env.search.calls[0].query == "and why?"


# ---- retrieval -------------------------------------------------------------------
def test_decide_intent_boosts_decisions(env):
    env.ollama.scripts["llama32_1b"] = ['{"intent": "decide"}']
    run("would you take a job with a long commute?")
    call = env.search.calls[0]
    assert call.boost == {"Decisions": 0.05}
    assert call.k == 5 and call.index_key == "nomic" and call.tab == "ask"

    env.search.calls.clear()
    env.ollama.scripts["llama32_1b"] = [ROUTER_ABOUT_ME]
    run("what do you do for work?", index_key="gemma")
    assert env.search.calls[0].boost is None and env.search.calls[0].index_key == "gemma"


def test_retrieval_failure_still_answers(env):
    env.search.raise_exc = FileNotFoundError("index_nomic.npz")
    events = run("what do you do for work?")
    done = done_of(events)
    assert done["data"]["chunk_ids"] == [] and done["text"]
    assert any("retrieval[nomic]" in e["text"] and "failed" in e["text"] for e in events if e["kind"] == "trace")
    assert "(nothing retrieved)" in env.lms.calls[0].messages[0]["content"]


# ---- voice: LM Studio ------------------------------------------------------------
def test_voice_lms_request_body(env):
    events = run("what phone did you buy", HISTORY, temperature=1.0)
    assert len(env.lms.calls) == 1
    call = env.lms.calls[0]
    assert call.key == "stheno_q4" and call.name == "l3-8b-stheno-v3.2"
    assert call.stream is True and call.max_tokens == 300 and call.temperature == 1.0 and call.extra is None
    assert call.tab == "ask"
    msgs = call.messages
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"].startswith(prompts.VOICE_SYSTEM("Ari"))
    assert DIGEST in msgs[0]["content"]
    assert "CONTEXT:" in msgs[0]["content"] and CHUNKS[0]["text"] in msgs[0]["content"]
    assert msgs[1:] == HISTORY + [{"role": "user", "content": "what phone did you buy"}]
    assert tokens_of(events) == LMS_DEFAULT
    assert done_of(events)["text"] == prompts.postprocess_voice(LMS_DEFAULT, "Ari")
    assert done_of(events)["data"]["voice_model"] == "stheno_q4"
    assert ("ensure", "stheno_q4") in env.log


def test_voice_prefix_identical_across_turns(env):
    run("what phone did you buy")
    env.search.results = copy.deepcopy(CHUNKS[1:])       # different context on the follow-up
    run("and why?", HISTORY)
    sys1 = env.lms.calls[0].messages[0]["content"]
    sys2 = env.lms.calls[1].messages[0]["content"]
    assert sys1 != sys2
    assert sys1.split("CONTEXT:")[0] == sys2.split("CONTEXT:")[0]
    assert sys1.count("CONTEXT:") == 1 and sys1.index("CONTEXT:") > sys1.index(DIGEST)


# ---- voice: Q8 on Ollama ---------------------------------------------------------
def test_q8_path_uses_ollama_with_system_and_spec_samplers(env):
    events = run("what phone did you buy", use_q8=True, temperature=1.0)
    assert env.lms.calls == []
    calls = env.ollama.for_key("stheno_q8")
    assert len(calls) == 1
    call = calls[0]
    s = spec("stheno_q8")
    assert call.body["model"] == s.name == "fluffy/l3-8b-stheno-v3.2:q8_0"
    assert call.stream is True and call.body["stream"] is True
    assert call.body["messages"][0]["role"] == "system"
    assert call.options == {"temperature": 1.0}          # samplers left to the spec
    assert call.body["options"] == {**s.samplers, "temperature": 1.0, "num_ctx": 8192, "num_predict": 300}
    assert call.body["options"]["min_p"] == 0.075 and call.body["options"]["top_k"] == 50
    assert call.body["options"]["repeat_penalty"] == 1.1
    assert call.body["keep_alive"] == "10m" and "think" not in call.body and call.format is None
    assert tokens_of(events) == DEFAULT_REPLIES["stheno_q8"]
    assert done_of(events)["data"]["voice_model"] == "stheno_q8"
    assert ("ensure", "stheno_q8") in env.log


# ---- voice: fallback -------------------------------------------------------------
def test_lms_down_falls_back_to_llama32_3b(env):
    env.lms.alive_flag = False
    env.ollama.scripts["llama32_3b"] = ["the boring one, lasts four years"]
    events = run("what phone did you buy")
    assert env.lms.calls == []
    calls = env.ollama.for_key("llama32_3b")
    assert len(calls) == 1                                  # no rewrite (no history), one voice call
    call = calls[0]
    assert call.body["model"] == "llama3.2:3b" and call.stream is True
    assert call.options == {"temperature": 0.8} and call.body["options"]["temperature"] == 0.8
    assert call.body["options"]["num_ctx"] == 4096 and call.body["keep_alive"] == "30m"
    assert call.num_predict == 300 and call.messages[0]["role"] == "system"
    assert done_of(events)["data"]["voice_model"] == "llama32_3b"
    assert any("LM Studio is down" in e["text"] for e in events if e["kind"] == "trace")
    assert tokens_of(events) == "the boring one, lasts four years"


# ---- empty stream retry ----------------------------------------------------------
def test_empty_lms_stream_retries_once_non_streaming(env):
    env.lms.scripts["stheno_q4"] = ["", "hello there"]
    events = run("hey")
    assert [c.stream for c in env.lms.calls] == [True, False]
    assert env.lms.calls[1].max_tokens == 300 and env.lms.calls[1].temperature == 1.0
    assert env.lms.calls[0].messages == env.lms.calls[1].messages
    assert tokens_of(events) == "hello there" and done_of(events)["text"] == "hello there"
    assert any("retrying once without streaming" in e["text"] for e in events if e["kind"] == "trace")


def test_empty_q8_stream_retries_once_non_streaming(env):
    env.ollama.scripts["stheno_q8"] = ["", "yo"]
    events = run("hey", use_q8=True)
    calls = env.ollama.for_key("stheno_q8")
    assert [c.stream for c in calls] == [True, False]
    assert calls[0].body["messages"] == calls[1].body["messages"]
    assert calls[1].body["options"]["num_predict"] == 300
    assert tokens_of(events) == "yo"


# ---- checker ---------------------------------------------------------------------
def test_checker_request_body(env):
    events = run("what phone did you buy", use_checker=True)
    calls = env.ollama.for_key("qwen25")
    assert len(calls) == 1
    call = calls[0]
    s = spec("qwen25")
    assert call.body["model"] == s.name == "qwen2.5:7b"
    assert call.format is prompts.CHECKER_SCHEMA and call.body["format"] == prompts.CHECKER_SCHEMA
    assert call.options == {"temperature": 0} and call.body["options"]["temperature"] == 0
    assert call.body["options"]["num_ctx"] == 8192 and call.body["keep_alive"] == "10m"
    assert call.num_predict == 300 and call.stream is False and "think" not in call.body
    assert call.messages[0] == {"role": "system", "content": prompts.CHECKER_SYSTEM}
    user = call.messages[1]["content"]
    reply = done_of(events)["text"]
    assert user.startswith("CONTEXT:\n[1] (D-01: Bought the boring phone) " + CHUNKS[0]["text"])
    assert "[3] (Tech and tools)" in user
    assert user.endswith("\n\nREPLY:\n" + reply) and reply
    checker_events = [e for e in events if e["kind"] == "checker"]
    assert len(checker_events) == 1
    assert checker_events[0]["data"] == {"consistent": True, "unsupported_claims": [], "contradictions": []}
    assert done_of(events)["data"]["checker"] == checker_events[0]["data"]
    # checker runs after the voice call, inside its own session
    assert env.log.index(("ensure", "qwen25")) > env.log.index(("lms.chat", "stheno_q4", True))
    assert env.log.index(("ollama.chat", "qwen25", False)) > env.log.index(("ensure", "qwen25"))


def test_checker_retries_with_more_tokens_when_truncated(env):
    truncated = '{"consistent": true, "unsupported_claims": ["a", "b"'
    full = '{"consistent": true, "unsupported_claims": ["a", "b"], "contradictions": []}'
    env.ollama.scripts["qwen25"] = [(truncated, "length"), full]
    events = run("hey", use_checker=True)
    calls = env.ollama.for_key("qwen25")
    assert [c.num_predict for c in calls] == [300, 600]
    assert [c.body["options"]["num_predict"] for c in calls] == [300, 600]
    assert all(c.format is prompts.CHECKER_SCHEMA and c.options == {"temperature": 0} for c in calls)
    assert calls[0].messages == calls[1].messages
    ev = [e for e in events if e["kind"] == "checker"][0]
    assert ev["data"] == {"consistent": True, "unsupported_claims": ["a", "b"], "contradictions": []}
    # both calls inside one session: exactly one ensure for the checker
    assert env.log.count(("ensure", "qwen25")) == 1

    # truncated but not done_reason == "length" -> no retry, checker reports failure
    env.ollama.scripts["qwen25"] = [truncated]
    before = len(env.ollama.for_key("qwen25"))
    events = run("hey", use_checker=True)
    assert len(env.ollama.for_key("qwen25")) - before == 1
    assert [e for e in events if e["kind"] == "checker"][0]["data"]["consistent"] is None


def test_checker_not_run_by_default(env):
    events = run("what phone did you buy")
    assert env.ollama.for_key("qwen25") == []
    assert not [e for e in events if e["kind"] == "checker"]
    assert done_of(events)["data"]["checker"] is None


def test_checker_failure_yields_none(env):
    env.ollama.scripts["qwen25"] = ["garbage", "garbage"]
    events = run("hey", use_checker=True)
    ev = [e for e in events if e["kind"] == "checker"][0]
    assert ev["data"]["consistent"] is None and "unparseable" in ev["data"]["error"]
    assert done_of(events)["data"]["checker"] == ev["data"]

    env.ollama.scripts["qwen25"] = ["", '{"consistent": false, "unsupported_claims": ["owns a boat"], "contradictions": []}']
    events = run("hey", use_checker=True)
    ev = [e for e in events if e["kind"] == "checker"][0]
    assert ev["data"] == {"consistent": False, "unsupported_claims": ["owns a boat"], "contradictions": []}
    assert "1 unsupported" in ev["text"]


# ---- post-processing and events --------------------------------------------------
def test_postprocess_strips_actions_and_name_prefix(env):
    env.lms.scripts["stheno_q4"] = ["*waves* Ari: hey"]
    events = run("hi")
    assert tokens_of(events) == "*waves* Ari: hey"     # tokens stream raw
    assert done_of(events)["text"] == "hey"            # done carries the cleaned reply


SENTENCE = "i learned i'm not lazy, i'm allergic to being managed. "          # 10 pieces
CUT_TAIL = "and the last thing, i guess, is that nobody"                       # cut mid-sentence at the cap


def test_capped_reply_is_trimmed_to_its_last_full_sentence(env):
    # demo rehearsal: B4.1 stopped mid-word at VOICE_TOKENS in 2 of 2 runs ("... is that nobody")
    raw = SENTENCE * 30 + CUT_TAIL
    assert len(_pieces(raw)) >= ask.VOICE_TOKENS
    env.lms.scripts["stheno_q4"] = [raw]
    events = run("what did you learn from quitting?")
    assert tokens_of(events) == raw                                  # streaming is untouched
    done = done_of(events)["text"]
    assert done == (SENTENCE * 30).strip()
    assert done.endswith("managed.") and "nobody" not in done
    voice_lines = [e["text"] for e in events if e["kind"] == "trace" and re.match(r"voice: \d+ pieces", e["text"])]
    assert len(voice_lines) == 1
    assert voice_lines[0].startswith(f"voice: {len(_pieces(raw))} pieces, {len(raw)} chars raw, {len(raw)} cleaned (")
    assert voice_lines[0].endswith(f"; trimmed to {len(done)} chars at the last full sentence (token cap)")


def test_short_reply_is_never_trimmed(env):
    short = "the boring one. it'll last four years, that's the whole"
    assert len(_pieces(short)) < ask.VOICE_TOKENS
    env.lms.scripts["stheno_q4"] = [short]
    events = run("what phone did you buy")
    assert done_of(events)["text"] == short
    assert not any("trimmed" in e["text"] for e in events if e["kind"] == "trace")


@pytest.mark.parametrize("raw", [
    "word " * 310 + "and then",                                   # no sentence boundary at all
    SENTENCE * 30 + "and that's it 🙃",                           # already ends complete (trailing emoji)
    SENTENCE * 30 + "and that's it...",                           # already ends complete (ellipsis)
    "ok. " + "word " * 310 + "and then",                          # the only boundary would drop most of it
])
def test_capped_reply_left_unchanged_without_a_safe_cut(env, raw):
    assert len(_pieces(raw)) >= ask.VOICE_TOKENS
    env.lms.scripts["stheno_q4"] = [raw]
    events = run("what did you learn from quitting?")
    assert tokens_of(events) == raw
    assert done_of(events)["text"] == prompts.postprocess_voice(raw, "Ari")
    assert not any("trimmed" in e["text"] for e in events if e["kind"] == "trace")


def test_event_sequence_ends_with_done(env):
    events = run("what phone did you buy", HISTORY, use_checker=True)
    kinds = [e["kind"] for e in events]
    assert set(kinds) <= {"trace", "hint", "token", "checker", "done"}
    assert kinds.count("done") == 1 and kinds[-1] == "done"
    assert kinds[0] == "trace"
    assert kinds.index("token") > kinds.index("trace")
    assert kinds.index("checker") > max(i for i, k in enumerate(kinds) if k == "token")
    for e in events:
        assert set(e) == {"kind", "text", "data"}
    done = events[-1]
    assert done["data"]["chunk_ids"] == [c["id"] for c in CHUNKS]
    assert set(done["data"]) >= {"intent", "query", "chunk_ids", "voice_model", "checker"}
    assert done["data"]["intent"] == "about_me" and done["data"]["voice_model"] == "stheno_q4"
    trace = "\n".join(e["text"] for e in events if e["kind"] == "trace")
    assert "router: about_me" in trace and "Decisions/D-01 0.710" in trace and "stheno_q4" in trace
    assert re.search(r"total \d+\.\d+ s", trace)


@pytest.mark.parametrize("intent,tab", [("tool", "Act"), ("image", "See")])
def test_tool_and_image_intents_yield_hint(env, intent, tab):
    env.ollama.scripts["llama32_1b"] = ['{"intent": "%s"}' % intent]
    events = run("what time is it and what's 17% of 240?")
    hints = [e for e in events if e["kind"] == "hint"]
    assert len(hints) == 1 and tab in hints[0]["text"]
    kinds = [e["kind"] for e in events]
    assert kinds.index("hint") < kinds.index("token")   # hint first, then still answers
    assert done_of(events)["data"]["intent"] == intent and done_of(events)["text"]


def test_smalltalk_has_no_hint(env):
    env.ollama.scripts["llama32_1b"] = ['{"intent": "smalltalk"}']
    events = run("thanks!")
    assert not [e for e in events if e["kind"] == "hint"]


def test_empty_message_makes_no_model_calls(env):
    events = run("   ")
    assert env.ollama.calls == [] and env.lms.calls == [] and env.search.calls == []
    assert done_of(events)["text"] == "" and done_of(events)["data"]["chunk_ids"] == []


# ---- sessions, history, threading --------------------------------------------------
@pytest.mark.parametrize("worker_thread", [True, False])
def test_every_model_call_inside_its_session(env, worker_thread):
    run("and why?", HISTORY, use_checker=True, worker_thread=worker_thread)
    ensures = [k for op, k, *_ in env.log if op == "ensure"]
    assert ensures == ["llama32_1b", "llama32_3b", "stheno_q4", "qwen25"]
    for i, entry in enumerate(env.log):
        if entry[0] in ("ollama.chat", "lms.chat"):
            prior = [e for e in env.log[:i] if e[0] == "ensure"]
            assert prior and prior[-1][1] == entry[1], f"{entry} not inside its session: {env.log[:i + 1]}"
    # the lock is free again afterwards
    assert gpu.MANAGER.lock.acquire(blocking=False)
    gpu.MANAGER.lock.release()


def test_history_limited_to_last_six_turns(env):
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(10)]
    history.insert(0, {"role": "system", "content": "ignored"})
    history.append({"role": "user", "content": {"path": "x.png"}})    # non-text content is skipped
    run("and why?", history)
    voice = env.lms.calls[0].messages
    assert voice[0]["role"] == "system"
    assert voice[1:-1] == [{"role": m["role"], "content": m["content"]} for m in history[5:-1]]
    assert voice[-1] == {"role": "user", "content": "and why?"}
    rewrite_user = env.ollama.for_key("llama32_3b")[0].messages[1]["content"]
    assert rewrite_user.startswith("user: m4\nassistant: m5\n") and "m3" not in rewrite_user
    assert rewrite_user.endswith("\nlatest: and why?")


def test_ask_sync_collects_result(env):
    r = ask.ask_sync("what phone did you buy", [], use_checker=True)
    assert isinstance(r, ask.AskResult)
    assert r.reply == prompts.postprocess_voice(LMS_DEFAULT, "Ari") and r.raw_text == LMS_DEFAULT
    assert r.intent == "about_me" and r.query == "what phone did you buy"
    assert r.chunk_ids == [c["id"] for c in CHUNKS] and r.voice_model == "stheno_q4"
    assert r.checker == {"consistent": True, "unsupported_claims": [], "contradictions": []}
    assert r.trace and "total" in r.timings and r.hints == []


def test_exceptions_propagate_through_worker_thread(env):
    env.lms.raise_exc = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        run("hey")
    assert gpu.MANAGER.lock.acquire(blocking=False)     # released on the worker thread
    gpu.MANAGER.lock.release()


def test_helpers_route_rewrite_retrieve(env):
    env.ollama.scripts["llama32_1b"] = ['{"intent": "decide"}']
    assert ask.route("should i take the job?") == "decide"
    assert ask.rewrite("and why?", []) == "and why?" and env.ollama.for_key("llama32_3b") == []
    assert ask.rewrite("and why?", HISTORY) == DEFAULT_REPLIES["llama32_3b"]
    chunks = ask.retrieve("job offer", "decide")
    assert [c["id"] for c in chunks] == [c["id"] for c in CHUNKS]
    assert env.search.calls[-1].boost == {"Decisions": 0.05} and env.search.calls[-1].k == 5
    assert ask.check_reply("hey", CHUNKS) == {"consistent": True, "unsupported_claims": [], "contradictions": []}


def test_profile_cache_reloads_when_file_changes(env, monkeypatch, tmp_path):
    p = tmp_path / "twin_profile.md"
    shutil.copy(EXAMPLE_PROFILE_PATH, p)
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: p)
    ask.reset_profile_cache()
    p1 = ask.get_profile()
    assert p1 is ask.get_profile() and p1.name == "Ari"
    text = p.read_text(encoding="utf-8").replace("name: Ari", "name: Ariana", 1)
    p.write_text(text, encoding="utf-8")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns + 2_000_000_000, st.st_mtime_ns + 2_000_000_000))
    p3 = ask.get_profile()
    assert p3 is not p1 and p3.name == "Ariana" and p3.sha != p1.sha
    assert p3 is ask.get_profile()
