"""Hermetic tests for the conditions lane (docs/PLAN_UNIFIED.md 3.4 + workflow-B contract section A):

* ask under each condition (demographic: no search, digest "", the trace line; persona: no search, digest kept;
  interview: the same event stream and request bodies as the 5-argument call), the audit line (sha only),
* decide.retrieve_for_decision per condition (reflection append, boost dict) and build_context strings,
* evals cache keys (cand vs cand@condition), validate_keys splitting, a phase-1-shaped results file replaying
  unchanged, live_one(condition) with the checker skipped outside interview,
* voice.pick_voice / stream_in_voice with bodies identical to the old Ask path; see.react through reply_in_voice,
* the UI: the condition dropdown is the LAST input of /ask, /decide_b1, /decide_b2, /eval_live and the handlers
  pass it through.

Fakes come from the phase-1 test modules (they build the exact request bodies); no network, no GPU, and every
data path (eval results, audit log) points at tmp_path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import gradio as gr
import pytest

from tests.test_ask import CHUNKS, DIGEST, HISTORY, LMS_DEFAULT, FakeLMS, FakeOllama, FakeSearch
from tests.test_decide import B1_OK, B2_OK, SITUATION, FakeLMS as DecideFakeLMS, FakeOllama as DecideFakeOllama
from tests.test_decide import _default_hits, _ollama_response
from tests.test_evals import GOOD_CHECK, GOOD_SCORES, FakeAnthropic, FakeLMS as EvalFakeLMS, FakeOllama as EvalFakeOllama
from twin import audit, clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_PATH, spec
from twin.gpu import MANAGER
from twin.pipelines import ask, decide, digest, evals, see, voice
from twin.ui import ask as ask_ui
from twin.ui import decide as decide_ui
from twin.ui import evals as evals_ui
from twin.ui import frame

ROOT = Path(__file__).resolve().parent.parent
_TIMING = re.compile(r"\d+\.\d+ s")
CONDITION_ELEMS = {"ask": "ask-condition", "decide_b1": "decide-condition", "decide_b2": "decide-condition",
                   "eval_live": "eval-condition"}


def _norm(events: list[dict]) -> list[dict]:
    """Events with the wall-clock parts removed so two runs can be compared."""
    out = []
    for e in events:
        e = copy.deepcopy(e)
        if e["kind"] == "trace":
            e["text"] = _TIMING.sub("T s", e["text"])
        if e["kind"] == "done":
            e["data"].pop("timings", None)
        out.append(e)
    return out


def _audit_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ===========================================================================
# ask
# ===========================================================================
def _ask_env(monkeypatch, tmp_path: Path) -> SimpleNamespace:
    log: list = []
    fo, fl, fs = FakeOllama(log), FakeLMS(log), FakeSearch(log)
    monkeypatch.setattr(clients, "ollama", fo)
    monkeypatch.setattr(clients, "lms", fl)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: log.append(("ensure", key)))
    monkeypatch.setattr(index, "search_chunks", fs)
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST)
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    ask.reset_profile_cache()
    return SimpleNamespace(ollama=fo, lms=fl, search=fs, log=log, audit_path=tmp_path / "audit.jsonl",
                           profile=profile_mod.load_profile(EXAMPLE_PROFILE_PATH))


@pytest.fixture
def ask_env(monkeypatch, tmp_path):
    ns = _ask_env(monkeypatch, tmp_path)
    yield ns
    ask.reset_profile_cache()


def _events(message, history=(), **kw) -> list[dict]:
    return list(ask.ask_turn(message, list(history), worker_thread=False, **kw))


def test_ask_demographic_no_retrieval_no_digest(ask_env):
    events = _events("what phone did you buy", condition="demographic")
    assert ask_env.search.calls == [], "no retrieval call at all"
    traces = [e["text"] for e in events if e["kind"] == "trace"]
    assert traces[0].startswith("profile: Ari (") and f"digest {len(DIGEST)} chars" in traces[0]
    assert traces[1] == "condition: demographic (chunks: 0, digest: no)"
    system = ask_env.lms.calls[0].messages[0]["content"]
    assert system == prompts.build_voice_system(ask_env.profile, "", [], condition="demographic")
    assert system == prompts.VOICE_SYSTEM_NO_CONTEXT("Ari") + "\n\nIDENTITY:\n" + ask_env.profile.identity.strip()
    assert DIGEST not in system and "CONTEXT:" not in system and "STYLE RULES" not in system
    assert ask_env.lms.calls[0].messages[1:] == [{"role": "user", "content": "what phone did you buy"}]
    done = events[-1]
    assert done["kind"] == "done" and done["data"]["condition"] == "demographic"
    assert done["data"]["chunk_ids"] == [] and done["data"]["chunks"] == []
    assert done["data"]["voice_model"] == "stheno_q4" and done["text"] == prompts.postprocess_voice(LMS_DEFAULT, "Ari")
    # the rest of the turn is the phase-1 turn: router body, streamed Stheno body
    router = ask_env.ollama.for_key("llama32_1b")[0]
    assert router.format is prompts.ROUTER_SCHEMA and router.options == {"temperature": 0} and router.num_predict == 40
    v = ask_env.lms.calls[0]
    assert v.key == "stheno_q4" and v.stream is True and v.max_tokens == 300 and v.temperature == 1.0 and v.tab == "ask"
    assert "retrieval" not in done["data"]["timings"]
    assert not any(t.startswith("retrieval[") for t in traces)


def test_ask_persona_no_retrieval_digest_kept(ask_env):
    events = _events("what phone did you buy", condition="persona")
    assert ask_env.search.calls == []
    traces = [e["text"] for e in events if e["kind"] == "trace"]
    assert traces[1] == "condition: persona (chunks: 0, digest: yes)"
    system = ask_env.lms.calls[0].messages[0]["content"]
    assert system == prompts.build_voice_system(ask_env.profile, DIGEST, [], condition="persona")
    assert system.startswith(prompts.VOICE_SYSTEM_NO_CONTEXT("Ari")) and DIGEST in system
    assert "STYLE RULES:" in system and "BOUNDARIES" in system and "CONTEXT:" not in system
    assert events[-1]["data"]["condition"] == "persona" and events[-1]["data"]["chunk_ids"] == []


def test_ask_persona_reports_digest_no_when_the_digest_is_missing(ask_env, monkeypatch):
    monkeypatch.setattr(digest, "load_digest", lambda: "")
    events = _events("hey", condition="persona")
    traces = [e["text"] for e in events if e["kind"] == "trace"]
    assert traces[1] == "condition: persona (chunks: 0, digest: no)"
    assert "ABOUT YOU" not in ask_env.lms.calls[0].messages[0]["content"]


def test_ask_interview_identical_to_the_five_argument_call(monkeypatch, tmp_path):
    a = _ask_env(monkeypatch, tmp_path / "a")
    a.ollama.scripts["llama32_3b"] = ["why did ari buy the boring phone"]
    base = _events("and why?", HISTORY, use_checker=True)
    base_lms, base_ollama = copy.deepcopy(a.lms.calls), copy.deepcopy([c.body for c in a.ollama.calls])
    base_search = copy.deepcopy(a.search.calls)
    b = _ask_env(monkeypatch, tmp_path / "b")
    b.ollama.scripts["llama32_3b"] = ["why did ari buy the boring phone"]
    with_cond = _events("and why?", HISTORY, use_checker=True, condition="interview")
    assert _norm(with_cond) == _norm(base)
    assert [c.messages for c in b.lms.calls] == [c.messages for c in base_lms]
    assert [(c.temperature, c.max_tokens, c.stream, c.tab) for c in b.lms.calls] == \
           [(c.temperature, c.max_tokens, c.stream, c.tab) for c in base_lms]
    assert [c.body for c in b.ollama.calls] == base_ollama
    assert b.search.calls == base_search and len(b.search.calls) == 1
    # interview keeps the phase-1 trace (no condition line) and carries the condition in done.data
    assert not any(e["kind"] == "trace" and e["text"].startswith("condition:") for e in with_cond)
    assert with_cond[-1]["data"]["condition"] == "interview" == base[-1]["data"]["condition"]
    assert with_cond[-1]["data"]["chunk_ids"] == [c["id"] for c in CHUNKS]
    assert "CONTEXT:" in b.lms.calls[0].messages[0]["content"] and DIGEST in b.lms.calls[0].messages[0]["content"]


def test_ask_audit_line_holds_sha_not_text(ask_env):
    secret = "my salary is exactly 41k and i live at 12 harbour road"
    _events(secret, condition="persona")
    lines = _audit_lines(ask_env.audit_path)
    assert len(lines) == 1
    e = lines[0]
    assert e["tab"] == "ask" and e["condition"] == "persona" and e["ok"] is True
    assert e["request_sha"] == hashlib.sha256(secret.encode("utf-8")).hexdigest()
    assert e["chunk_ids"] == [] and e["model_keys"] == ["llama32_1b", "stheno_q4"]
    raw = ask_env.audit_path.read_text(encoding="utf-8")
    assert "41k" not in raw and "harbour" not in raw and secret not in raw
    # interview with history + checker: rewrite, voice and checker keys, the retrieved chunk ids
    _events("and why?", HISTORY, use_checker=True)
    e2 = _audit_lines(ask_env.audit_path)[-1]
    assert e2["condition"] == "interview" and e2["chunk_ids"] == [c["id"] for c in CHUNKS]
    assert e2["model_keys"] == ["llama32_1b", "llama32_3b", "stheno_q4", "qwen25"] and e2["ok"] is True
    # Q8 + fallback keys are what actually ran
    _events("hey", use_q8=True, condition="demographic")
    assert _audit_lines(ask_env.audit_path)[-1]["model_keys"] == ["llama32_1b", "stheno_q8"]
    ask_env.lms.alive_flag = False
    _events("hey")
    assert _audit_lines(ask_env.audit_path)[-1]["model_keys"] == ["llama32_1b", "llama32_3b"]


def test_ask_audit_ok_false_on_failure_and_nothing_for_empty_message(ask_env):
    _events("   ")
    assert not ask_env.audit_path.exists(), "an empty message calls no model and writes no audit line"
    ask_env.lms.raise_exc = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        _events("hey", condition="persona")
    lines = _audit_lines(ask_env.audit_path)
    assert len(lines) == 1 and lines[0]["ok"] is False and lines[0]["condition"] == "persona"
    assert lines[0]["model_keys"] == ["llama32_1b", "stheno_q4"]
    # the worker-thread path writes the line too
    ask_env.lms.raise_exc = None
    list(ask.ask_turn("hey", [], condition="demographic"))
    assert _audit_lines(ask_env.audit_path)[-1]["ok"] is True
    # an audit failure never breaks a turn
    ask_env.audit_path.write_text("x", encoding="utf-8")
    audit.AUDIT_PATH = ask_env.audit_path / "not-a-dir" / "audit.jsonl"   # restored by the fixture's monkeypatch
    events = _events("hey")
    assert events[-1]["kind"] == "done" and events[-1]["text"]


def test_ask_sync_and_result_carry_condition(ask_env):
    r = ask.ask_sync("what phone did you buy", [], condition="persona")
    assert isinstance(r, ask.AskResult) and r.condition == "persona" and r.chunk_ids == []
    assert r.reply == prompts.postprocess_voice(LMS_DEFAULT, "Ari")
    assert ask.ask_sync("hey", []).condition == "interview"
    assert ask.AskResult().condition == "interview"
    with pytest.raises(ValueError, match="unknown condition"):
        _events("hey", condition="ablation")
    assert ask_env.audit_path.exists() and len(_audit_lines(ask_env.audit_path)) == 2


def test_ask_checker_skipped_outside_interview(ask_env):
    events = _events("hey", use_checker=True, condition="persona")
    assert ask_env.ollama.for_key("qwen25") == []
    assert not [e for e in events if e["kind"] == "checker"]
    assert events[-1]["data"]["checker"] is None
    assert any(e["text"] == "checker: skipped (no CONTEXT under the persona condition)"
               for e in events if e["kind"] == "trace")
    assert _audit_lines(ask_env.audit_path)[-1]["model_keys"] == ["llama32_1b", "stheno_q4"]
    events = _events("hey", use_checker=True)
    assert len(ask_env.ollama.for_key("qwen25")) == 1 and [e for e in events if e["kind"] == "checker"]


def test_ask_q8_body_unchanged_under_persona(ask_env):
    _events("hey", use_q8=True, condition="persona")
    call = ask_env.ollama.for_key("stheno_q8")[0]
    s = spec("stheno_q8")
    assert call.body["options"] == {**s.samplers, "temperature": 1.0, "num_ctx": 8192, "num_predict": 300}
    assert call.stream is True and call.body["keep_alive"] == "10m" and call.body["messages"][0]["role"] == "system"
    assert "CONTEXT:" not in call.body["messages"][0]["content"]
    assert ask_env.search.calls == [] and ask_env.lms.calls == []


def test_ask_cli_condition_flag(ask_env, capsys):
    assert ask.main(["what phone did you buy", "--condition", "demographic"]) == 0
    assert ask_env.search.calls == []
    err = capsys.readouterr().err
    assert "condition: demographic (chunks: 0, digest: no)" in err and '"condition": "demographic"' in err
    with pytest.raises(SystemExit):
        ask.main(["hey", "--condition", "nope"])


# ===========================================================================
# decide
# ===========================================================================
@pytest.fixture
def decide_env(monkeypatch, tmp_path):
    events: list = []
    prof = profile_mod.load_profile(EXAMPLE_PROFILE_PATH)
    ns = SimpleNamespace(events=events, profile=prof, hits=_default_hits(prof), search_calls=[], lookup_calls=0,
                         audit_path=tmp_path / "audit.jsonl")
    lookup = {c.id: {"id": c.id, "section": c.section, "subsection": c.subsection, "title": c.title,
                     "text": c.text, "source": "profile"} for c in prof.chunks}
    ns.lookup = lookup
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)
    monkeypatch.setattr(audit, "AUDIT_PATH", ns.audit_path)

    def chunk_lookup():
        ns.lookup_calls += 1
        return {k: dict(v) for k, v in ns.lookup.items()}

    monkeypatch.setattr(index, "chunk_lookup", chunk_lookup)
    monkeypatch.setattr(index, "index_path", lambda key: SimpleNamespace(exists=lambda: key != "lms_nomic"))
    monkeypatch.setattr(decide, "_PROFILE_CACHE", {"sha": None, "profile": None})
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST)

    def fake_search(index_key, query, k=5, boost=None, tab=""):
        ns.search_calls.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
        return [dict(h) for h in ns.hits]

    monkeypatch.setattr(index, "search_chunks", fake_search)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: events.append(("ensure", key)))

    def install(ollama_responses=(), lms_contents=()):
        ns.ollama = DecideFakeOllama(ollama_responses, events)
        ns.lms = DecideFakeLMS(lms_contents, events)
        monkeypatch.setattr(clients, "ollama", ns.ollama)
        monkeypatch.setattr(clients, "lms", ns.lms)
        return ns

    ns.install = install
    install()
    return ns


@pytest.mark.parametrize("condition", ["demographic", "persona"])
def test_retrieve_for_decision_skips_search_outside_interview(decide_env, condition):
    assert decide.retrieve_for_decision(SITUATION, condition=condition) == []
    assert decide_env.search_calls == [] and decide_env.lookup_calls == 0 and decide_env.events == []


def test_retrieve_for_decision_interview_boost_sections_and_reflection_append(decide_env):
    prof = decide_env.profile
    refl = {"id": "Expert reflections/Psychologist", "section": "Expert reflections", "subsection": "Psychologist",
            "title": "Psychologist", "text": "Ari avoids novelty and optimises for regret minimisation.",
            "source": "reflection"}
    draft = {"id": "Reflections/Demographer", "section": "Reflections", "subsection": "Demographer",
             "title": "Demographer", "text": "A thirty-something renter in a mid-sized city."}   # old row: no source
    decide_env.lookup["Expert reflections/Psychologist"] = refl
    decide_env.lookup["Reflections/Demographer"] = draft
    decide_env.hits = decide_env.hits + [{**refl, "score": 0.77}, {**draft, "score": 0.10}]
    out = decide.retrieve_for_decision(SITUATION, k=4)
    ids = [c["id"] for c in out]
    # top-4 by score within DECISION_SECTIONS (the reflection sections count), then the missing reflection appended
    assert ids == ["Decisions/D-01", "Expert reflections/Psychologist", "Decisions/D-08", "Values",
                   "Reflections/Demographer"]
    assert ids.count("Expert reflections/Psychologist") == 1, "already in the top-k: not appended twice"
    assert out[-1]["score"] == 0.10 and out[-1]["source"] == "reflection"   # score kept from the hits
    call = decide_env.search_calls[-1]
    assert call["boost"] == {"Decisions": 0.05, "Expert reflections": 0.05, "Reflections": 0.05}
    assert call["k"] == len(decide_env.lookup) and call["tab"] == "decide" and call["index_key"] == "nomic"
    assert decide.DECISION_SECTIONS >= {"Decisions", "Values", "Preferences", "Boundaries", "Expert reflections",
                                        "Reflections"}
    # a reflection chunk absent from the hits still comes from chunks.json (no score)
    decide_env.hits = _default_hits(prof)
    out = decide.retrieve_for_decision(SITUATION, k=8)
    assert [c["id"] for c in out][-2:] == ["Expert reflections/Psychologist", "Reflections/Demographer"]
    assert "score" not in out[-1] and out[-1]["text"] == draft["text"]
    # without reflection chunks the phase-1 result is unchanged
    del decide_env.lookup["Expert reflections/Psychologist"]
    del decide_env.lookup["Reflections/Demographer"]
    assert [c["id"] for c in decide.retrieve_for_decision(SITUATION)] == [h["id"] for h in _default_hits(prof)]


def test_build_context_per_condition(decide_env):
    prof = decide_env.profile
    chunks = [{"id": "Decisions/D-01", "title": "D-01: Job offer", "text": "Situation: an offer."}]
    interview = decide.build_context(chunks, "the digest")
    assert interview == "[1] (Decisions/D-01) D-01: Job offer\nSituation: an offer.\n\nDIGEST:\nthe digest"
    assert decide.build_context(chunks, "the digest", "interview", prof) == interview
    assert decide.build_context(chunks, "the digest", condition="persona", profile=prof) == \
           f"IDENTITY:\n{prof.identity.strip()}\n\nDIGEST:\nthe digest"
    assert decide.build_context(chunks, "the digest", condition="demographic", profile=prof) == \
           f"IDENTITY:\n{prof.identity.strip()}"
    assert decide.build_context([], "", "persona", prof) == f"IDENTITY:\n{prof.identity.strip()}\n\nDIGEST:\n(none)"
    assert decide.build_context([], "", "persona") == decide.build_context([], "", "persona", prof)   # get_profile()
    with pytest.raises(ValueError, match="unknown condition"):
        decide.build_context(chunks, "d", "nope", prof)


def test_decide_b1_persona_prompt_result_and_audit(decide_env):
    decide_env.install([_ollama_response(B1_OK)])
    res = decide.decide_b1(SITUATION, condition="persona")
    assert decide_env.search_calls == [] and res["condition"] == "persona" and res["chunk_ids"] == []
    assert res["verdict"] == "no" and res["error"] is None
    body = decide_env.ollama.calls[0]["body"]
    user = body["messages"][1]["content"]
    assert user.startswith(f"CONTEXT:\nIDENTITY:\n{decide_env.profile.identity.strip()}\n\nDIGEST:\n{DIGEST}\n\nSITUATION:\n")
    assert "[1] " not in user and user.endswith("QUESTION: Would you do it? Answer yes or no.")
    assert body["format"] == prompts.B1_SCHEMA and body["options"] == {"temperature": 0.2, "num_ctx": 8192, "num_predict": 600}
    lines = _audit_lines(decide_env.audit_path)
    assert len(lines) == 1
    assert lines[0]["tab"] == "decide" and lines[0]["condition"] == "persona" and lines[0]["ok"] is True
    assert lines[0]["request_sha"] == hashlib.sha256(SITUATION.encode("utf-8")).hexdigest()
    assert lines[0]["chunk_ids"] == [] and lines[0]["model_keys"] == ["qwen3_8k"] and lines[0]["extra"] == {"kind": "b1"}
    assert SITUATION not in decide_env.audit_path.read_text(encoding="utf-8")
    md = decide.render_result_markdown(res)
    assert "condition persona" in md and "**Verdict: NO**" in md


def test_decide_b2_demographic_has_identity_only(decide_env):
    decide_env.install([_ollama_response(B2_OK)])
    res = decide.decide_b2(SITUATION, "Take the job", "Stay", condition="demographic")
    user = decide_env.ollama.calls[0]["body"]["messages"][1]["content"]
    assert user.startswith(f"CONTEXT:\nIDENTITY:\n{decide_env.profile.identity.strip()}\n\nSITUATION:\n")
    assert "DIGEST" not in user and DIGEST not in user
    assert "OPTIONS:\nA: Take the job\nB: Stay" in user
    assert res["condition"] == "demographic" and res["choice"] == "B"
    assert decide_env.search_calls == []
    e = _audit_lines(decide_env.audit_path)[-1]
    assert e["condition"] == "demographic" and e["extra"] == {"kind": "b2"}


def test_decide_interview_default_unchanged_and_audit_has_chunk_ids(decide_env):
    decide_env.install([_ollama_response(B1_OK)])
    res = decide.decide_b1(SITUATION)
    assert res["condition"] == "interview" and res["chunk_ids"] == [h["id"] for h in decide_env.hits]
    user = decide_env.ollama.calls[0]["body"]["messages"][1]["content"]
    assert user.startswith("CONTEXT:\n[1] ") and "DIGEST:\n" + DIGEST in user
    e = _audit_lines(decide_env.audit_path)[-1]
    assert e["condition"] == "interview" and e["chunk_ids"] == res["chunk_ids"] and e["ok"] is True
    # empty situation: no model call, no audit line
    decide.decide_b1("  ", condition="persona")
    assert len(_audit_lines(decide_env.audit_path)) == 1
    # a failed call audits ok=False
    decide_env.install([_ollama_response(""), _ollama_response("")])
    res = decide.decide_b1(SITUATION, condition="persona")
    assert res["error"] and _audit_lines(decide_env.audit_path)[-1]["ok"] is False
    with pytest.raises(ValueError, match="unknown condition"):
        decide.decide_b1(SITUATION, condition="nope")


def test_say_it_follows_the_result_condition(decide_env):
    decide_env.install([_ollama_response(B1_OK), _ollama_response(B1_OK)], ["nah", "nah again"])
    persona = decide.decide_b1(SITUATION, condition="persona")
    interview = decide.decide_b1(SITUATION)
    assert decide.say_it(persona) == "nah"
    sys_p = decide_env.lms.calls[0]["messages"][0]["content"]
    assert sys_p == prompts.build_voice_system(decide_env.profile, DIGEST, [], condition="persona")
    assert sys_p.startswith(prompts.VOICE_SYSTEM_NO_CONTEXT("Ari")) and "CONTEXT:" not in sys_p
    assert decide.say_it(interview) == "nah again"
    sys_i = decide_env.lms.calls[1]["messages"][0]["content"]
    assert sys_i.startswith(prompts.VOICE_SYSTEM("Ari")) and "CONTEXT:" in sys_i
    d01 = next(c for c in decide_env.profile.chunks if c.id == "Decisions/D-01")
    assert d01.text in sys_i
    # a phase-1 result dict without "condition" is treated as interview
    legacy = {k: v for k, v in interview.items() if k != "condition"}
    decide.say_it(legacy)
    assert decide_env.lms.calls[2]["messages"][0]["content"] == sys_i
    assert all(c["max_tokens"] == 120 and c["temperature"] == 1.0 and c["tab"] == "decide" for c in decide_env.lms.calls)
    says = [e for e in _audit_lines(decide_env.audit_path) if e["extra"].get("kind") == "say_it"]
    assert [e["condition"] for e in says] == ["persona", "interview", "interview"]
    assert says[0]["model_keys"] == ["stheno_q4"] and says[0]["chunk_ids"] == []
    assert says[1]["chunk_ids"] == ["Decisions/D-01"]


# ===========================================================================
# evals
# ===========================================================================
@pytest.fixture
def eval_env(monkeypatch, tmp_path):
    profile = profile_mod.load_profile(EXAMPLE_PROFILE_PATH)
    ollama, lms, anth = EvalFakeOllama(), EvalFakeLMS(), FakeAnthropic(available=False)
    ensured: list[str] = []
    searches: list[dict] = []
    by_id = {c.id: {"id": c.id, "section": c.section, "subsection": c.subsection, "title": c.title, "text": c.text}
             for c in profile.chunks}
    fixed = [{**by_id["Identity"], "score": 0.9}, {**by_id["Decisions/D-01"], "score": 0.8}]

    def fake_search(index_key, query, k=5, boost=None, tab=""):
        searches.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
        return [dict(c) for c in fixed]

    monkeypatch.setattr(clients, "ollama", ollama)
    monkeypatch.setattr(clients, "lms", lms)
    monkeypatch.setattr(clients, "anthropic_client", anth)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    monkeypatch.setattr(index, "search_chunks", fake_search)
    monkeypatch.setattr(index, "chunk_lookup", lambda: dict(by_id))
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST)
    monkeypatch.setattr(config, "EVAL_RESULTS_PATH", tmp_path / "eval_results.json")
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)
    return SimpleNamespace(ollama=ollama, lms=lms, anth=anth, ensured=ensured, searches=searches, by_id=by_id,
                           chunks=fixed, profile=profile, results_path=tmp_path / "eval_results.json",
                           audit_path=tmp_path / "audit.jsonl")


def _collapse(seq):
    out = []
    for x in seq:
        if not out or out[-1] != x:
            out.append(x)
    return out


def test_cell_keys_and_validate_keys_split():
    assert evals.cell_key("hermes3") == "hermes3" == evals.cell_key("hermes3", "interview")
    assert evals.cell_key("hermes3", "persona") == "hermes3@persona"
    assert evals.cell_key("stheno_q4", "demographic") == "stheno_q4@demographic"
    assert evals.split_cell_key("hermes3") == ("hermes3", "interview")
    assert evals.split_cell_key("hermes3@persona") == ("hermes3", "persona")
    with pytest.raises(ValueError, match="bogus"):
        evals.split_cell_key("hermes3@bogus")
    evals.validate_keys(["hermes3@persona", "stheno_q4@demographic", "qwen3_8k"], ["llama31"])
    with pytest.raises(ValueError, match="bogus"):
        evals.validate_keys(["hermes3@bogus"])
    with pytest.raises(ValueError, match="claude"):
        evals.validate_keys(["claude@persona"])
    with pytest.raises(ValueError, match="unknown condition"):
        evals._conditions(["interview", "nope"])
    assert evals._conditions(["persona", "persona", "interview"]) == ["persona", "interview"]
    assert evals._conditions(None) == ["interview"]


def test_bakeoff_conditions_cache_keys_retrieval_and_checker(eval_env):
    entry = evals.run_voice_bakeoff(n_questions=2, judges=("llama31",), candidates=["hermes3"],
                                    conditions=("interview", "persona", "demographic"))
    assert list(entry["voice"]) == ["hermes3", "hermes3@persona", "hermes3@demographic"]
    for key in entry["voice"]:
        assert set(entry["voice"][key]) == {"Q-01", "Q-02"}
        for rec in entry["voice"][key].values():
            assert rec["judges"]["llama31"] == GOOD_SCORES and rec["reply"]
    # retrieval only for the interview cells (one embed per question), checker only on interview cells
    assert [s["query"] for s in eval_env.searches] == [q.question for q in eval_env.profile.eval[:2]]
    gens = [c for c in eval_env.ollama.calls if c["body"].get("format") is None]
    assert len(gens) == 6 and _collapse(eval_env.ensured) == ["hermes3", "llama31", "qwen25"]
    checks = [c for c in eval_env.ollama.calls if c["body"].get("format") == prompts.CHECKER_SCHEMA]
    assert len(checks) == 2
    for qid in ("Q-01", "Q-02"):
        assert entry["voice"]["hermes3"][qid]["checker"] == GOOD_CHECK
        assert "checker" not in entry["voice"]["hermes3@persona"][qid]
        assert "checker" not in entry["voice"]["hermes3@demographic"][qid]
    # prompts per condition
    systems = {}
    for c in gens:
        systems.setdefault(c["body"]["messages"][0]["content"], []).append(c["body"]["messages"][1]["content"])
    prof = eval_env.profile
    persona = prompts.build_voice_system(prof, DIGEST, [], condition="persona")
    demo = prompts.build_voice_system(prof, DIGEST, [], condition="demographic")
    assert persona in systems and demo in systems
    assert len(systems[persona]) == 2 and len(systems[demo]) == 2
    interview_systems = [s for s in systems if s not in (persona, demo)]
    # the fake search returns the same chunks for every question, so one interview system string, two questions
    assert len(interview_systems) == 1 and len(systems[interview_systems[0]]) == 2
    assert "CONTEXT:" in interview_systems[0] and eval_env.by_id["Decisions/D-01"]["text"] in interview_systems[0]
    assert "CONTEXT:" not in persona and DIGEST in persona and DIGEST not in demo
    # every model body is the phase-1 body (hermes3: temperature 0.7, num_predict 300, num_ctx 8192)
    for c in gens:
        assert c["body"]["options"] == {"temperature": 0.7, "num_ctx": 8192, "num_predict": 300}
    # summary rows: the ablation keys are their own rows after the phase-1 candidates
    rows = evals.summary_rows(entry)
    assert [r[0] for r in rows] == ["hermes3", "hermes3@persona", "hermes3@demographic"]
    assert rows[0][6] == 1.0 and rows[1][6] is None and rows[2][6] is None
    # one audit line per generation, tagged with the cell's condition and the interview chunk ids
    lines = _audit_lines(eval_env.audit_path)
    assert [(e["tab"], e["condition"]) for e in lines] == [("eval", "interview")] * 2 + [("eval", "persona")] * 2 + \
           [("eval", "demographic")] * 2
    assert lines[0]["chunk_ids"] == ["Identity", "Decisions/D-01"] and lines[2]["chunk_ids"] == []
    assert all(e["model_keys"] == ["hermes3"] and e["ok"] and e["extra"]["step"] == "generate" for e in lines)
    # a cached re-run makes no model call and no embed call
    eval_env.ollama.calls.clear()
    eval_env.searches.clear()
    again = evals.run_voice_bakeoff(n_questions=2, judges=("llama31",), candidates=["hermes3"],
                                    conditions=("interview", "persona", "demographic"))
    assert eval_env.ollama.calls == [] and eval_env.searches == [] and again["voice"] == entry["voice"]
    # adding a condition later only fills that condition's cells
    evals.run_voice_bakeoff(n_questions=2, judges=("llama31",), candidates=["hermes3", "qwen25"],
                            conditions=("persona",))
    gens = [c for c in eval_env.ollama.calls if c["body"].get("format") is None]
    assert [c["body"]["model"] for c in gens] == ["qwen2.5:7b", "qwen2.5:7b"] and eval_env.searches == []
    assert set(evals.load_results()[eval_env.profile.sha]["voice"]) == {"hermes3", "hermes3@persona",
                                                                          "hermes3@demographic", "qwen25@persona"}


def test_bakeoff_accepts_stored_cell_keys_as_candidates(eval_env, monkeypatch):
    monkeypatch.setattr(gpu.MANAGER, "free_all", lambda: [])
    # a `cand@condition` candidate is exactly that cell (never handed to config.spec unsplit); a plain
    # candidate still fans out over the requested conditions
    entry = evals.run_voice_bakeoff(n_questions=1, judges=("llama31",), candidates=["hermes3@persona", "qwen25"],
                                    conditions=("demographic",))
    assert list(entry["voice"]) == ["hermes3@persona", "qwen25@demographic"]
    gens = [c for c in eval_env.ollama.calls if c["body"].get("format") is None]
    assert [c["body"]["model"] for c in gens] == ["hermes3:8b", "qwen2.5:7b"]
    persona = prompts.build_voice_system(eval_env.profile, DIGEST, [], condition="persona")
    assert gens[0]["body"]["messages"][0]["content"] == persona
    assert eval_env.searches == []  # no interview cell, no embed call
    # the CLI path goes through the same normalisation instead of dying in config.spec
    eval_env.ollama.calls.clear()
    assert evals.main(["--run", "--no-claude", "--candidates", "hermes3@persona", "--judges", "llama31",
                       "--n", "1"]) == 0
    assert eval_env.ollama.calls == []  # cached cell, nothing regenerated


def test_bakeoff_default_condition_keeps_phase1_layout(eval_env):
    entry = evals.run_voice_bakeoff(n_questions=1, judges=("llama31",), candidates=["hermes3", "qwen3_8k"])
    assert list(entry["voice"]) == ["hermes3", "qwen3_8k"] and "@" not in "".join(entry["voice"])
    data = json.loads(eval_env.results_path.read_text(encoding="utf-8"))
    assert set(data[eval_env.profile.sha]) == {"voice", "retrieval", "meta"}
    rec = data[eval_env.profile.sha]["voice"]["hermes3"]["Q-01"]
    assert set(rec) == {"reply", "raw", "ms", "judges", "checker"}


def test_phase1_results_file_replays_unchanged(eval_env):
    """A phase-1-shaped results block (plain candidate keys) goes through summary_rows exactly as before, and a
    resumed interview run on top of it calls no model."""
    sha = eval_env.profile.sha
    rec = lambda n: {"reply": f"r{n}", "raw": f"r{n}", "ms": 1.0,   # noqa: E731
                     "judges": {"llama31": GOOD_SCORES, "qwen25": {**GOOD_SCORES, "overall": 2}},
                     "checker": GOOD_CHECK}
    block = {"voice": {c: {"Q-01": rec(c)} for c in evals.CANDIDATES},
             "retrieval": {"nomic": {"recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0, "mrr": 1.0,
                                     "embed_ms_mean": 5.0, "n": 20, "per_question": []}},
             "meta": {"profile_path": str(EXAMPLE_PROFILE_PATH), "n_questions": 1}}
    evals.save_results({sha: copy.deepcopy(block)})
    rows = evals.summary_rows(block)
    assert [r[0] for r in rows] == evals.CANDIDATES
    assert rows[0] == ["stheno_q4", 1, 4.0, 3.0, 5.0, 3.0, 1.0, "llama31: 4.0 | qwen25: 2.0"]
    assert evals.retrieval_rows(block)[0][:5] == ["nomic", 1.0, 1.0, 1.0, 1.0]
    entry = evals.run_voice_bakeoff(n_questions=1)
    assert eval_env.ollama.calls == [] and eval_env.lms.calls == [] and eval_env.searches == []
    assert entry["voice"] == block["voice"]
    assert evals.summary_rows(evals.results_for_current_profile()) == rows
    # the real phase-1 file on disk (Ari, six plain candidate keys) also replays through summary_rows
    real = ROOT / "data" / "eval_results.json"
    if real.exists():
        data = json.loads(real.read_text(encoding="utf-8"))
        for sha_on_disk, blk in data.items():
            keys = list((blk.get("voice") or {}))
            if keys and all("@" not in k for k in keys):
                assert [r[0] for r in evals.summary_rows(blk)] == keys
                assert all(r[1] > 0 for r in evals.summary_rows(blk))


def test_live_one_condition_skips_retrieval_and_checker(eval_env):
    out = evals.live_one("qwen3_8k", qid="Q-03", judge_key="llama31", condition="persona")
    assert out["condition"] == "persona" and out["qid"] == "Q-03" and out["score"] == GOOD_SCORES
    assert out["checker"] is None
    assert eval_env.searches == []
    assert [c["body"]["model"] for c in eval_env.ollama.calls] == ["qwen3-8b-8k", "llama3.1:8b"]
    assert eval_env.ensured == ["qwen3_8k", "llama31"]
    system = eval_env.ollama.calls[0]["body"]["messages"][0]["content"]
    assert system == prompts.build_voice_system(eval_env.profile, DIGEST, [], condition="persona")
    assert not eval_env.results_path.exists()
    e = _audit_lines(eval_env.audit_path)[-1]
    assert e["tab"] == "eval" and e["condition"] == "persona" and e["chunk_ids"] == []
    assert e["model_keys"] == ["qwen3_8k", "llama31"] and e["ok"] and e["extra"] == {"qid": "Q-03", "step": "live"}
    assert e["request_sha"] == hashlib.sha256(out["question"].encode("utf-8")).hexdigest()
    # interview: unchanged (retrieval, judge, checker) and its audit line carries the chunk ids
    eval_env.ollama.calls.clear()
    eval_env.ensured.clear()
    out = evals.live_one("qwen3_8k", qid="Q-03", judge_key="llama31")
    assert out["condition"] == "interview" and out["checker"] == GOOD_CHECK
    assert [c["body"]["model"] for c in eval_env.ollama.calls] == ["qwen3-8b-8k", "llama3.1:8b", "qwen2.5:7b"]
    assert len(eval_env.searches) == 1
    e = _audit_lines(eval_env.audit_path)[-1]
    assert e["chunk_ids"] == ["Identity", "Decisions/D-01"] and e["model_keys"] == ["qwen3_8k", "llama31", "qwen25"]
    with pytest.raises(ValueError, match="unknown condition"):
        evals.live_one("qwen3_8k", condition="nope")


def test_evals_cli_conditions_flag(eval_env, monkeypatch, capsys):
    monkeypatch.setattr(gpu.MANAGER, "free_all", lambda: [])
    rc = evals.main(["--run", "--n", "1", "--judges", "llama31", "--no-claude", "--candidates", "hermes3",
                     "--conditions", "interview,persona"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hermes3@persona" in out and "hermes3" in out
    assert set(evals.load_results()[eval_env.profile.sha]["voice"]) == {"hermes3", "hermes3@persona"}
    with pytest.raises(SystemExit):
        evals.main(["--run", "--candidates", "hermes3", "--conditions", "nope"])


# ===========================================================================
# voice: pick_voice / stream_in_voice bodies identical to the old Ask path; see.react through reply_in_voice
# ===========================================================================
def test_pick_voice_strings(ask_env):
    assert voice.pick_voice(True, 1.0) == ("stheno_q8", 1.0, "")
    assert voice.pick_voice(False, 1.2) == ("stheno_q4", 1.2, "")
    ask_env.lms.alive_flag = False
    assert voice.pick_voice(False, 1.2) == ("llama32_3b", 0.8, " (LM Studio is down: falling back to llama3.2:3b on Ollama)")
    assert voice.pick_voice(True, None) == ("stheno_q8", None, "")   # Q8 never probes LM Studio
    assert voice.VOICE_Q8_KEY == "stheno_q8" and voice.STREAM_TOKENS == ask.VOICE_TOKENS == 300


def test_stream_in_voice_lms_body_matches_ask(ask_env):
    messages = [{"role": "system", "content": "You are Ari."}, {"role": "user", "content": "hey"}]
    pieces = list(voice.stream_in_voice("stheno_q4", messages, 1.0, "ask"))
    assert "".join(pieces) == LMS_DEFAULT and all(p for p in pieces)
    c = ask_env.lms.calls[0]
    assert c.key == "stheno_q4" and c.stream is True and c.max_tokens == 300 and c.temperature == 1.0
    assert c.tab == "ask" and c.extra is None and c.messages == messages
    assert ask_env.log == [("ensure", "stheno_q4"), ("lms.chat", "stheno_q4", True)]
    # the same call through the Ask turn produces the same LM Studio kwargs
    ask_env.lms.calls.clear()
    events = _events("hey", condition="demographic")
    d = ask_env.lms.calls[0]
    assert (d.key, d.stream, d.max_tokens, d.temperature, d.tab, d.extra) == (c.key, c.stream, c.max_tokens,
                                                                            c.temperature, c.tab, c.extra)
    assert "".join(e["text"] for e in events if e["kind"] == "token") == LMS_DEFAULT
    # a different budget is honoured
    ask_env.lms.calls.clear()
    list(voice.stream_in_voice("stheno_q4", messages, 1.1, "x", max_tokens=42))
    assert ask_env.lms.calls[0].max_tokens == 42 and ask_env.lms.calls[0].temperature == 1.1


def test_stream_in_voice_empty_stream_retries_once_with_note(ask_env):
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    ask_env.lms.scripts["stheno_q4"] = ["", "hello there"]
    notes: list[str] = []
    assert list(voice.stream_in_voice("stheno_q4", messages, 1.0, "ask", on_note=notes.append)) == ["hello there"]
    assert notes == ["voice: empty stream, retrying once without streaming"]
    assert [c.stream for c in ask_env.lms.calls] == [True, False]
    assert ask_env.lms.calls[0].messages == ask_env.lms.calls[1].messages
    assert ask_env.lms.calls[1].max_tokens == 300 and ask_env.lms.calls[1].temperature == 1.0
    assert ask_env.log.count(("ensure", "stheno_q4")) == 1, "the retry stays inside the same session"
    # Ollama (Q8) stream body and its retry
    ask_env.ollama.scripts["stheno_q8"] = ["", "yo"]
    notes.clear()
    assert list(voice.stream_in_voice("stheno_q8", messages, 1.0, "ask", on_note=notes.append)) == ["yo"]
    calls = ask_env.ollama.for_key("stheno_q8")
    s = spec("stheno_q8")
    assert [c.stream for c in calls] == [True, False] and notes == [voice.EMPTY_STREAM_NOTE]
    assert calls[0].options == {"temperature": 1.0} and calls[0].num_predict == 300 and calls[0].tab == "ask"
    assert calls[0].body["options"] == {**s.samplers, "temperature": 1.0, "num_ctx": 8192, "num_predict": 300}
    assert calls[0].body["messages"] == calls[1].body["messages"] and calls[0].body["keep_alive"] == "10m"
    # fallback voice body: temperature 0.8 as before
    ask_env.ollama.scripts["llama32_3b"] = ["the boring one"]
    assert list(voice.stream_in_voice("llama32_3b", messages, 0.8, "ask")) == ["the ", "boring ", "one"]
    fb = ask_env.ollama.for_key("llama32_3b")[0]
    assert fb.options == {"temperature": 0.8} and fb.body["options"]["num_ctx"] == 4096 and fb.stream is True
    assert fb.num_predict == 300 and fb.body["keep_alive"] == "30m"
    # temperature None sends no temperature override
    ask_env.ollama.scripts["llama32_3b"] = ["x"]
    list(voice.stream_in_voice("llama32_3b", messages, None, "ask"))
    assert ask_env.ollama.for_key("llama32_3b")[-1].options == {}


def test_stream_in_voice_early_close_releases_the_session(ask_env):
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    gen = voice.stream_in_voice("stheno_q4", messages, 1.0, "ask")
    assert next(gen)
    gen.close()
    assert gpu.MANAGER.lock.acquire(blocking=False)
    gpu.MANAGER.lock.release()
    # the Ask wrapper turns the retry note into a trace event before the retried text
    ask_env.lms.scripts["stheno_q4"] = ["", "late"]
    evs = list(ask._stream_voice("stheno_q4", messages, 1.0))
    assert [(e["kind"], e["text"]) for e in evs] == [("trace", voice.EMPTY_STREAM_NOTE), ("token", "late")]


def test_see_react_goes_through_reply_in_voice(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)
    monkeypatch.setattr(index, "search_chunks", lambda *a, **k: [dict(c) for c in CHUNKS])
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST)
    see._PROFILE_CACHE.clear()

    def fake_reply(messages, *, max_tokens, tab, temperature=1.0):
        calls.append({"messages": messages, "max_tokens": max_tokens, "tab": tab, "temperature": temperature})
        return ("*grins* Ari: nice", "stheno_q4") if len(calls) == 1 else ("eh", "llama32_3b")

    monkeypatch.setattr(see.voice, "reply_in_voice", fake_reply)
    out = see.react("A dog.")
    assert out["reaction"] == "nice" and out["voice_key"] == "stheno_q4" and out["fallback_reason"] == ""
    assert out["voice_model"] == "l3-8b-stheno-v3.2" and out["chunk_ids"] == [c["id"] for c in CHUNKS]
    assert calls[0]["max_tokens"] == 150 and calls[0]["tab"] == "see" and calls[0]["temperature"] == 1.0
    prof = profile_mod.load_profile(EXAMPLE_PROFILE_PATH)
    assert calls[0]["messages"] == [{"role": "system", "content": prompts.build_voice_system(prof, DIGEST, CHUNKS)},
                                    {"role": "user", "content": "You just saw: A dog.\n" + see.REACTION_INSTRUCTION}]
    out2 = see.react("A cat.")
    assert out2["voice_key"] == "llama32_3b" and out2["voice_model"] == "llama3.2:3b"
    assert out2["fallback_reason"] == see.FALLBACK_REASON == "LM Studio down or the call failed: fell back to llama3.2:3b"
    assert not hasattr(see, "_react_stheno") and not hasattr(see, "_react_fallback")


# ===========================================================================
# UI
# ===========================================================================
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}
_APP: dict = {}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture
def ui_app(monkeypatch):
    """The app built offline (GET-only fakes, any model call fails), cached for this module."""
    monkeypatch.setattr(MANAGER, "status", lambda: dict(FIXED_STATUS))
    monkeypatch.setattr(gpu, "gpu_line", lambda: "")
    for name in ("ps", "tags"):
        monkeypatch.setattr(clients.ollama, name, lambda: [])
    for name in ("models_v0", "models_v1", "loaded"):
        monkeypatch.setattr(clients.lms, name, lambda: [])
    for obj, names in ((clients.ollama, ("chat", "embed", "warm", "stop")), (clients.lms, ("chat", "embed", "unload_all"))):
        for n in names:
            monkeypatch.setattr(obj, n, _boom)
    monkeypatch.delenv("TWIN_NO_WARM", raising=False)
    saved = (MANAGER.active_tab, MANAGER.last_model_tab, dict(MANAGER.tab_overrides))
    if "demo" not in _APP:
        _APP["demo"] = frame.build_app()
    yield _APP["demo"]
    MANAGER.active_tab, MANAGER.last_model_tab = saved[0], saved[1]
    MANAGER.tab_overrides.clear()
    MANAGER.tab_overrides.update(saved[2])


def _public(demo) -> dict:
    return {fn.api_name: fn for fn in demo.fns.values() if fn.api_visibility != "private"}


def test_condition_dropdown_is_the_last_input_of_the_four_endpoints(ui_app):
    pub = _public(ui_app)
    baseline = json.loads((ROOT / "scripts" / "dev" / "view_api_baseline.json").read_text(encoding="utf-8"))
    for name in frame.CONDITION_ENDPOINTS:
        fn = pub[name]
        ins = [c for c in fn.inputs if not isinstance(c, gr.State)]
        last = ins[-1]
        assert isinstance(last, gr.Dropdown), name
        assert last.elem_id == CONDITION_ELEMS[name] and last.value == "interview" and last.label == "Condition"
        assert [c[1] for c in last.choices] == ["demographic", "persona", "interview"]
        assert len(ins) == len(baseline["endpoints"]["/" + name]["parameters"]) + 1, name
        assert fn.concurrency_id == "gpu"
    # nothing else gained an input; the Enter-key submit shares the Ask inputs
    for name, ep in baseline["endpoints"].items():
        key = name.lstrip("/")
        if key in frame.CONDITION_ENDPOINTS:
            continue
        ins = [c for c in pub[key].inputs if not isinstance(c, gr.State)]
        assert len(ins) == len(ep["parameters"]), name
    parts = ui_app.twin_parts
    assert parts["ask"]["condition"].elem_id == "ask-condition"
    assert parts["decide"]["condition"].elem_id == "decide-condition"
    assert parts["eval"]["condition"].elem_id == "eval-condition"
    assert parts["eval"]["probes"].elem_id == "eval-probes"
    submits = [fn for fn in ui_app.fns.values()
               if any(ev == "submit" and ui_app.blocks.get(i) is parts["ask"]["msg"] for i, ev in fn.targets)]
    assert len(submits) == 1 and submits[0].inputs[-1] is parts["ask"]["condition"]


def test_ask_send_passes_the_condition_through(monkeypatch):
    seen: list[dict] = []

    def fake_turn(message, turns, **kw):
        seen.append(dict(kw, message=message, turns=turns))
        yield {"kind": "trace", "text": "t", "data": None}
        yield {"kind": "done", "text": "ok", "data": {"condition": kw.get("condition")}}

    monkeypatch.setattr(ask, "ask_turn", fake_turn)
    monkeypatch.setattr(MANAGER, "set_tab_model", lambda tab, key: None)
    outs = list(ask_ui.ask_send("hi", [], False, 1.0, False, "persona"))
    assert seen[-1]["condition"] == "persona" and seen[-1]["message"] == "hi"
    assert outs[-1][0][-1] == {"role": "assistant", "content": "ok"}
    list(ask_ui.ask_send("hi", [], False, 1.0, False))
    assert seen[-1]["condition"] == "interview"
    list(ask_ui.ask_send("hi", [], True, 1.2, True, None))
    assert seen[-1]["condition"] == "interview" and seen[-1]["use_q8"] is True and seen[-1]["use_checker"] is True


def test_decide_and_eval_handlers_pass_the_condition_through(monkeypatch):
    seen: list[tuple] = []
    result = {"kind": "b1", "verdict": "no", "confidence": 0.5, "reasons": [], "cited_decisions": [], "uncited": [],
              "chunk_ids": [], "model": "m", "timing_ms": 1.0, "attempts": 1, "error": None, "condition": "x"}
    monkeypatch.setattr(decide, "decide_b1", lambda s, condition="interview": seen.append(("b1", s, condition)) or result)
    monkeypatch.setattr(decide, "decide_b2", lambda s, a, b, condition="interview": seen.append(("b2", s, a, b, condition)) or result)
    monkeypatch.setattr(decide, "render_result_markdown", lambda r: "md")
    md, js, st = decide_ui.decide_b1_handler("s", "demographic")
    assert seen[-1] == ("b1", "s", "demographic") and (md, js, st) == ("md", result, result)
    decide_ui.decide_b1_handler("s")
    assert seen[-1] == ("b1", "s", "interview")
    decide_ui.decide_b2_handler("s", "A", "B", "persona")
    assert seen[-1] == ("b2", "s", "A", "B", "persona")
    decide_ui.decide_b2_handler("s", "A", "B", None)
    assert seen[-1] == ("b2", "s", "A", "B", "interview")

    live: list[dict] = []
    monkeypatch.setattr(evals, "live_one", lambda cand, qid, **kw: live.append(dict(kw, cand=cand, qid=qid)) or {"ok": 1})
    assert evals_ui.eval_live_handler("hermes3", "Q-02", "persona") == {"ok": 1}
    assert live[-1] == {"cand": "hermes3", "qid": "Q-02", "condition": "persona"}
    evals_ui.eval_live_handler("", "", "")
    assert live[-1] == {"cand": evals.CANDIDATES[0], "qid": None, "condition": "interview"}


def test_eval_voice_rerun_runs_probes_after_the_bakeoff_and_appends_the_table(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(evals, "run_voice_bakeoff", lambda **kw: order.append("bakeoff") or {})
    monkeypatch.setattr(evals_ui, "eval_tables", lambda: ([["stheno_q4", 1]], []))
    monkeypatch.setattr(clients.anthropic_client, "available", lambda: False)
    fake_probes = SimpleNamespace(
        run_probes=lambda condition="interview", progress=None, judge_key="qwen25": order.append(f"probes:{condition}")
        or {"probes": [], "all_deflected": True},
        markdown_table=lambda cache: "| id | deflected |\n|---|---|\n| P-01 | yes |" if cache else "(no probe results yet)",
        load_cached=lambda profile=None: None,
    )
    monkeypatch.setattr(evals_ui, "probes", fake_probes)
    summary, retrieval, note = evals_ui.eval_voice_rerun(use_claude=False, progress=lambda *a, **k: None)
    assert order == ["bakeoff", "probes:interview"]
    assert "Voice bake-off finished" in note and "| P-01 | yes |" in note and "Boundary probes (interview)" in note
    assert summary == [["stheno_q4", 1]]
    assert evals_ui.probes_markdown() == "(no probe results yet)"
    # without the probes module the note says so and nothing breaks
    monkeypatch.setattr(evals_ui, "probes", None)
    _s, _r, note2 = evals_ui.eval_voice_rerun(use_claude=False, progress=lambda *a, **k: None)
    assert "module not available" in note2 and evals_ui.probes_markdown() == "(no probe results yet)"
