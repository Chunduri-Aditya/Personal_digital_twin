"""Hermetic tests for twin.pipelines.decide: fake clients record exact request bodies. No network, no GPU."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from twin import audit, clients, gpu, index, profile as profile_mod, prompts
from twin.config import EXAMPLE_PROFILE_PATH
from twin.pipelines import decide
from twin.pipelines import digest as digest_mod

SITUATION = "A recruiter offers a role that pays 20% more but needs me in the office five days a week."
DIGEST = "Ari is a cautious engineer who values routine, low fixed costs and boring reliable choices."


def _ollama_response(content, done_reason="stop"):
    """Ollama /api/chat non-stream response shape."""
    if not isinstance(content, str):
        content = json.dumps(content)
    return {
        "model": "qwen3-8b-8k",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 10,
        "eval_count": 5,
        "eval_duration": 1e9,
        "load_duration": 0,
    }


B1_OK = {"verdict": "no", "confidence": 0.82,
         "reasons": ["the commute kills the morning routine", "the money gap can be closed with a raise"],
         "cited_decisions": ["D-01"], "what_would_change_my_mind": "a remote-first arrangement"}
B2_OK = {"choice": "B", "confidence": 0.7, "reasons": ["boring is the point"],
         "cited_decisions": ["D-08"], "tradeoff": "less money some years"}


class FakeOllama:
    """Records every chat call and the exact body the real client would POST (via the real _chat_body)."""

    def __init__(self, responses, events):
        self.responses = list(responses)
        self.calls = []
        self.events = events

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None,
             stream=False, images_on_last_user=None, tab=""):
        _, body = clients.OllamaClient._chat_body(self, key, messages, options, format, tools, num_predict,
                                                  stream, images_on_last_user)
        self.calls.append({"key": key, "tab": tab, "body": body, "stream": stream})
        self.events.append(("chat", key))
        if not self.responses:
            raise AssertionError("FakeOllama ran out of canned responses")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeLMS:
    """Records LM Studio chat calls; returns objects shaped like an openai ChatCompletion."""

    def __init__(self, contents, events):
        self.contents = list(contents)
        self.calls = []
        self.events = events

    def chat(self, key, messages, *, temperature=None, max_tokens=300, stream=False, extra=None, tab=""):
        self.calls.append({"key": key, "messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, "stream": stream, "extra": extra, "tab": tab})
        self.events.append(("lms_chat", key))
        content = self.contents.pop(0) if self.contents else ""
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content=content))],
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=12),
        )

    alive_flag = True

    def alive(self) -> bool:
        return self.alive_flag


def _example_profile():
    return profile_mod.load_profile(EXAMPLE_PROFILE_PATH)


def _chunk(prof, cid, score):
    c = next(c for c in prof.chunks if c.id == cid)
    return {"id": c.id, "section": c.section, "subsection": c.subsection, "title": c.title, "text": c.text,
            "score": score}


def _default_hits(prof):
    return [
        _chunk(prof, "Decisions/D-01", 0.81),
        _chunk(prof, "Decisions/D-08", 0.74),
        _chunk(prof, "Values", 0.70),
        _chunk(prof, "Preferences/Money", 0.61),
        _chunk(prof, "Boundaries", 0.40),
    ]


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Fakes for ollama, lms, MANAGER.ensure, search_chunks, load_digest; profile pinned to the example file;
    the audit log redirected to tmp_path."""
    events: list[tuple[str, str]] = []
    prof = _example_profile()
    hits = _default_hits(prof)
    ns = SimpleNamespace(events=events, profile=prof, hits=hits, search_calls=[], lms_index_exists=False,
                         audit_path=tmp_path / "audit.jsonl")

    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)
    monkeypatch.setattr(audit, "AUDIT_PATH", ns.audit_path)
    # Hermetic index files: no data/chunks.json read, and "lms_nomic" exists only when the test says so.
    monkeypatch.setattr(index, "chunk_lookup", lambda: {c.id: {"id": c.id} for c in prof.chunks})
    monkeypatch.setattr(index, "index_path", lambda key: SimpleNamespace(
        exists=lambda: ns.lms_index_exists if key == "lms_nomic" else True))
    monkeypatch.setattr(decide, "_PROFILE_CACHE", {"sha": None, "profile": None})
    monkeypatch.setattr(digest_mod, "load_digest", lambda: DIGEST)

    def fake_search(index_key, query, k=5, boost=None, tab=""):
        ns.search_calls.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
        return [dict(h) for h in ns.hits]

    monkeypatch.setattr(index, "search_chunks", fake_search)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: events.append(("ensure", key)))

    def install(ollama_responses=(), lms_contents=()):
        ns.ollama = FakeOllama(ollama_responses, events)
        ns.lms = FakeLMS(lms_contents, events)
        monkeypatch.setattr(clients, "ollama", ns.ollama)
        monkeypatch.setattr(clients, "lms", ns.lms)
        return ns

    ns.install = install
    install()
    return ns


