"""Hermetic tests for twin.pipelines.act: fakes for Ollama, LM Studio, the index and the GPU manager."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import audit, clients, gpu, index, prompts
from twin.config import EXAMPLE_PROFILE_PATH
from twin.pipelines import act, digest
from twin.profile import load_profile

REAL_OLLAMA = clients.ollama  # captured before any monkeypatching; used only to build request bodies


@pytest.fixture(autouse=True)
def audit_path(monkeypatch, tmp_path: Path) -> Path:
    """run_agent writes one audit line per request; keep it out of data/audit.jsonl."""
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_PATH", p)
    return p


def audit_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---- fakes -------------------------------------------------------------------
def ollama_reply(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return {"model": "hermes3:8b", "message": msg, "done": True, "done_reason": "stop",
            "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9, "load_duration": 0}


def call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


class FakeOllama:
    """Records every chat call (kwargs + the exact body the real client would post)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, key, messages, **kw):
        s, body = REAL_OLLAMA._chat_body(
            key, messages, kw.get("options"), kw.get("format"), kw.get("tools"),
            kw.get("num_predict"), kw.get("stream", False), kw.get("images_on_last_user"))
        self.calls.append({"key": key, "kwargs": kw, "body": body,
                           "messages": [dict(m) for m in messages]})
        if not self.replies:
            raise AssertionError("fake ollama ran out of replies")
        return self.replies.pop(0)


class FakeLMS:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def chat(self, key, messages, **kw):
        self.calls.append({"key": key, "messages": [dict(m) for m in messages], "kwargs": kw})
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


CHUNKS = [
    {"id": "Preferences/Work style", "section": "Preferences", "subsection": "Work style",
     "title": "Work style", "text": "gym at 7 then work", "score": 0.81},
    {"id": "Decisions/D-01", "section": "Decisions", "subsection": "D-01",
     "title": "D-01: Job offer", "text": "took the boring job", "score": 0.75},
]


@pytest.fixture
def env(monkeypatch):
    """Example profile, recorder ensure(), fixed search results, short digest."""
    prof = load_profile(EXAMPLE_PROFILE_PATH)
    monkeypatch.setattr(act, "_PROFILE", prof)
    ensured = []
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    searches = []

    def fake_search(index_key, query, k=5, boost=None, tab=""):
        searches.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
        return [dict(c) for c in CHUNKS[:k]]

    monkeypatch.setattr(index, "search_chunks", fake_search)
    monkeypatch.setattr(digest, "load_digest", lambda: "ari is a dry, quiet backend developer.")
    return SimpleNamespace(profile=prof, ensured=ensured, searches=searches, monkeypatch=monkeypatch)


def install_ollama(monkeypatch, replies):
    fake = FakeOllama(replies)
    monkeypatch.setattr(clients, "ollama", fake)
    return fake


def install_lms(monkeypatch, contents):
    fake = FakeLMS(contents)
    monkeypatch.setattr(clients, "lms", fake)
    return fake


# ---- safe_calc ---------------------------------------------------------------
def test_safe_calc_basic_arithmetic():
    assert act.safe_calc("0.17 * 240") == 40.8
    assert act.safe_calc("(3+4)/2") == 3.5
    assert act.safe_calc("2**10") == 1024
    assert act.safe_calc("-5 + 2") == -3
    assert act.safe_calc("-(3 * 2)") == -6
    assert act.safe_calc("+7") == 7
    assert act.safe_calc("17 % 5") == 2
    assert act.safe_calc("17 // 5") == 3
    assert isinstance(act.safe_calc("2**10"), float)


@pytest.mark.parametrize("expr", [
    "__import__('os')",
    "a+1",
    "1;2",
    "2**100000",
    "'a' + 'b'",
    "(1).real",
    "abs(-1)",
    "1/0",
    "",
    "[1, 2]",
    "1 if 2 else 3",
    "10**400 * 10**400",
])
def test_safe_calc_rejects(expr):
    with pytest.raises(ValueError):
        act.safe_calc(expr)


def test_safe_calc_never_uses_eval():
    import inspect
    src = inspect.getsource(act)
    assert "eval(" not in src.replace("_eval_node(", "").replace("mode=\"eval\"", "")
    assert "exec(" not in src


