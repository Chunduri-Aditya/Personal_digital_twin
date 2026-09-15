"""Hermetic tests for twin.pipelines.evals: fakes replace the clients, MANAGER.ensure and index.search_chunks.

The Ollama fake builds the request body with the real client's pure `_chat_body`, so every assertion is on
the exact body the server would receive (model, think, format, options.num_ctx, keep_alive, num_predict,
stream, messages). No network, no subprocess, no GPU.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import audit, clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_PATH, spec
from twin.pipelines import digest, evals
from twin.profile import load_profile

_REAL_OLLAMA = clients.ollama  # only its pure _chat_body is used
DIGEST_TEXT = "Ari is a quiet, dry backend developer who picks boring reliable options."
GOOD_SCORES = {"factual_agreement": 4, "voice_fidelity": 3, "no_roleplay_artifacts": 5, "overall": 4, "note": "ok"}
GOOD_CHECK = {"consistent": True, "unsupported_claims": [], "contradictions": []}


def ollama_response(model: str, content: str) -> dict:
    return {"model": model, "message": {"role": "assistant", "content": content}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9,
            "load_duration": 0}


class FakeOllama:
    """Records exact /api/chat bodies; `reply(key, body)` returns content (str) or a full response (dict)."""

    def __init__(self, reply=None):
        self.calls: list[dict] = []
        self.reply = reply

    def default_reply(self, key, body) -> str:
        if body.get("format") == prompts.CHECKER_SCHEMA:
            return json.dumps(GOOD_CHECK)
        if body.get("format") is not None:
            return json.dumps(GOOD_SCORES)
        return f"eh. reply number {len(self.calls)}, probably fine"

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = _REAL_OLLAMA._chat_body(key, messages, options, format, tools, num_predict, stream,
                                          images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        out = self.reply(key, body) if self.reply else self.default_reply(key, body)
        if isinstance(out, dict):
            return out
        return ollama_response(s.name, out)


class FakeLMS:
    """Records the openai chat.completions.create arguments LMSClient.chat would send."""

    def __init__(self, reply=None):
        self.calls: list[dict] = []
        self.reply = reply

    def chat(self, key, messages, *, temperature=None, max_tokens=300, stream=False, extra=None, tab=""):
        s = spec(key)
        assert s.runtime == "lms", key
        extra_body = {k: v for k, v in s.samplers.items() if k in ("min_p", "top_k", "repeat_penalty")}
        extra_body.update(extra or {})
        if temperature is None:
            temperature = s.samplers.get("temperature", 1.0)
        body = {"model": s.name, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "stream": stream, "extra_body": extra_body}
        self.calls.append({"key": key, "body": body, "tab": tab})
        content = self.reply(key, body) if self.reply else f"yo. lms reply {len(self.calls)}"
        msg = SimpleNamespace(role="assistant", content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class FakeAnthropic:
    def __init__(self, available=False, reply=None):
        self._available = available
        self.reply = reply or json.dumps({**GOOD_SCORES, "overall": 5, "note": "ceiling"})
        self.calls: list[dict] = []

    def available(self) -> bool:
        return self._available

    def chat(self, system, messages, *, max_tokens=600, temperature=0.0, tab=""):
        self.calls.append({"system": system, "messages": messages, "tab": tab,
                           "thread": threading.current_thread().name})
        return self.reply


@pytest.fixture
def profile():
    return load_profile(EXAMPLE_PROFILE_PATH)


@pytest.fixture
def env(monkeypatch, tmp_path: Path, profile):
    """Wire every fake; returns a namespace with the recorders."""
    ollama = FakeOllama()
    lms = FakeLMS()
    anth = FakeAnthropic(available=False)
    ensured: list[str] = []
    searches: list[dict] = []
    by_id = {c.id: asdict(c) for c in profile.chunks}
    fixed_chunks = [{**by_id["Identity"], "score": 0.9}, {**by_id["Decisions/D-01"], "score": 0.8}]

    def fake_search(index_key, query, k=5, boost=None, tab=""):
        searches.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
        return [dict(c) for c in fixed_chunks]

    monkeypatch.setattr(clients, "ollama", ollama)
    monkeypatch.setattr(clients, "lms", lms)
    monkeypatch.setattr(clients, "anthropic_client", anth)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    monkeypatch.setattr(index, "search_chunks", fake_search)
    monkeypatch.setattr(index, "chunk_lookup", lambda: dict(by_id))
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST_TEXT)
    monkeypatch.setattr(config, "EVAL_RESULTS_PATH", tmp_path / "eval_results.json")
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")   # audit lines never reach data/
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_PATH)  # pin Ari (v1)
    return SimpleNamespace(ollama=ollama, lms=lms, anth=anth, ensured=ensured, searches=searches,
                           chunks=fixed_chunks, by_id=by_id, results_path=tmp_path / "eval_results.json",
                           audit_path=tmp_path / "audit.jsonl", profile=profile)


def collapse(seq):
    out = []
    for x in seq:
        if not out or out[-1] != x:
            out.append(x)
    return out


def gen_calls(env):
    """Generation requests (no format) across both runtimes, in call order."""
    return [c for c in env.ollama.calls if c["body"].get("format") is None] + env.lms.calls


def judge_calls(env):
    return [c for c in env.ollama.calls if c["body"].get("format") == prompts.JUDGE_SCHEMA]


def checker_calls(env):
    return [c for c in env.ollama.calls if c["body"].get("format") == prompts.CHECKER_SCHEMA]


CANDIDATE_NAMES = [spec(c).name for c in evals.CANDIDATES]


# ---------------------------------------------------------------------------
# voice bake-off: ordering and request bodies
# ---------------------------------------------------------------------------

def test_candidate_order_and_one_session_per_candidate_then_judges(env):
    entry = evals.run_voice_bakeoff(n_questions=2)
    assert list(entry["voice"]) == evals.CANDIDATES
    assert collapse(env.ensured) == evals.CANDIDATES + list(evals.JUDGES)
    # generation happens for every candidate before any judge call
    kinds = ["judge" if c["body"].get("format") is not None else "gen" for c in env.ollama.calls]
    assert "gen" not in kinds[kinds.index("judge"):]
    assert len(env.lms.calls) == 2  # stheno_q4 x 2 questions
    assert len(gen_calls(env)) == 6 * 2
    assert len(judge_calls(env)) == 2 * 6 * 2
    assert len(checker_calls(env)) == 6 * 2
    assert all(c["tab"] == "eval" for c in env.ollama.calls + env.lms.calls)


def test_checker_runs_on_every_reply_while_qwen25_is_loaded(env):
    entry = evals.run_voice_bakeoff(n_questions=2)
    cc = checker_calls(env)
    assert len(cc) == 12
    # the checker calls come right after qwen25's judge calls (no extra model swap) and before nothing else
    models = [c["body"]["model"] for c in env.ollama.calls if c["body"].get("format") is not None]
    assert models[-12:] == ["qwen2.5:7b"] * 12 and models[-24:-12] == ["qwen2.5:7b"] * 12
    assert collapse(env.ensured) == evals.CANDIDATES + list(evals.JUDGES)
    replies = {rec["reply"] for c in entry["voice"].values() for rec in c.values()}
    for c in cc:
        b = c["body"]
        assert b["model"] == "qwen2.5:7b" and b["format"] == prompts.CHECKER_SCHEMA
        assert b["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 300}
        assert b["keep_alive"] == "10m" and b["stream"] is False and "think" not in b
        assert b["messages"][0] == {"role": "system", "content": prompts.CHECKER_SYSTEM}
        user = b["messages"][1]["content"]
        assert user.startswith("CONTEXT:\n[1] (") and "\n\nREPLY:\n" in user
        assert env.by_id["Decisions/D-01"]["text"] in user
        assert user.split("\n\nREPLY:\n", 1)[1] in replies
    for cand in evals.CANDIDATES:
        for qid in ("Q-01", "Q-02"):
            assert entry["voice"][cand][qid]["checker"] == GOOD_CHECK
    rows = evals.summary_rows(entry)
    assert all(r[6] == 1.0 for r in rows)
    # checker disabled: no CHECKER_SCHEMA request at all
    env.ollama.calls.clear()
    results = evals.load_results()
    for c in results[env.profile.sha]["voice"].values():
        for rec in c.values():
            rec.pop("checker")
    evals.save_results(results)
    evals.run_voice_bakeoff(n_questions=2, use_checker=False)
    assert env.ollama.calls == []


def test_checker_without_qwen25_judge_runs_after_the_judges_and_retries_on_length(env, monkeypatch):
    seq = {"n": 0}

    def reply(key, body):
        if body.get("format") == prompts.CHECKER_SCHEMA:
            seq["n"] += 1
            if seq["n"] == 1:
                return {**ollama_response(spec(key).name, '{"consistent": true, "unsupported_claims": ["a", "b"'),
                        "done_reason": "length"}
            return json.dumps({"consistent": False, "unsupported_claims": ["x"], "contradictions": []})
        if body.get("format") is not None:
            return json.dumps(GOOD_SCORES)
        return "eh."

    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=reply))
    entry = evals.run_voice_bakeoff(n_questions=1, judges=("llama31",), candidates=["hermes3", "qwen3_8k"])
    assert collapse(env.ensured) == ["hermes3", "qwen3_8k", "llama31", "qwen25"]
    cc = [c for c in clients.ollama.calls if c["body"].get("format") == prompts.CHECKER_SCHEMA]
    assert [c["body"]["options"]["num_predict"] for c in cc] == [300, 600, 300]
    assert cc[0]["body"]["messages"] == cc[1]["body"]["messages"]
    bad = {"consistent": False, "unsupported_claims": ["x"], "contradictions": []}
    assert entry["voice"]["hermes3"]["Q-01"]["checker"] == bad
    assert entry["voice"]["qwen3_8k"]["Q-01"]["checker"] == bad
    assert evals.summary_rows(entry)[0][6] == 0.0
    # an error verdict is retried on resume; a good one is not
    results = evals.load_results()
    results[env.profile.sha]["voice"]["hermes3"]["Q-01"]["checker"] = {"consistent": None, "error": "boom"}
    evals.save_results(results)
    clients.ollama.calls.clear()
    evals.run_voice_bakeoff(n_questions=1, judges=("llama31",), candidates=["hermes3", "qwen3_8k"])
    assert [c["body"]["format"] for c in clients.ollama.calls] == [prompts.CHECKER_SCHEMA]


def test_bad_keys_are_rejected_before_any_model_call(env):
    with pytest.raises(ValueError, match="claude"):
        evals.run_voice_bakeoff(candidates=["claude"])
    with pytest.raises(ValueError, match="stheno_q4"):
        evals.run_voice_bakeoff(candidates=["hermes3"], judges=["stheno_q4"])
    with pytest.raises(ValueError, match="nomic"):
        evals.run_voice_bakeoff(candidates=["nomic"])
    with pytest.raises(ValueError, match="claude"):
        evals.live_one("hermes3", judge_key="claude")
    with pytest.raises(ValueError, match="stheno_q4"):
        evals.live_one("qwen3_8k", judge_key="stheno_q4")
    assert env.ollama.calls == [] and env.lms.calls == [] and env.ensured == [] and env.searches == []
    assert not env.results_path.exists()


def test_stheno_q4_goes_to_lms_with_samplers_and_system_message(env):
    evals.run_voice_bakeoff(n_questions=1, judges=())
    assert len(env.lms.calls) == 1
    c = env.lms.calls[0]
    assert c["key"] == "stheno_q4"
    b = c["body"]
    assert b["model"] == "l3-8b-stheno-v3.2"
    assert b["temperature"] == 1.15
    assert b["max_tokens"] == 300
    assert b["stream"] is False
    assert b["extra_body"] == {"min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1}
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert b["messages"][1]["content"] == env.profile.eval[0].question
    assert "stheno_q4" not in [c["key"] for c in env.ollama.calls]


def test_stheno_q8_goes_to_ollama_with_system_message_and_card_samplers(env):
    evals.run_voice_bakeoff(n_questions=1, judges=())
    calls = [c for c in env.ollama.calls if c["key"] == "stheno_q8"]
    assert len(calls) == 1
    b = calls[0]["body"]
    assert b["model"] == "fluffy/l3-8b-stheno-v3.2:q8_0"
    assert b["messages"][0]["role"] == "system"
    assert b["messages"][-1] == {"role": "user", "content": env.profile.eval[0].question}
    assert b["options"] == {"temperature": 1.15, "min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1,
                            "num_ctx": 8192, "num_predict": 300}
    assert b["keep_alive"] == "10m"
    assert b["stream"] is False
    assert "think" not in b and "format" not in b and "tools" not in b


def test_qwen3_8k_request_has_think_false_and_num_predict_300(env):
    evals.run_voice_bakeoff(n_questions=1, judges=())
    calls = [c for c in env.ollama.calls if c["key"] == "qwen3_8k"]
    assert len(calls) == 1
    b = calls[0]["body"]
    assert b["model"] == "qwen3-8b-8k"
    assert b["think"] is False
    assert b["options"] == {"temperature": 0.7, "num_ctx": 8192, "num_predict": 300}
    assert b["keep_alive"] == "10m"
    assert b["stream"] is False
    for key in ("llama31", "qwen25", "hermes3"):
        b2 = next(c for c in env.ollama.calls if c["key"] == key)["body"]
        assert b2["model"] == spec(key).name
        assert b2["options"] == {"temperature": 0.7, "num_ctx": 8192, "num_predict": 300}
        assert b2["keep_alive"] == "10m"
        assert "think" not in b2


def test_identical_system_string_for_all_candidates_per_question(env):
    evals.run_voice_bakeoff(n_questions=2, judges=())
    qid_of = {q.question: q.qid for q in env.profile.eval[:2]}
    systems: dict[str, set[str]] = {}
    for c in gen_calls(env):
        msgs = c["body"]["messages"]
        systems.setdefault(qid_of[msgs[-1]["content"]], set()).add(msgs[0]["content"])
    assert set(systems) == {"Q-01", "Q-02"}
    for qid, s in systems.items():
        assert len(s) == 1, qid
        system = next(iter(s))
        assert system.startswith(prompts.VOICE_SYSTEM("Ari"))
        assert "CONTEXT:" in system and DIGEST_TEXT in system
        assert env.by_id["Decisions/D-01"]["text"] in system
    # retrieval was precomputed with nomic, k=5, tab eval, once per question, before any model call
    assert [s["index_key"] for s in env.searches] == ["nomic", "nomic"]
    assert all(s["k"] == 5 and s["tab"] == "eval" for s in env.searches)
    assert [s["query"] for s in env.searches] == [q.question for q in env.profile.eval[:2]]


def test_judge_requests_are_anonymised_llama31_then_qwen25(env):
    evals.run_voice_bakeoff(n_questions=2)
    jc = judge_calls(env)
    assert [c["body"]["model"] for c in jc] == ["llama3.1:8b"] * 12 + ["qwen2.5:7b"] * 12
    forbidden = evals.CANDIDATES + CANDIDATE_NAMES
    gold = {q.qid: q.answer for q in env.profile.eval[:2]}
    for c in jc:
        b = c["body"]
        assert b["format"] == prompts.JUDGE_SCHEMA
        assert b["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 300}
        assert b["keep_alive"] == "10m" and b["stream"] is False and "think" not in b
        assert b["messages"][0] == {"role": "system", "content": prompts.JUDGE_SYSTEM}
        user = b["messages"][1]["content"]
        for tag in ("QUESTION:\n", "\n\nGOLD:\n", "\n\nSTYLE RULES:\n", "\n\nCANDIDATE:\n"):
            assert tag in user
        assert env.profile.style_rules in user
        assert any(g in user for g in gold.values())
        joined = "\n".join(m["content"] for m in b["messages"])
        for bad in forbidden:
            assert bad not in joined, bad
    # every (candidate, qid) got both judges' scores
    entry = evals.load_results()[env.profile.sha]
    for cand in evals.CANDIDATES:
        for qid in ("Q-01", "Q-02"):
            rec = entry["voice"][cand][qid]
            assert set(rec["judges"]) == {"llama31", "qwen25"}
            assert rec["judges"]["llama31"] == GOOD_SCORES


# ---------------------------------------------------------------------------
# persistence and resume
# ---------------------------------------------------------------------------

def test_results_saved_after_every_call_and_second_run_resumes(env, monkeypatch):
    real_save = evals.save_results
    writes = []
    monkeypatch.setattr(evals, "save_results", lambda results: writes.append(real_save(results)))
    entry = evals.run_voice_bakeoff(n_questions=2)
    n_model_calls = len(env.ollama.calls) + len(env.lms.calls)
    assert n_model_calls == 12 + 24 + 12  # replies + two judges + checker
    assert len(writes) >= n_model_calls
    data = json.loads(env.results_path.read_text(encoding="utf-8"))
    assert list(data) == [env.profile.sha]
    assert set(data[env.profile.sha]) == {"voice", "retrieval", "meta"}
    assert data[env.profile.sha]["meta"]["n_questions"] == 2
    assert data[env.profile.sha]["meta"]["profile_path"] == str(EXAMPLE_PROFILE_PATH)
    rec = data[env.profile.sha]["voice"]["stheno_q4"]["Q-01"]
    assert set(rec) == {"reply", "raw", "ms", "judges", "checker"}
    assert rec["reply"] and isinstance(rec["ms"], float)
    assert entry == data[env.profile.sha]

    env.ollama.calls.clear()
    env.lms.calls.clear()
    env.ensured.clear()
    env.searches.clear()
    again = evals.run_voice_bakeoff(n_questions=2)
    assert env.ollama.calls == [] and env.lms.calls == [] and env.ensured == []
    assert env.searches == []  # a fully cached re-run does not even embed the queries
    assert again["voice"] == entry["voice"]
    # a partial resume retrieves only the questions that still need work
    evals.run_voice_bakeoff(n_questions=3)
    assert [s["query"] for s in env.searches] == [env.profile.eval[2].question]


def test_resume_only_fills_the_missing_cells(env):
    evals.run_voice_bakeoff(n_questions=1, judges=("llama31",))
    env.ollama.calls.clear()
    env.lms.calls.clear()
    evals.run_voice_bakeoff(n_questions=2, judges=("llama31", "qwen25"))
    # replies for Q-02 only (6), llama31 judges Q-02 only (6), qwen25 judges both (12)
    assert len(gen_calls(env)) == 6
    assert [c["body"]["messages"][-1]["content"] for c in gen_calls(env)] == [env.profile.eval[1].question] * 6
    jc = judge_calls(env)
    assert [c["body"]["model"] for c in jc] == ["llama3.1:8b"] * 6 + ["qwen2.5:7b"] * 12


def test_error_judge_entries_are_retried_on_resume(env):
    evals.run_voice_bakeoff(n_questions=1, judges=("llama31",))
    results = evals.load_results()
    results[env.profile.sha]["voice"]["hermes3"]["Q-01"]["judges"]["llama31"] = {"error": "invalid judge JSON"}
    evals.save_results(results)
    env.ollama.calls.clear()
    evals.run_voice_bakeoff(n_questions=1, judges=("llama31",))
    assert len(env.ollama.calls) == 1 and env.ollama.calls[0]["body"].get("format") is not None
    assert evals.load_results()[env.profile.sha]["voice"]["hermes3"]["Q-01"]["judges"]["llama31"] == GOOD_SCORES


# ---------------------------------------------------------------------------
# claude judge
# ---------------------------------------------------------------------------

def test_claude_judge_not_called_when_unavailable(env):
    msgs = []
    entry = evals.run_voice_bakeoff(n_questions=1, judges=("llama31",), progress=msgs.append)
    assert env.anth.calls == []
    assert all("claude" not in rec["judges"] for c in entry["voice"].values() for rec in c.values())
    entry = evals.run_voice_bakeoff(n_questions=1, judges=("llama31",), use_claude=True, progress=msgs.append)
    assert env.anth.calls == []
    assert any("skipping" in m for m in msgs)
    assert evals.claude_judge("q", "g", "s", "r") == {"error": "anthropic unavailable"}


def test_claude_judge_runs_in_side_thread_when_available(env, monkeypatch):
    anth = FakeAnthropic(available=True, reply='```json\n{"factual_agreement": 5, "voice_fidelity": 4, '
                                                '"no_roleplay_artifacts": 5, "overall": 5, "note": "ceiling"}\n```')
    monkeypatch.setattr(clients, "anthropic_client", anth)
    entry = evals.run_voice_bakeoff(n_questions=2, judges=("llama31",))
    assert len(anth.calls) == 12
    for c in anth.calls:
        assert c["system"] == prompts.JUDGE_SYSTEM + " Output JSON only."
        assert c["thread"] != threading.main_thread().name
        assert [m["role"] for m in c["messages"]] == ["user"]
        assert "CANDIDATE:\n" in c["messages"][0]["content"]
        for bad in evals.CANDIDATES + CANDIDATE_NAMES:
            assert bad not in c["messages"][0]["content"]
    for cand in evals.CANDIDATES:
        for qid in ("Q-01", "Q-02"):
            assert entry["voice"][cand][qid]["judges"]["claude"] == {
                "factual_agreement": 5, "voice_fidelity": 4, "no_roleplay_artifacts": 5, "overall": 5,
                "note": "ceiling"}
    assert "claude" not in env.ensured  # never enters the GPU manager
    # use_claude=False suppresses it even when available
    anth.calls.clear()
    evals.run_voice_bakeoff(n_questions=3, judges=(), use_claude=False)
    assert anth.calls == []


# ---------------------------------------------------------------------------
# generate_reply / judge_reply unit behaviour
# ---------------------------------------------------------------------------

def test_generate_reply_retries_once_on_empty_content(env, monkeypatch):
    seq = iter(["", "*grins* Ari: hey. mostly time, not money"])
    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=lambda key, body: next(seq)))
    out = evals.generate_reply("hermes3", "SYS", "q?", name="Ari")
    assert out == "hey. mostly time, not money"
    assert len(clients.ollama.calls) == 2
    assert env.ensured == ["hermes3", ]
    # empty twice -> exactly two calls, empty reply
    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=lambda key, body: ""))
    assert evals.generate_reply("qwen25", "SYS", "q?", name="Ari") == ""
    assert len(clients.ollama.calls) == 2
    # same for the LM Studio candidate
    seq2 = iter(["", "yo"])
    monkeypatch.setattr(clients, "lms", FakeLMS(reply=lambda key, body: next(seq2)))
    assert evals.generate_reply("stheno_q4", "SYS", "q?", name="Ari") == "yo"
    assert len(clients.lms.calls) == 2


def test_judge_scores_are_clamped_to_1_5(env, monkeypatch):
    raw = {"factual_agreement": 9, "voice_fidelity": 0, "no_roleplay_artifacts": 3.7, "overall": "-2", "note": None}
    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=lambda key, body: json.dumps(raw)))
    out = evals.judge_reply("llama31", "q", "gold", "rules", "reply")
    assert out == {"factual_agreement": 5, "voice_fidelity": 1, "no_roleplay_artifacts": 4, "overall": 1, "note": ""}
    assert len(clients.ollama.calls) == 1
    assert env.ensured == ["llama31"]
    assert evals.clamp_scores({"factual_agreement": 3}) is None
    assert evals.clamp_scores(None) is None


def test_invalid_judge_json_retries_once_then_error(env, monkeypatch):
    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=lambda key, body: "not json at all"))
    out = evals.judge_reply("qwen25", "q", "gold", "rules", "reply")
    assert len(clients.ollama.calls) == 2
    assert out["error"] == "invalid judge JSON" and out["raw"] == "not json at all"
    assert all(c["body"]["model"] == "qwen2.5:7b" and c["body"]["format"] == prompts.JUDGE_SCHEMA
               for c in clients.ollama.calls)
    # the retry is not byte-identical (temp 0 is greedy): it gets a bigger token budget
    assert [c["body"]["options"]["num_predict"] for c in clients.ollama.calls] == [300, 600]
    assert clients.ollama.calls[0]["body"]["messages"] == clients.ollama.calls[1]["body"]["messages"]
    # invalid then valid -> two calls and real scores (also exercises "text around the JSON")
    seq = iter(["", "Sure! " + json.dumps(GOOD_SCORES) + " done."])
    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=lambda key, body: next(seq)))
    assert evals.judge_reply("llama31", "q", "gold", "rules", "reply") == GOOD_SCORES
    assert len(clients.ollama.calls) == 2


def test_truncated_judge_json_is_retried_with_num_predict_600(env, monkeypatch):
    truncated = '{"factual_agreement": 4, "voice_fidelity": 3, "no_roleplay_artifacts": 5, "note": "this went on and'
    seq = iter([{**ollama_response("llama3.1:8b", truncated), "done_reason": "length"}, json.dumps(GOOD_SCORES)])
    monkeypatch.setattr(clients, "ollama", FakeOllama(reply=lambda key, body: next(seq)))
    assert evals.judge_reply("llama31", "q", "gold", "rules", "reply") == GOOD_SCORES
    bodies = [c["body"] for c in clients.ollama.calls]
    assert [b["options"]["num_predict"] for b in bodies] == [300, 600]
    assert bodies[0]["options"]["temperature"] == 0 and bodies[1]["options"]["temperature"] == 0
    assert bodies[0]["messages"] == bodies[1]["messages"]
    assert env.ensured == ["llama31"]


def test_parse_json_object():
    assert evals.parse_json_object('{"a": 1}') == {"a": 1}
    assert evals.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert evals.parse_json_object("[1, 2]") is None
    assert evals.parse_json_object("") is None
    assert evals.parse_json_object("{broken") is None


# ---------------------------------------------------------------------------
# retrieval bake-off
# ---------------------------------------------------------------------------

def test_ground_truth_is_highest_lexical_overlap(env):
    qa = {q.qid: q.answer for q in env.profile.eval}
    assert evals.ground_truth_chunk(qa["Q-02"], env.by_id) == "Decisions/D-06"
    # containment, not Jaccard: a 1-line Voice sample sharing one word must not beat the Decisions chunk
    assert evals.ground_truth_chunk(qa["Q-07"], env.by_id) == "Decisions/D-01"
    assert evals.ground_truth_chunk(qa["Q-01"], env.by_id) == "Decisions/D-01"
    assert evals.ground_truth_chunk(qa["Q-06"], env.by_id) == "Decisions/D-05"
    assert evals.ground_truth_chunk(qa["Q-08"], env.by_id) == "Decisions/D-04"
    assert evals.ground_truth_chunk(qa["Q-11"], env.by_id) == "Decisions/D-10"
    assert evals.ground_truth_chunk(qa["Q-18"], env.by_id) == "Decisions/D-09"
    assert evals.ground_truth_chunk(qa["Q-19"], env.by_id) == "Decisions/D-12"
    assert evals.containment({"a", "b", "c"}, {"a", "b", "zzz"}) == pytest.approx(2 / 3)
    assert evals.containment(set(), {"a"}) == 0.0
    assert evals.ground_truth_chunk("x\nSources: Decisions/D-03", env.by_id) == "Decisions/D-03"
    assert evals.ground_truth_chunk("", env.by_id) is None
    assert evals.lexical_words("The Laptop's battery, i'd say, is fine!") == {"laptop", "battery", "say", "fine"}
    assert evals.jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert evals.jaccard(set(), set()) == 0.0


def _retrieval_fake(env, monkeypatch, gt_position: int):
    gts = {q.question: evals.ground_truth_chunk(q.answer, env.by_id) for q in env.profile.eval}
    calls = []

    def fake_search(index_key, query, k=5, boost=None, tab=""):
        calls.append({"index_key": index_key, "k": k, "tab": tab})
        gt = gts[query]
        decoys = [cid for cid in env.by_id if cid != gt][:k]
        ids = decoys[:gt_position] + [gt] + decoys[gt_position:]
        return [{**env.by_id[cid], "score": 1.0 - i / 10} for i, cid in enumerate(ids[:k])]

    monkeypatch.setattr(index, "search_chunks", fake_search)
    return calls


def test_retrieval_bakeoff_gt_first(env, monkeypatch):
    calls = _retrieval_fake(env, monkeypatch, gt_position=0)
    ret = evals.run_retrieval_bakeoff()
    assert list(ret) == evals.RETRIEVAL_INDEXES
    for ik in evals.RETRIEVAL_INDEXES:
        r = ret[ik]
        assert r["recall@1"] == 1.0 and r["recall@3"] == 1.0 and r["recall@5"] == 1.0 and r["mrr"] == 1.0
        assert r["n"] == 20 and len(r["per_question"]) == 20
        assert isinstance(r["embed_ms_mean"], float)
        assert all(p["rank"] == 1 and p["top"][0] == p["gt"] for p in r["per_question"])
    assert [c["index_key"] for c in calls] == [ik for ik in evals.RETRIEVAL_INDEXES for _ in range(20)]
    assert all(c["k"] == 5 and c["tab"] == "eval" for c in calls)
    saved = evals.load_results()[env.profile.sha]["retrieval"]
    assert saved == ret
    assert env.ollama.calls == [] and env.lms.calls == []


def test_retrieval_bakeoff_gt_second_gives_half_mrr(env, monkeypatch):
    _retrieval_fake(env, monkeypatch, gt_position=1)
    ret = evals.run_retrieval_bakeoff(indexes=["nomic"])
    r = ret["nomic"]
    assert r["recall@1"] == 0.0 and r["recall@3"] == 1.0 and r["recall@5"] == 1.0
    assert r["mrr"] == 0.5
    assert "gemma" not in ret


def test_retrieval_bakeoff_records_error_for_missing_index(env, monkeypatch):
    def boom(index_key, query, k=5, boost=None, tab=""):
        raise FileNotFoundError(f"index_{index_key}.npz")
    monkeypatch.setattr(index, "search_chunks", boom)
    ret = evals.run_retrieval_bakeoff(indexes=["gemma"])
    assert ret["gemma"]["error"].startswith("FileNotFoundError")
    assert ret["gemma"]["mrr"] == 0.0
    rows = evals.retrieval_rows(evals.load_results()[env.profile.sha])
    assert rows[0][0] == "gemma" and rows[0][-1].startswith("FileNotFoundError")


# ---------------------------------------------------------------------------
# tables and CLI
# ---------------------------------------------------------------------------

def test_summary_rows_on_empty_results():
    assert evals.summary_rows({}) == []
    assert evals.summary_rows(None) == []
    assert evals.summary_rows({"voice": {}}) == []
    assert evals.retrieval_rows({}) == []
    assert evals.retrieval_rows({"retrieval": {}}) == []


def test_summary_rows_means_and_missing_data():
    entry = {"voice": {
        "qwen25": {"Q-01": {"reply": "a", "raw": "a", "ms": 1.0, "judges": {
            "llama31": {"factual_agreement": 4, "voice_fidelity": 2, "no_roleplay_artifacts": 5, "overall": 3, "note": ""},
            "claude": {"factual_agreement": 5, "voice_fidelity": 5, "no_roleplay_artifacts": 5, "overall": 5, "note": ""},
        }}, "Q-02": {"reply": "b", "raw": "b", "ms": 1.0, "judges": {
            "llama31": {"factual_agreement": 2, "voice_fidelity": 4, "no_roleplay_artifacts": 3, "overall": 4, "note": ""},
            "qwen25": {"error": "invalid judge JSON"},
        }, "checker": {"consistent": False, "unsupported_claims": ["x"], "contradictions": []}}},
        "stheno_q4": {"Q-01": {"reply": "c", "raw": "c", "ms": 2.0, "judges": {},
                               "checker": {"consistent": None, "error": "boom"}}},
        "hermes3": {},
    }}
    entry["voice"]["qwen25"]["Q-01"]["checker"] = {"consistent": True, "unsupported_claims": [], "contradictions": []}
    rows = evals.summary_rows(entry)
    assert [r[0] for r in rows] == ["stheno_q4", "qwen25", "hermes3"]  # CANDIDATES order
    assert rows[0] == ["stheno_q4", 1, None, None, None, None, None, ""]
    assert rows[1] == ["qwen25", 2, 3.67, 3.67, 4.33, 4.0, 0.5, "llama31: 3.5 | claude: 5.0"]
    assert rows[2] == ["hermes3", 0, None, None, None, None, None, ""]
    assert len(evals.SUMMARY_HEADERS) == len(rows[0])


def test_cli_show_prints_cached_tables_without_model_calls(env, capsys):
    results = {env.profile.sha: {"voice": {"qwen3_8k": {"Q-01": {"reply": "x", "raw": "x", "ms": 3.0, "judges": {
        "llama31": GOOD_SCORES}}}}, "retrieval": {"nomic": {"recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0,
        "mrr": 1.0, "embed_ms_mean": 12.5, "n": 20, "per_question": []}}, "meta": {}}}
    evals.save_results(results)
    assert evals.main(["--show"]) == 0
    out = capsys.readouterr().out
    assert "qwen3_8k" in out and "llama31: 4.0" in out and "nomic" in out and "12.50" in out
    assert env.ollama.calls == [] and env.lms.calls == [] and env.ensured == []
    assert evals.main([]) == 0  # help only


def test_cli_run_parses_flags_and_frees_gpu(env, monkeypatch, capsys):
    freed = []
    monkeypatch.setattr(gpu.MANAGER, "free_all", lambda: freed.append(True) or ["ollama stop x"])
    rc = evals.main(["--run", "--n", "1", "--judges", "qwen25", "--no-claude", "--candidates", "hermes3,qwen3_8k",
                     "--retrieval"])
    assert rc == 0
    assert freed == [True]
    assert collapse(env.ensured) == ["hermes3", "qwen3_8k", "qwen25"]
    assert [c["body"]["model"] for c in judge_calls(env)] == ["qwen2.5:7b", "qwen2.5:7b"]
    out = capsys.readouterr().out
    assert "hermes3" in out and "Retrieval bake-off" in out
    entry = evals.load_results()[env.profile.sha]
    assert set(entry["voice"]) == {"hermes3", "qwen3_8k"}
    assert set(entry["retrieval"]) == set(evals.RETRIEVAL_INDEXES)
    with pytest.raises(SystemExit):
        evals.main(["--run", "--candidates", "nope"])


def test_live_one_retrieves_generates_and_judges(env):
    out = evals.live_one("qwen3_8k", qid="Q-03", judge_key="llama31")
    assert out["qid"] == "Q-03" and out["candidate"] == "qwen3_8k"
    assert out["gold"] == next(q.answer for q in env.profile.eval if q.qid == "Q-03")
    assert out["reply"] and out["score"] == GOOD_SCORES
    assert out["checker"] == GOOD_CHECK  # the qwen25 consistency checker is always on in Eval
    assert [c["body"]["model"] for c in env.ollama.calls] == ["qwen3-8b-8k", "llama3.1:8b", "qwen2.5:7b"]
    assert env.ensured == ["qwen3_8k", "llama31", "qwen25"]
    assert env.searches[0]["query"] == out["question"]
    assert not env.results_path.exists()  # live demo is not cached


def test_live_one_can_skip_the_checker(env):
    out = evals.live_one("qwen3_8k", qid="Q-03", judge_key="llama31", use_checker=False)
    assert out["checker"] is None
    assert [c["body"]["model"] for c in env.ollama.calls] == ["qwen3-8b-8k", "llama3.1:8b"]