# ---- request bodies -----------------------------------------------------------
def test_b1_request_body_and_result(env):
    env.install([_ollama_response(B1_OK)])
    res = decide.decide_b1(SITUATION)

    assert len(env.ollama.calls) == 1
    call = env.ollama.calls[0]
    body = call["body"]
    assert call["key"] == "qwen3_8k" and call["tab"] == "decide"
    assert body["model"] == "qwen3-8b-8k"
    assert body["think"] is False
    assert body["format"] == prompts.B1_SCHEMA
    assert body["options"] == {"temperature": 0.2, "num_ctx": 8192, "num_predict": 600}
    assert body["keep_alive"] == "10m"
    assert body["stream"] is False
    assert "tools" not in body
    assert all("images" not in m for m in body["messages"])

    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "Ari" in body["messages"][0]["content"]
    user = body["messages"][1]["content"]
    assert SITUATION in user
    assert user.startswith("CONTEXT:\n[1] ")
    for h in env.hits:
        assert h["text"] in user
    assert "DIGEST:\n" + DIGEST in user
    assert user.endswith("QUESTION: Would you do it? Answer yes or no.")
    assert "OPTIONS:" not in user

    assert res["kind"] == "b1" and res["error"] is None
    assert res["verdict"] == "no" and res["confidence"] == 0.82
    assert res["reasons"] == B1_OK["reasons"]
    assert res["cited_decisions"] == ["D-01"] and res["uncited"] == []
    assert res["what_would_change_my_mind"] == "a remote-first arrangement"
    assert res["chunk_ids"] == [h["id"] for h in env.hits]
    assert res["model"] == "qwen3-8b-8k"
    assert res["raw"] == json.dumps(B1_OK)
    assert res["attempts"] == 1 and res["timing_ms"] >= 0


def test_b2_request_body_and_result(env):
    env.install([_ollama_response(B2_OK)])
    res = decide.decide_b2(SITUATION, "Take the job", "Stay and ask for a raise")

    body = env.ollama.calls[0]["body"]
    assert body["model"] == "qwen3-8b-8k" and body["think"] is False
    assert body["format"] == prompts.B2_SCHEMA
    assert body["options"] == {"temperature": 0.2, "num_ctx": 8192, "num_predict": 600}
    assert body["keep_alive"] == "10m"
    user = body["messages"][1]["content"]
    assert SITUATION in user
    assert "OPTIONS:\nA: Take the job\nB: Stay and ask for a raise" in user
    assert user.endswith("QUESTION: Which would you choose?")
    assert "Answer yes or no" not in user

    assert res["kind"] == "b2" and res["error"] is None
    assert res["choice"] == "B" and res["confidence"] == 0.7
    assert res["tradeoff"] == "less money some years"
    assert res["cited_decisions"] == ["D-08"]
    assert res["option_a"] == "Take the job" and res["option_b"] == "Stay and ask for a raise"
    assert "verdict" not in res


def test_search_covers_whole_index_on_decide_tab(env):
    env.install([_ollama_response(B1_OK)])
    decide.decide_b1(SITUATION)
    n = len(env.profile.chunks)
    assert n > 24
    assert env.search_calls == [{"index_key": "nomic", "query": SITUATION, "k": n, "boost": decide.DECIDE_BOOST,
                                 "tab": "decide"}]
    assert decide.DECIDE_BOOST == {"Decisions": 0.05, "Expert reflections": 0.05, "Reflections": 0.05}


def test_search_prefers_lms_nomic_index_when_it_exists(env):
    env.lms_index_exists = True
    env.install([_ollama_response(B1_OK)])
    decide.decide_b1(SITUATION)
    assert env.search_calls[0]["index_key"] == "lms_nomic"
    assert env.events == [("ensure", "qwen3_8k"), ("chat", "qwen3_8k")]  # no Ollama embed evicts qwen3