# ---- request body ------------------------------------------------------------
def test_hermes_request_body(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply("done.")])
    out = act.run_agent("hi")
    assert out["answer"] == "done."
    assert out["steps"] == 1
    assert len(fake.calls) == 1
    c = fake.calls[0]
    assert c["key"] == "hermes3"
    body = c["body"]
    assert body["model"] == "hermes3:8b"
    assert body["tools"] == prompts.AGENT_TOOLS
    assert body["options"] == {"temperature": 0.3, "num_ctx": 8192, "num_predict": 500}
    assert body["keep_alive"] == "10m"
    assert "think" not in body
    assert "format" not in body
    assert body["stream"] is False
    assert c["kwargs"]["tab"] == "act"
    # The hermes3 Ollama template (`{{- if .Tools }}<tools boilerplate>{{- else if .System }}...`)
    # drops the system message whenever tools are sent, so the instructions MUST be inside the first
    # user turn. Do not "simplify" this back to a bare system message.
    assert body["messages"][0] == {"role": "system", "content": prompts.AGENT_SYSTEM("Ari")}
    user = body["messages"][1]
    assert user["role"] == "user"
    assert prompts.AGENT_SYSTEM("Ari") in user["content"]
    assert user["content"].endswith("\n\nREQUEST:\nhi")
    assert env.ensured == ["hermes3"]


def test_assistant_with_text_and_tool_calls_resent_with_empty_content(env):
    tc = [call("get_datetime", {})]
    fake = install_ollama(env.monkeypatch, [ollama_reply("Let me check.", tc), ollama_reply("done")])
    out = act.run_agent("time?")
    resent = fake.calls[1]["messages"][2]
    assert resent == {"role": "assistant", "content": "", "tool_calls": tc}
    assert out["trace"][0]["content"] == "Let me check."


def test_calculator_accepts_numeric_expression(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply("", [call("calculator", {"expression": 40.8})]), ollama_reply("ok")])
    act.run_agent("calc")
    assert json.loads(fake.calls[1]["messages"][3]["content"]) == {"expression": "40.8", "result": 40.8}
    assert act.TOOL_IMPL["calculator"](7) == {"expression": "7", "result": 7.0}


def test_extra_tool_kwargs_are_dropped(env):
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("calculator", {"expression": "1+1", "precision": 2}),
                          call("search_profile", {"query": "gym", "top_k": 3})]),
        ollama_reply("ok"),
    ])
    act.run_agent("calc")
    msgs = fake.calls[1]["messages"]
    assert json.loads(msgs[3]["content"]) == {"expression": "1+1", "result": 2.0}
    assert "results" in json.loads(msgs[4]["content"]) and env.searches[-1]["k"] == 4
    # required parameter still missing -> error dict
    assert "error" in act._run_tool("calculator", {"precision": 2})


# ---- tool loop ---------------------------------------------------------------
def test_tool_loop_sequence(env):
    tc = [call("get_datetime", {}), call("calculator", {"expression": "0.17 * 240"})]
    fake = install_ollama(env.monkeypatch, [ollama_reply("", tc), ollama_reply("It is now and 17% of 240 is 40.8")])
    out = act.run_agent("What time is it and what's 17% of 240?")
    assert out["answer"] == "It is now and 17% of 240 is 40.8"
    assert out["steps"] == 2
    assert len(fake.calls) == 2

    msgs = fake.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "tool"]
    assert msgs[2]["tool_calls"] == tc
    assert msgs[3]["role"] == "tool" and msgs[3]["tool_name"] == "get_datetime"
    dt = json.loads(msgs[3]["content"])
    assert set(dt) == {"iso", "weekday", "timezone"}
    assert msgs[4]["role"] == "tool" and msgs[4]["tool_name"] == "calculator"
    assert json.loads(msgs[4]["content"]) == {"expression": "0.17 * 240", "result": 40.8}

    kinds = [(t["step"], t["kind"]) for t in out["trace"]]
    assert kinds == [(1, "assistant"), (1, "tool"), (1, "tool"), (2, "assistant")]
    assert out["trace"][2]["tool"] == "calculator"
    assert out["trace"][2]["args"] == {"expression": "0.17 * 240"}
    assert out["trace"][2]["result"]["result"] == 40.8
    assert out["trace"][3]["content"] == out["answer"]


def test_agent_prompt_demands_one_tool_per_part():
    text = prompts.AGENT_SYSTEM("Ari")
    assert "get_datetime" in text and "calculator" in text
    assert "several tools in one turn" in text
    assert "one tool at a time" not in text.lower()
    assert "Never state a time, date or computed number without the matching tool result" in text


def test_time_request_without_get_datetime_is_nudged_once(env):
    # hermes3 calls only the calculator and answers; the loop nudges once and allows one extra step.
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("calculator", {"expression": "17% of 240"})]),
        ollama_reply("It is 10:00 and 17% of 240 is 40.8"),
        ollama_reply("", [call("get_datetime", {})]),
        ollama_reply("It is 22:56 and 17% of 240 is 40.8"),
    ])
    out = act.run_agent("What time is it and what's 17% of 240?", max_steps=3)
    assert out["answer"] == "It is 22:56 and 17% of 240 is 40.8"
    assert len(fake.calls) == 4 and out["steps"] == 4
    nudge = fake.calls[2]["messages"][-1]
    assert nudge == {"role": "user", "content": act.DATETIME_NUDGE}
    tools = [t["tool"] for t in out["trace"] if t["kind"] == "tool"]
    assert tools == ["calculator", "get_datetime"]
    assert any(t["kind"] == "note" and "nudge" in t["note"] for t in out["trace"])


def test_time_request_nudge_happens_only_once(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply("It is noon."), ollama_reply("Still noon.")])
    out = act.run_agent("what time is it?")
    assert len(fake.calls) == 2
    assert out["answer"] == "Still noon."


def test_non_time_request_is_never_nudged(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply("1024")])
    out = act.run_agent("2 to the 10")
    assert len(fake.calls) == 1 and out["answer"] == "1024"


def test_unknown_tool_returns_error(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply("", [call("launch_rockets", {"n": 3})]), ollama_reply("ok")])
    out = act.run_agent("do it")
    tool_msg = fake.calls[1]["messages"][3]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "launch_rockets"
    assert json.loads(tool_msg["content"]) == {"error": "unknown tool launch_rockets"}
    assert out["trace"][1]["result"] == {"error": "unknown tool launch_rockets"}


def test_string_arguments_are_parsed(env):
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("calculator", '{"expression": "(3+4)/2"}')]),
        ollama_reply("3.5"),
    ])
    out = act.run_agent("half of seven")
    assert json.loads(fake.calls[1]["messages"][3]["content"]) == {"expression": "(3+4)/2", "result": 3.5}
    assert out["trace"][1]["args"] == {"expression": "(3+4)/2"}


def test_bad_string_arguments_become_empty_dict(env):
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("get_datetime", "not json")]),
        ollama_reply("fine"),
    ])
    out = act.run_agent("time?")
    assert out["trace"][1]["args"] == {}
    assert "iso" in json.loads(fake.calls[1]["messages"][3]["content"])


def test_tool_exception_becomes_error(env):
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("calculator", {"expr": "1+1"})]),  # wrong kwarg -> TypeError
        ollama_reply("ok"),
    ])
    act.run_agent("calc")
    assert "error" in json.loads(fake.calls[1]["messages"][3]["content"])


def test_loop_stops_at_max_steps(env):
    replies = [ollama_reply("", [call("get_datetime", {})]) for _ in range(10)]
    fake = install_ollama(env.monkeypatch, replies)
    out = act.run_agent("keep asking the time", max_steps=3)
    assert out["steps"] == 3
    assert len(fake.calls) == 3
    assert out["trace"][-1]["kind"] == "note"
    assert "get_datetime" in out["answer"]
    assert "iso" in out["answer"]


def test_empty_content_retries_exactly_once(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply(""), ollama_reply(""), ollama_reply("late")])
    out = act.run_agent("say something")
    assert len(fake.calls) == 2
    assert fake.calls[0]["body"] == fake.calls[1]["body"]
    assert out["answer"] == act.NO_ANSWER
    assert out["trace"][0]["retries"] == 1


def test_empty_then_content_on_retry(env):
    fake = install_ollama(env.monkeypatch, [ollama_reply(""), ollama_reply("second try")])
    out = act.run_agent("say something")
    assert len(fake.calls) == 2
    assert out["answer"] == "second try"
    assert out["steps"] == 1