# ---- retries ------------------------------------------------------------------
def test_length_stop_retries_once_with_1200(env):
    env.install([_ollama_response('{"verdict": "no", "conf', done_reason="length"), _ollama_response(B1_OK)])
    res = decide.decide_b1(SITUATION)
    preds = [c["body"]["options"]["num_predict"] for c in env.ollama.calls]
    assert preds == [600, 1200]
    assert res["error"] is None and res["verdict"] == "no" and res["attempts"] == 2
    assert res["num_predict"] == 1200


def test_empty_content_retries_exactly_once(env):
    env.install([_ollama_response(""), _ollama_response(B1_OK)])
    res = decide.decide_b1(SITUATION)
    assert [c["body"]["options"]["num_predict"] for c in env.ollama.calls] == [600, 600]
    assert res["error"] is None and res["verdict"] == "no"

    env.install([_ollama_response(""), _ollama_response("")])
    res = decide.decide_b1(SITUATION)
    assert len(env.ollama.calls) == 2
    assert res["error"] and "empty" in res["error"]
    assert res["verdict"] is None and res["raw"] == ""


def test_invalid_json_twice_sets_error_without_raising(env):
    env.install([_ollama_response("not json at all"), _ollama_response("[1, 2, 3]")])
    res = decide.decide_b1(SITUATION)
    assert len(env.ollama.calls) == 2
    assert res["error"] and "JSON" in res["error"]
    assert res["verdict"] is None and res["raw"] == "[1, 2, 3]"
    assert res["kind"] == "b1" and res["chunk_ids"] == [h["id"] for h in env.hits]
    assert res["cited_decisions"] == [] and res["reasons"] == [] and res["confidence"] == 0.0


def test_length_then_empty_uses_both_retry_budgets(env):
    env.install([_ollama_response("{", done_reason="length"), _ollama_response(""), _ollama_response(B2_OK)])
    res = decide.decide_b2(SITUATION, "A thing", "B thing")
    assert [c["body"]["options"]["num_predict"] for c in env.ollama.calls] == [600, 1200, 1200]
    assert res["error"] is None and res["choice"] == "B" and res["attempts"] == 3


def test_ollama_error_becomes_error_field(env):
    env.install([clients.OllamaError("HTTP 500: boom")])
    res = decide.decide_b1(SITUATION)
    assert len(env.ollama.calls) == 1
    assert res["error"] == "ollama: HTTP 500: boom"
    assert res["verdict"] is None


def test_empty_situation_makes_no_model_call(env):
    env.install([_ollama_response(B1_OK)])
    res = decide.decide_b1("   ")
    assert res["error"] == "situation is empty"
    assert env.ollama.calls == [] and env.search_calls == [] and env.events == []
    res = decide.decide_b2(SITUATION, "only A", "")
    assert res["error"] == "both options are required" and env.ollama.calls == []


# ---- retrieval filter and context ---------------------------------------------
def test_retrieve_keeps_only_decision_sections_and_at_most_8(env):
    prof = env.profile
    hits = [
        _chunk(prof, "Voice/Sample 1", 0.99),
        _chunk(prof, "Identity", 0.98),
        _chunk(prof, "Goals", 0.97),
        _chunk(prof, "People", 0.96),
        _chunk(prof, "Decisions/D-03", 0.50),
        _chunk(prof, "Preferences/Food", 0.90),
        _chunk(prof, "Decisions/D-01", 0.80),
        _chunk(prof, "Values", 0.70),
        _chunk(prof, "Boundaries", 0.10),
        _chunk(prof, "Decisions/D-02", 0.60),
        _chunk(prof, "Decisions/D-04", 0.55),
        _chunk(prof, "Preferences/Money", 0.52),
        _chunk(prof, "Decisions/D-05", 0.51),
        _chunk(prof, "Decisions/D-06", 0.49),
        _chunk(prof, "Voice/Style rules", 0.95),
    ]
    env.hits = hits
    out = decide.retrieve_for_decision(SITUATION)
    assert len(out) == 8
    assert {c["section"] for c in out} <= {"Decisions", "Values", "Preferences", "Boundaries"}
    assert [c["id"] for c in out] == ["Preferences/Food", "Decisions/D-01", "Values", "Decisions/D-02",
                                      "Decisions/D-04", "Preferences/Money", "Decisions/D-05", "Decisions/D-03"]
    assert env.search_calls[-1]["k"] == len(prof.chunks) and env.search_calls[-1]["tab"] == "decide"
    assert len(decide.retrieve_for_decision(SITUATION, k=3)) == 3