# ---- draft_message next_step after a lookup (demo rehearsal: 0 of 6 drafts, hermes3 looped to max_steps) -------
# The requests below avoid the words time/date/today/now/day so the get_datetime nudge can never fire.
def test_draft_message_after_search_profile_tells_the_model_to_write(env):
    draft = "ok wait, passed on the crypto branding gig, didn't believe in it and my name would be on it"
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("search_profile", {"query": "crypto branding offer", "k": 1})]),
        ollama_reply("", [call("draft_message", {"recipient_role": "mentor", "intent": "tell them i passed"})]),
        ollama_reply(draft),
    ])
    out = act.run_agent("look up what i decided about the crypto branding offer, then draft a text to my mentor")
    tool_msg = fake.calls[2]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "draft_message"
    payload = json.loads(tool_msg["content"])
    assert "call search_profile" not in payload["next_step"]          # search_profile already ran at step 1
    assert payload["next_step"] == act.DRAFT_WRITE_NOW.format(name=env.profile.name)
    assert payload["style_rules"] == env.profile.style_rules and payload["samples"] == env.profile.samples[:2]
    assert out["answer"] == draft
    assert out["steps"] == 3 and len(fake.calls) == 3


def test_second_draft_message_after_search_tells_the_model_to_write(env):
    draft = "passed on the crypto branding thing, felt gross tbh"
    fake = install_ollama(env.monkeypatch, [
        ollama_reply("", [call("draft_message", {"recipient_role": "mentor", "intent": "tell them i passed"})]),
        ollama_reply("", [call("search_profile", {"query": "how I talk to mentor", "k": 1})]),
        ollama_reply("", [call("draft_message", {"recipient_role": "mentor", "intent": "tell them i passed"})]),
        ollama_reply(draft),
    ])
    out = act.run_agent("draft a text to my mentor saying i passed on the crypto branding gig")
    first = json.loads(fake.calls[1]["messages"][-1]["content"])
    second = json.loads(fake.calls[3]["messages"][-1]["content"])
    # the first draft_message call keeps its lookup step unchanged
    assert first["next_step"] == (f"Before writing, call search_profile once with query \"how I talk to mentor\" "
                                  f"to get facts about the recipient, then write the draft. "
                                  f"Sign as {env.profile.name} if you sign.")
    assert "call search_profile" not in second["next_step"]
    assert second["next_step"] == act.DRAFT_WRITE_NOW.format(name=env.profile.name)
    drafts = [t for t in out["trace"] if t["kind"] == "tool" and t["tool"] == "draft_message"]
    assert [d["result"]["next_step"] for d in drafts] == [first["next_step"], second["next_step"]]
    assert out["answer"] == draft
    assert out["steps"] == 4 and len(fake.calls) == 4


# ---- audit line --------------------------------------------------------------
def test_run_agent_writes_one_audit_line_with_search_chunk_ids(env, audit_path):
    secret = "draft a note to my landlord about 12 Harbour Road and what's 17% of 240"
    install_ollama(env.monkeypatch, [
        ollama_reply("", [call("search_profile", {"query": "landlord"}), call("calculator", {"expression": "17% of 240"})]),
        ollama_reply("done"),
    ])
    out = act.run_agent(secret)
    assert out["answer"] == "done"
    lines = audit_lines(audit_path)
    assert len(lines) == 1
    e = lines[0]
    assert e["tab"] == "act" and e["condition"] == "interview" and e["ok"] is True
    assert e["request_sha"] == audit.request_sha(secret)
    raw = audit_path.read_text(encoding="utf-8")
    assert secret not in raw and "Harbour" not in raw and "landlord" not in raw
    assert e["chunk_ids"] == ["Preferences/Work style", "Decisions/D-01"]     # the search_profile results
    assert e["model_keys"] == ["hermes3"] and e["extra"] == {"steps": 2}


def test_run_agent_audit_line_on_failure_and_none_for_empty_request(env, audit_path):
    assert act.run_agent("   ")["steps"] == 0
    assert audit_lines(audit_path) == []

    class Boom:
        def chat(self, *a, **k):
            raise RuntimeError("ollama down")

    env.monkeypatch.setattr(clients, "ollama", Boom())
    with pytest.raises(RuntimeError):
        act.run_agent("what time is it?")
    lines = audit_lines(audit_path)
    assert len(lines) == 1 and lines[0]["ok"] is False and lines[0]["chunk_ids"] == []
    assert lines[0]["model_keys"] == ["hermes3"] and lines[0]["tab"] == "act"