def test_retrieve_returns_8_when_20_other_section_hits_outrank_decisions(env):
    prof = env.profile
    others = [_chunk(prof, c.id, 0.0) for c in prof.chunks if c.section not in decide.DECISION_SECTIONS]
    while len(others) < 20:  # pad with synthetic Voice samples if the example profile has fewer
        others.append({"id": f"Voice/Extra {len(others)}", "section": "Voice", "subsection": "Extra",
                       "title": "Extra", "text": "extra voice sample", "score": 0.0})
    others = others[:20]
    decisions = [c for c in prof.chunks if c.section == "Decisions"][:8]
    assert len(others) == 20 and len(decisions) == 8
    env.hits = ([{**h, "score": 0.99 - i * 0.001} for i, h in enumerate(others)]
                + [_chunk(prof, c.id, 0.50 - i * 0.01) for i, c in enumerate(decisions)])
    out = decide.retrieve_for_decision(SITUATION)
    assert len(out) == 8
    assert [c["id"] for c in out] == [c.id for c in decisions]
    assert env.search_calls[-1]["k"] >= len(env.hits)


def test_build_context_numbers_chunks_then_digest():
    chunks = [{"id": "Decisions/D-01", "title": "D-01: Job offer", "text": "Situation: an offer."},
              {"id": "Values", "title": "Values", "text": "- boring reliability"}]
    ctx = decide.build_context(chunks, "the digest")
    assert ctx == ("[1] (Decisions/D-01) D-01: Job offer\nSituation: an offer.\n\n"
                   "[2] (Values) Values\n- boring reliability\n\nDIGEST:\nthe digest")
    assert decide.build_context([], "") == "(nothing retrieved)\n\nDIGEST:\n(none)"


# ---- validation ---------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [(1.7, 1.0), (-0.2, 0.0), ("abc", 0.0), ("0.35", 0.35), (None, 0.0)])
def test_confidence_is_clamped(env, raw, expected):
    env.install([_ollama_response({**B1_OK, "confidence": raw})])
    res = decide.decide_b1(SITUATION)
    assert res["error"] is None
    assert res["confidence"] == expected


def test_cited_decisions_filtered_to_profile_ids(env):
    cited = ["D-01", "D-3", "D-99", "Decisions/D-02", "junk", "D-01", "D-06: A friend's startup"]
    env.install([_ollama_response({**B1_OK, "cited_decisions": cited})])
    res = decide.decide_b1(SITUATION)
    assert res["cited_decisions"] == ["D-01", "D-03", "D-02", "D-06"]
    assert res["uncited"] == ["D-99", "junk"]


def test_cited_decisions_id_regex_is_anchored_and_collects_every_id(env):
    cited = ["covid-19", "used 4 options", "I did 2 of these", "D-3 and D-7", "d-5", "D-03: title", "D-1000"]
    env.install([_ollama_response({**B1_OK, "cited_decisions": cited})])
    res = decide.decide_b1(SITUATION)
    assert res["cited_decisions"] == ["D-03", "D-07", "D-05"]
    assert res["uncited"] == ["covid-19", "used 4 options", "I did 2 of these", "D-1000"]
    assert decide._all_decision_ids("D-3 and D-7") == ["D-3", "D-7"]
    assert decide._normalise_decision_id("covid-19") is None
    assert decide._normalise_decision_id("used 4 options") is None


def test_invalid_verdict_sets_error_without_retry(env):
    env.install([_ollama_response({**B1_OK, "verdict": "maybe"})])
    res = decide.decide_b1(SITUATION)
    assert len(env.ollama.calls) == 1
    assert res["verdict"] is None and res["error"] and "verdict" in res["error"]
    assert res["reasons"] == B1_OK["reasons"]  # the rest is still surfaced for the UI


# ---- GPU session order --------------------------------------------------------
def test_session_entered_with_qwen3_8k_before_chat(env):
    env.install([_ollama_response("", done_reason="length"), _ollama_response(B1_OK)])
    decide.decide_b1(SITUATION)
    assert env.events == [("ensure", "qwen3_8k"), ("chat", "qwen3_8k"), ("chat", "qwen3_8k")]