def test_audit_failure_never_breaks_the_tab(env, monkeypatch, capsys):
    install_ollama(env.monkeypatch, [ollama_reply("fine")])
    monkeypatch.setattr(audit, "record", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert act.run_agent("hi")["answer"] == "fine"
    assert "audit.record failed" in capsys.readouterr().err


# ---- tools directly -----------------------------------------------------------
def test_search_profile_uses_lms_nomic_and_clamps_k(env):
    res = act.TOOL_IMPL["search_profile"]("morning routine", k=20)
    assert env.searches[-1] == {"index_key": "lms_nomic", "query": "morning routine", "k": 8, "boost": None, "tab": "act"}
    assert [r["id"] for r in res["results"]] == ["Preferences/Work style", "Decisions/D-01"]
    assert set(res["results"][0]) == {"id", "title", "text", "score"}
    act.TOOL_IMPL["search_profile"]("x", k=0)
    assert env.searches[-1]["k"] == 1
    act.TOOL_IMPL["search_profile"]("x")
    assert env.searches[-1]["k"] == 4
    act.TOOL_IMPL["search_profile"]("x", k="3")
    assert env.searches[-1]["k"] == 3


def test_draft_message_returns_rules_and_two_samples(env):
    res = act.TOOL_IMPL["draft_message"]("my manager", "ask for friday off")
    assert res["recipient_role"] == "my manager"
    assert res["intent"] == "ask for friday off"
    assert res["style_rules"] == env.profile.style_rules
    assert res["style_rules"].startswith("- lowercase")
    assert res["samples"] == env.profile.samples[:2]
    assert len(res["samples"]) == 2
    assert res["instruction"] == ("Write the message in this voice, 1-4 sentences, no greeting to yourself, "
                                  "sign-off optional.")


def test_get_datetime_shape():
    res = act.TOOL_IMPL["get_datetime"]()
    assert set(res) == {"iso", "weekday", "timezone"}
    assert len(res["iso"]) >= 19 and res["iso"][10] == "T"
    assert res["weekday"] in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def test_calculator_tool_error_dict():
    assert act.TOOL_IMPL["calculator"]("2**10") == {"expression": "2**10", "result": 1024.0}
    bad = act.TOOL_IMPL["calculator"]("__import__('os')")
    assert bad["expression"] == "__import__('os')" and "error" in bad and "result" not in bad


# ---- polish ------------------------------------------------------------------
def test_polish_uses_stheno_q4_with_system_message(env):
    fake = install_lms(env.monkeypatch, ["*grins* Ari: sure"])
    out = act.polish("Sure, I can do that.")
    assert out == "sure"
    assert len(fake.calls) == 1
    c = fake.calls[0]
    assert c["key"] == "stheno_q4"
    assert c["kwargs"] == {"temperature": 1.0, "max_tokens": 250, "tab": "act"}
    assert [m["role"] for m in c["messages"]] == ["system", "user"]
    sysmsg = c["messages"][0]["content"]
    assert sysmsg.startswith(prompts.VOICE_SYSTEM("Ari"))
    assert "STYLE RULES:" in sysmsg and "ari is a dry, quiet backend developer." in sysmsg
    assert c["messages"][1]["content"].endswith("\n\nSure, I can do that.")
    assert env.ensured == ["stheno_q4"]


def test_polish_retries_once_then_falls_back(env):
    fake = install_lms(env.monkeypatch, ["", "*nods*"])
    assert act.polish("keep this") == "keep this"
    assert len(fake.calls) == 2


# ---- trace markdown ----------------------------------------------------------
def test_format_trace_markdown(env):
    install_ollama(env.monkeypatch, [ollama_reply("", [call("calculator", {"expression": "2**10"})]), ollama_reply("1024")])
    out = act.run_agent("2 to the 10")
    md = act.format_trace_markdown(out["trace"])
    assert "Step 1 - assistant" in md
    assert "`calculator`" in md
    assert '"result": 1024.0' in md
    assert "Step 2 - assistant" in md and "1024" in md
    assert act.format_trace_markdown([]) == "_(no trace)_"