# ---- say it -------------------------------------------------------------------
def test_say_it_uses_stheno_with_system_message_and_postprocesses(env):
    env.install([_ollama_response(B1_OK)], ["*grins* Ari: nah, not doing the two hour commute thing\nno way"])
    res = decide.decide_b1(SITUATION)
    env.events.clear()
    text = decide.say_it(res)

    assert env.events == [("ensure", "stheno_q4"), ("lms_chat", "stheno_q4")]
    assert len(env.lms.calls) == 1
    call = env.lms.calls[0]
    assert call["key"] == "stheno_q4" and call["tab"] == "decide"
    assert call["temperature"] == 1.0 and call["max_tokens"] == 120 and call["stream"] is False
    msgs = call["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"].startswith(prompts.VOICE_SYSTEM("Ari"))
    d01 = next(c for c in env.profile.chunks if c.id == "Decisions/D-01")
    assert d01.text in msgs[0]["content"]  # cited decision chunk goes into CONTEXT
    assert msgs[1]["content"] == (
        f"Someone asked: {SITUATION.rstrip('.')}. Your decision: no, because the commute kills the morning "
        "routine; the money gap can be closed with a raise. Say this as one short text message in your own words."
    )
    assert text == "nah, not doing the two hour commute thing no way"
    assert len(env.ollama.calls) == 1  # say_it never touches Ollama


def test_say_it_b2_names_the_chosen_option_and_retries_empty_once(env):
    env.install([_ollama_response(B2_OK)], ["", "boring wins, taking the raise"])
    res = decide.decide_b2(SITUATION, "Take the job", "Stay and ask for a raise")
    text = decide.say_it(res)
    assert len(env.lms.calls) == 2
    assert "Your decision: B (Stay and ask for a raise), because boring is the point." in env.lms.calls[0]["messages"][1]["content"]
    assert text == "boring wins, taking the raise"


def test_say_it_falls_back_to_llama32_when_lms_is_down(env):
    env.install([_ollama_response(B1_OK), _ollama_response("nah. commute would eat the morning")], ["unused"])
    res = decide.decide_b1(SITUATION)
    env.lms.alive_flag = False
    env.events.clear()
    text = decide.say_it(res)
    assert text == "nah. commute would eat the morning"
    assert env.lms.calls == []
    assert env.events[0] == ("ensure", "llama32_3b")
    call = env.ollama.calls[-1]
    assert call["key"] == "llama32_3b" and call["tab"] == "decide"
    assert call["body"]["model"] == "llama3.2:3b"
    assert call["body"]["options"]["temperature"] == 0.8 and call["body"]["options"]["num_predict"] == 120


def test_say_it_without_decision_makes_no_call(env):
    env.install([_ollama_response(""), _ollama_response("")], ["unused"])
    res = decide.decide_b1(SITUATION)
    env.events.clear()
    out = decide.say_it(res)
    assert out.startswith("(nothing to say:")
    assert env.lms.calls == [] and env.events == []


# ---- markdown and caching -----------------------------------------------------
def test_render_markdown_includes_titles_from_profile(env):
    env.install([_ollama_response({**B1_OK, "cited_decisions": ["D-01", "D-42"]})])
    res = decide.decide_b1(SITUATION)
    md = decide.render_result_markdown(res)
    assert "**Verdict: NO**" in md and "Confidence: 0.82" in md
    assert "- D-01: Job offer with better pay, worse commute" in md
    assert "D-42" in md and "Uncited" in md
    assert "- the commute kills the morning routine" in md
    assert "**What would change my mind:** a remote-first arrangement" in md
    assert "qwen3-8b-8k" in md

    env.install([_ollama_response(B2_OK)])
    md2 = decide.render_result_markdown(decide.decide_b2(SITUATION, "Take the job", "Stay"))
    assert "**Choice: B** — Stay" in md2 and "**Tradeoff:** less money some years" in md2

    md3 = decide.render_result_markdown({"kind": "b1", "error": "empty reply after 2 attempts"})
    assert md3.startswith("**Error:** empty reply") and "**Verdict: (none)**" in md3


def test_profile_cached_by_sha(env):
    a = decide.get_profile()
    b = decide.get_profile()
    assert a is b and a.name == "Ari" and a.sha == env.profile.sha
    decide._PROFILE_CACHE["sha"] = "stale"
    c = decide.get_profile()
    assert c is not a and c.sha == a.sha
