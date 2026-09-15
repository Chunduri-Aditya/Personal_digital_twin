"""Hermetic tests for twin.pipelines.items: fakes replace the clients, MANAGER.ensure/free_all and index.search_chunks;
every data path points at tmp_path. The Ollama fake builds the request body with the real client's pure _chat_body,
so assertions are on the exact body the server would receive. No network, no subprocess, no GPU."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from twin import audit, clients, config, gpu, index, prompts
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_V2_PATH, spec
from twin.pipelines import digest, items
from twin.prompts import CONDITIONS

DIGEST = "mara is a freelance illustrator who decides by gut, hates being managed and keeps a cash buffer."
GOOD_SCORES = {"factual_agreement": 4, "voice_fidelity": 3, "no_roleplay_artifacts": 5, "overall": 4, "note": "ok"}
CHUNK_IDS = ["Identity", "Values", "Decisions/D-01", "Expert reflections/Psychologist", "Interview highlights/On money"]


def ollama_response(model: str, content: str, done_reason: str = "stop") -> dict:
    return {"model": model, "message": {"role": "assistant", "content": content}, "done": True,
            "done_reason": done_reason, "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9,
            "load_duration": 0}


class FakeOllama:
    """Records exact /api/chat bodies; `reply(key, body, n)` may override the default per-schema answer."""

    def __init__(self, reply=None):
        self.calls: list[dict] = []
        self.reply = reply

    def default_reply(self, key, body) -> str:
        fmt = body.get("format")
        if fmt == prompts.JUDGE_SCHEMA:
            return json.dumps(GOOD_SCORES)
        if isinstance(fmt, dict):
            props = fmt["properties"]
            if "item_id" in props:
                iid = props["item_id"]["enum"][0]
                a = props["answer"]
                if a.get("type") == "integer":
                    return json.dumps({"item_id": iid, "answer": 2 + (len(self.calls) % 3)})
                return json.dumps({"item_id": iid, "answer": a["enum"][0]})
            game = props["game"]["enum"][0]
            if "give" in props:
                return json.dumps({"game": game, "give": 4})
            if "fraction" in props:
                return json.dumps({"game": game, "fraction": 0.5})
            return json.dumps({"game": game, "action": "cooperate"})
        return "plain text"

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = clients.OllamaClient._chat_body(self, key, messages, options, format, tools, num_predict, stream,
                                                  images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        out = self.reply(key, body, len(self.calls)) if self.reply else None
        if out is None:
            out = self.default_reply(key, body)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, dict):
            return out
        return ollama_response(s.name, out)


class FakeLMS:
    """Records the openai chat.completions.create arguments LMSClient.chat would send."""

    def __init__(self, reply=None):
        self.calls: list[dict] = []
        self.reply = reply

    def alive(self) -> bool:
        return True

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
        content = self.reply(key, body) if self.reply else f"ok wait, honestly reply {len(self.calls)}, idk"
        msg = SimpleNamespace(role="assistant", content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


@pytest.fixture
def profile():
    return profile_mod.load_profile(EXAMPLE_PROFILE_V2_PATH)


@pytest.fixture
def env(monkeypatch, tmp_path: Path, profile):
    """Wire every fake and every data path; returns a namespace with the recorders."""
    ollama = FakeOllama()
    lms = FakeLMS()
    ensured: list[str] = []
    freed: list[int] = []
    searches: list[dict] = []
    by_id = {c.id: {**asdict(c), "source": index.infer_source(c.id)} for c in profile.chunks}
    fixed_chunks = [{**by_id[cid], "score": round(0.9 - 0.05 * i, 2)} for i, cid in enumerate(CHUNK_IDS)]

    def fake_search(index_key, query, k=5, boost=None, tab="", sources=None):
        searches.append({"index_key": index_key, "query": query, "k": k, "boost": boost, "tab": tab})
        return [dict(c) for c in fixed_chunks]

    saves: list[int] = []
    real_save = items.save_twin_answers

    def counting_save(results):
        saves.append(1)
        return real_save(results)

    monkeypatch.setattr(clients, "ollama", ollama)
    monkeypatch.setattr(clients, "lms", lms)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    monkeypatch.setattr(gpu.MANAGER, "free_all", lambda: freed.append(1) or ["stopped"])
    monkeypatch.setattr(index, "search_chunks", fake_search)
    monkeypatch.setattr(index, "chunk_lookup", lambda: dict(by_id))
    monkeypatch.setattr(digest, "load_digest", lambda: DIGEST)
    monkeypatch.setattr(items, "save_twin_answers", counting_save)
    monkeypatch.setattr(config, "TWIN_ANSWERS_PATH", tmp_path / "items" / "twin_answers.json")
    monkeypatch.setattr(config, "ITEM_SCORES_PATH", tmp_path / "items" / "scores.json")
    monkeypatch.setattr(config, "SELF_ANSWERS_PATH", tmp_path / "items" / "self_answers.json")
    monkeypatch.setattr(config, "SELF_ANSWERS_RETEST_PATH", tmp_path / "items" / "self_answers_retest.json")
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_V2_PATH)
    return SimpleNamespace(ollama=ollama, lms=lms, ensured=ensured, freed=freed, searches=searches, saves=saves,
                           chunks=fixed_chunks, by_id=by_id, profile=profile, tmp=tmp_path,
                           answers_path=tmp_path / "items" / "twin_answers.json", audit_path=tmp_path / "audit.jsonl")


def collapse(seq):
    out = []
    for x in seq:
        if not out or out[-1] != x:
            out.append(x)
    return out


def qwen_calls(env):
    return [c for c in env.ollama.calls if c["key"] == items.ITEM_MODEL]


def judge_calls(env, judge=None):
    return [c for c in env.ollama.calls if c["body"].get("format") == prompts.JUDGE_SCHEMA
            and (judge is None or c["key"] == judge)]


def twin_facing_texts(env) -> list[str]:
    """Every message content the twin itself received (qwen3 closed prompts + Stheno voice prompts)."""
    out = []
    for c in qwen_calls(env) + env.lms.calls:
        out += [m["content"] for m in c["body"]["messages"]]
    return out


def _profile_with(text_edit):
    text = EXAMPLE_PROFILE_V2_PATH.read_text(encoding="utf-8-sig")
    return profile_mod.parse_profile(text_edit(text), str(EXAMPLE_PROFILE_V2_PATH))


# ---------------------------------------------------------------------------
# bank
# ---------------------------------------------------------------------------

def test_bank_items_overrides_gold_text_and_reports_exclusions(profile):
    bank = items.load_bank()
    its = items.bank_items(profile)
    assert len(bank["items"]) == 112 and len(its) == 111
    assert items.excluded_items(profile) == [("GOLD_Q-12", "excluded: politics")]
    assert "GOLD_Q-12" not in {i["id"] for i in its}
    # bank order kept, minus the skipped item
    assert [i["id"] for i in its] == [i["id"] for i in bank["items"] if i["id"] != "GOLD_Q-12"]
    by_qid = {q.qid: q.question for q in profile.eval}
    for it in its:
        if it["instrument"] == "gold":
            assert it["text"] == by_qid[items.gold_qid(it["id"])] and it["qid"] == items.gold_qid(it["id"])
    groups = items.items_by_instrument(its)
    assert {k: len(v) for k, v in groups.items()} == {"ipip50": 50, "game": 5, "gold": 19, "gss": 37}
    assert list(groups) == ["ipip50", "game", "gold", "gss"]
    # the bank on disk is not modified by the override
    assert next(i for i in bank["items"] if i["id"] == "GOLD_Q-01")["text"] == by_qid["Q-01"]


def test_bank_items_politics_regex_skips_gold_question_from_the_profile():
    prof = _profile_with(lambda t: t.replace("Question: How do you spend a free evening?",
                                             "Question: Which party do you vote for?"))
    excluded = dict(items.excluded_items(prof))
    assert excluded["GOLD_Q-12"] == "excluded: politics"
    assert "politics" in excluded["GOLD_Q-05"] and "regex" in excluded["GOLD_Q-05"]
    assert "GOLD_Q-05" not in {i["id"] for i in items.bank_items(prof)}
    assert len(items.bank_items(prof)) == 110
    # the IPIP item "Am the life of the party." is not a gold item and is never regex-filtered
    assert "IPIP_E1" in {i["id"] for i in items.bank_items(prof)}


def test_bank_items_without_matching_eval_question_are_skipped():
    prof = _profile_with(lambda t: t.replace("## Q-20\nQuestion: What does success look like to you?\n"
                                             "Answer: publishing a book that's actually mine, and never having to take a job i hate again\n", ""))
    assert len(prof.eval) == 19
    excluded = dict(items.excluded_items(prof))
    assert excluded["GOLD_Q-20"] == "no Eval question Q-20 in the profile"
    assert len(items.bank_items(prof)) == 110


def test_items_without_a_profile_keep_the_bank_text(monkeypatch):
    def boom():
        raise OSError("no profile")
    monkeypatch.setattr(profile_mod, "load_profile", boom)
    its = items.bank_items(None)
    assert len(its) == 111 and next(i for i in its if i["id"] == "GOLD_Q-01")["text"].startswith("How do you decide")


# ---------------------------------------------------------------------------
# schemas, parsing
# ---------------------------------------------------------------------------

def test_schema_for_shapes(profile):
    by = {i["id"]: i for i in items.bank_items(profile)}
    s = items.schema_for(by["IPIP_E1"])
    assert s == {"type": "object", "properties": {"item_id": {"type": "string", "enum": ["IPIP_E1"]},
                                                  "answer": {"type": "integer", "minimum": 1, "maximum": 5}},
                 "required": ["item_id", "answer"]}
    s = items.schema_for(by["GSS_HAPPY"])
    assert s["properties"]["item_id"]["enum"] == ["GSS_HAPPY"]
    assert s["properties"]["answer"] == {"type": "string", "enum": ["VERY HAPPY", "PRETTY HAPPY", "NOT TOO HAPPY"]}
    assert s["required"] == ["item_id", "answer"]
    s = items.schema_for(by["GAME_dictator"])
    assert s["properties"] == {"game": {"type": "string", "enum": ["dictator"]},
                               "give": {"type": "integer", "minimum": 0, "maximum": 10}}
    assert s["required"] == ["game", "give"]
    s = items.schema_for(by["GAME_trust_return"])
    assert s["properties"] == {"game": {"type": "string", "enum": ["trust_return"]},
                               "fraction": {"type": "number", "minimum": 0, "maximum": 1}}
    s = items.schema_for(by["GAME_prisoners_dilemma"])
    assert s["properties"] == {"game": {"type": "string", "enum": ["prisoners_dilemma"]},
                               "action": {"type": "string", "enum": ["cooperate", "defect"]}}
    assert s["required"] == ["game", "action"]
    with pytest.raises(ValueError, match="GOLD_Q-01"):
        items.schema_for(by["GOLD_Q-01"])


def test_parse_closed_validation(profile):
    by = {i["id"]: i for i in items.bank_items(profile)}
    lik, cat, num, frac, binv = by["IPIP_E1"], by["GSS_HAPPY"], by["GAME_dictator"], by["GAME_trust_return"], by["GAME_prisoners_dilemma"]
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": 4}') == 4
    assert items.parse_closed(lik, 'sure: {"item_id": "IPIP_E1", "answer": 5} done') == 5
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": 6}') is None
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": 0}') is None
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": 3.5}') is None
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": "3"}') == 3
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": true}') is None
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1", "answer": 1e400}') is None      # inf, not OverflowError
    assert items.coerce_value(lik, "inf") is None and items.coerce_value(lik, "nan") is None
    assert items.coerce_value(num, float("inf")) is None and items.coerce_value(frac, "inf") is None
    assert items.parse_closed(lik, '{"item_id": "IPIP_E1"}') is None
    assert items.parse_closed(lik, "") is None and items.parse_closed(lik, "not json") is None
    assert items.parse_closed(cat, '{"item_id": "GSS_HAPPY", "answer": "PRETTY HAPPY"}') == "PRETTY HAPPY"
    assert items.parse_closed(cat, '{"item_id": "GSS_HAPPY", "answer": "pretty  happy"}') == "PRETTY HAPPY"
    assert items.parse_closed(cat, '{"item_id": "GSS_HAPPY", "answer": "ecstatic"}') is None
    assert items.parse_closed(cat, '{"item_id": "GSS_HAPPY", "answer": 2}') is None
    assert items.parse_closed(num, '{"game": "dictator", "give": 7}') == 7
    assert items.parse_closed(num, '{"game": "dictator", "give": 11}') is None
    assert items.parse_closed(num, '{"game": "dictator", "answer": 7}') is None
    assert items.parse_closed(frac, '{"game": "trust_return", "fraction": 0.25}') == 0.25
    assert items.parse_closed(frac, '{"game": "trust_return", "fraction": 1}') == 1.0
    assert items.parse_closed(frac, '{"game": "trust_return", "fraction": 1.5}') is None
    assert items.parse_closed(binv, '{"game": "prisoners_dilemma", "action": "Defect"}') == "defect"
    assert items.parse_closed(binv, '{"game": "prisoners_dilemma", "action": "maybe"}') is None
    assert items.coerce_value(by["GOLD_Q-01"], "  some text ") == "some text"
    assert items.coerce_value(by["GOLD_Q-01"], "   ") is None


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def _leak_strings(profile) -> list[str]:
    """Eval answers, the Changelog text and the example self answers (gold texts + a few closed values)."""
    out = [q.answer for q in profile.eval]
    out.append(profile.sections["Changelog"].strip())
    ex = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))["answers"]
    out += [v for k, v in ex.items() if k.startswith("GOLD_")]
    return out


def test_closed_messages_per_condition_and_no_leaks(profile):
    by = {i["id"]: i for i in items.bank_items(profile)}
    chunks = [{"id": f"C/{i}", "title": f"title {i}", "text": f"chunk text {i}"} for i in range(1, 6)]
    item = by["GSS_TRUST"]
    demo = items.closed_messages(profile, "demographic", item, chunks, DIGEST)
    pers = items.closed_messages(profile, "persona", item, chunks, DIGEST)
    intv = items.closed_messages(profile, "interview", item, chunks, DIGEST)
    for msgs in (demo, pers, intv):
        assert [m["role"] for m in msgs] == ["system", "user"]
        assert msgs[0]["content"].startswith(items.ITEM_SYSTEM(profile.name, "demographic").split("(condition")[0])
        assert "IDENTITY:\n" + profile.identity in msgs[0]["content"]
        assert msgs[1]["content"] == items.item_user_text(item)
        assert msgs[1]["content"].endswith("Answer with JSON only.")
        assert item["text"] in msgs[1]["content"]
        for i, o in enumerate(item["options"], 1):
            assert f"{i}. {o}" in msgs[1]["content"]
    assert "DIGEST:" not in demo[0]["content"] and "CONTEXT:" not in demo[0]["content"]
    assert "SELF-RATINGS" not in demo[0]["content"] and DIGEST not in demo[0]["content"]
    assert "(condition: demographic)" in demo[0]["content"]
    assert "DIGEST:\n" + DIGEST in pers[0]["content"] and "CONTEXT:" not in pers[0]["content"]
    assert "SELF-RATINGS" not in pers[0]["content"]
    assert "DIGEST:\n" + DIGEST in intv[0]["content"]
    ctx = intv[0]["content"].split("CONTEXT:\n", 1)[1].split("\n\nSELF-RATINGS:\n", 1)
    assert ctx[0].splitlines() == [f"[{i}] (title {i}) chunk text {i}" for i in range(1, 6)]
    assert ctx[1].strip() == profile.self_ratings
    assert items.condition_context(profile, "interview", [], DIGEST).count("(nothing retrieved)") == 1
    # the twin-facing prompt never carries Eval answers, the Changelog or self-answer values
    leaks = _leak_strings(profile)
    for msgs in (demo, pers, intv):
        blob = "\n".join(m["content"] for m in msgs)
        for s in leaks:
            assert s not in blob, s
    with pytest.raises(ValueError):
        items.closed_messages(profile, "bogus", item, chunks, DIGEST)
    # likert and game user turns
    lik = items.item_user_text(by["IPIP_E1"])
    assert lik.startswith("STATEMENT: Am the life of the party.") and "1 = Very Inaccurate" in lik and "5 = Very Accurate" in lik
    assert "whole number from 0 to 10" in items.item_user_text(by["GAME_dictator"])
    assert "number from 0 to 1" in items.item_user_text(by["GAME_trust_return"])
    assert "OPTIONS: cooperate or defect" in items.item_user_text(by["GAME_prisoners_dilemma"])


def test_open_messages_use_the_voice_system_per_condition(profile):
    by = {i["id"]: i for i in items.bank_items(profile)}
    item = by["GOLD_Q-03"]
    chunks = [{"id": "Values", "title": "Values", "text": "v"}]
    for cond in CONDITIONS:
        msgs = items.open_messages(profile, cond, item, chunks, DIGEST)
        assert msgs[0]["content"] == prompts.build_voice_system(profile, DIGEST, chunks, condition=cond)
        assert msgs[1] == {"role": "user", "content": profile.eval[2].question}
        for s in _leak_strings(profile):
            assert s not in msgs[0]["content"] + msgs[1]["content"]


# ---------------------------------------------------------------------------
# run_items
# ---------------------------------------------------------------------------

def test_run_items_model_outer_order_bodies_and_files(env):
    out = items.run_items(conditions=CONDITIONS, profile=env.profile)
    its = items.bank_items(env.profile)
    closed = [i for i in its if i["type"] != "open"]
    opened = [i for i in its if i["type"] == "open"]
    assert len(closed) == 92 and len(opened) == 19
    # (1) retrieval once per item, interview only, with the LM Studio nomic index and the section boost
    assert len(env.searches) == 111
    assert {s["index_key"] for s in env.searches} == {"lms_nomic"}
    assert all(s["k"] == 5 and s["boost"] == items.ITEM_BOOST and s["tab"] == "items" for s in env.searches)
    assert [s["query"] for s in env.searches] == [i["text"].strip() for i in its]
    # (2)-(5) model-outer order: at most four distinct big models, each loaded once
    assert collapse(env.ensured) == ["qwen3_8k", "stheno_q4", "llama31", "qwen25"]
    kinds = []
    for c in env.ollama.calls:
        kinds.append("qwen" if c["key"] == "qwen3_8k" else ("judge" if c["body"].get("format") == prompts.JUDGE_SCHEMA else "?"))
    assert "?" not in kinds and "qwen" not in kinds[kinds.index("judge"):]
    assert len(qwen_calls(env)) == 92 * 3 and len(env.lms.calls) == 19 * 3
    assert len(judge_calls(env, "llama31")) == 57 and len(judge_calls(env, "qwen25")) == 57
    jk = [c["key"] for c in judge_calls(env)]
    assert jk == ["llama31"] * 57 + ["qwen25"] * 57
    assert all(c["tab"] == "items" for c in env.ollama.calls + env.lms.calls)
    # qwen3 bodies
    expect = {(cond, i["id"]): items.schema_for(i) for cond in CONDITIONS for i in closed}
    seen = []
    for c in qwen_calls(env):
        b = c["body"]
        assert b["model"] == "qwen3-8b-8k" and b["think"] is False and b["keep_alive"] == "10m" and b["stream"] is False
        assert b["options"] == {"temperature": 0.2, "num_ctx": 8192, "num_predict": 80}
        assert [m["role"] for m in b["messages"]] == ["system", "user"]
        seen.append(b["format"])
    assert seen == [expect[(cond, i["id"])] for cond in CONDITIONS for i in closed]
    # first qwen3 call = demographic IPIP_E1 with the demographic prompt; the interview ones carry the 5 chunks
    first = qwen_calls(env)[0]["body"]["messages"]
    assert first == items.closed_messages(env.profile, "demographic", closed[0], [], DIGEST)
    intv = qwen_calls(env)[2 * 92]["body"]["messages"]
    assert intv == items.closed_messages(env.profile, "interview", closed[0], env.chunks, DIGEST)
    assert "[5] (" in intv[0]["content"] and "SELF-RATINGS:\n" + env.profile.self_ratings in intv[0]["content"]
    # Stheno bodies
    for c, (cond, it) in zip(env.lms.calls, [(cond, i) for cond in CONDITIONS for i in opened]):
        b = c["body"]
        assert c["key"] == "stheno_q4" and b["model"] == "l3-8b-stheno-v3.2"
        assert b["temperature"] == 1.15 and b["max_tokens"] == 300 and b["stream"] is False
        assert b["extra_body"] == {"min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1}
        chunks = env.chunks if cond == "interview" else []
        assert b["messages"] == items.open_messages(env.profile, cond, it, chunks, DIGEST)
    # judge bodies: the gold answer reaches the judge only; format, temperature 0, 300 tokens
    for c in judge_calls(env):
        b = c["body"]
        assert b["format"] == prompts.JUDGE_SCHEMA and b["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 300}
        assert b["messages"][0]["content"] == prompts.JUDGE_SYSTEM
        assert "GOLD:\n" in b["messages"][1]["content"] and env.profile.style_rules in b["messages"][1]["content"]
    golds = [q.answer for q in env.profile.eval if q.qid != "Q-12"]
    assert all(any(g in c["body"]["messages"][1]["content"] for g in golds) for c in judge_calls(env))
    # the file is written after every call
    total_calls = len(env.ollama.calls) + len(env.lms.calls)
    assert out["calls"] == total_calls == 92 * 3 + 19 * 3 + 57 * 2
    assert len(env.saves) >= total_calls
    data = json.loads(env.answers_path.read_text(encoding="utf-8"))
    entry = data[env.profile.sha]
    assert set(entry) == {"meta", *CONDITIONS}
    for cond in CONDITIONS:
        assert set(entry[cond]) == {i["id"] for i in its}
        cell = entry[cond]["IPIP_E1"]
        assert set(cell) >= {"answer", "raw", "ms", "attempts", "chunk_ids"} and cell["answer"] in (2, 3, 4)
        assert cell["chunk_ids"] == (CHUNK_IDS if cond == "interview" else [])
        g = entry[cond]["GOLD_Q-01"]
        assert g["voice"] == "stheno_q4" and g["answer"].startswith("ok wait") and set(g["judges"]) == {"llama31", "qwen25"}
        assert g["judges"]["llama31"] == GOOD_SCORES
        assert entry[cond]["GSS_HAPPY"]["answer"] == "VERY HAPPY"
        assert entry[cond]["GAME_trust_return"]["answer"] == 0.5 and entry[cond]["GAME_prisoners_dilemma"]["answer"] == "cooperate"
    assert entry["meta"]["excluded"] == [["GOLD_Q-12", "excluded: politics"]]
    assert entry["meta"]["bank_version"] == "1.0" and entry["meta"]["retrieval_index"] == "lms_nomic"
    assert entry["meta"]["last_run"]["models"] == ["nomic_lms", "qwen3_8k", "stheno_q4", "llama31", "qwen25"]
    # distribution report: histogram, most common categorical option (enum collapse visible), game values, gold
    report = out["report"]
    assert report == entry["meta"]["last_report"]
    for cond in CONDITIONS:
        i = report.index(f"distribution [{cond}]:")
        assert re.match(r"  ipip50 likert histogram: 1:\d+ 2:\d+ 3:\d+ 4:\d+ 5:\d+ \(invalid 0 of 50\)", report[i + 1])
        assert report[i + 2].startswith("  gss: answered 37/37, most common option ") and "first-option share 100%" in report[i + 2]
        assert report[i + 3] == "  game: dictator=4, trust_send=4, trust_return=0.5, public_goods=4, prisoners_dilemma='cooperate'"
        assert report[i + 4] == "  gold: 19/19 replies; mean judge overall: llama31 4.00, qwen25 4.00"
    # GPU freed once, one audit line per condition (request text never written)
    assert env.freed == [1]
    lines = [json.loads(ln) for ln in env.audit_path.read_text(encoding="utf-8").splitlines()]
    assert [(e["tab"], e["condition"], e["ok"]) for e in lines] == [("items", c, True) for c in CONDITIONS]
    assert all(e["model_keys"] == ["nomic_lms", "qwen3_8k", "stheno_q4", "llama31", "qwen25"] and e["chunk_ids"] == []
               for e in lines)
    assert out["sha"] == env.profile.sha and out["conditions"] == list(CONDITIONS) and out["excluded"] == [("GOLD_Q-12", "excluded: politics")]


def test_run_items_prompts_never_leak_eval_answers_changelog_or_self_answers(env):
    items.run_items(conditions=CONDITIONS, profile=env.profile)
    leaks = _leak_strings(env.profile)
    texts = twin_facing_texts(env)
    assert len(texts) == (92 * 3 + 19 * 3) * 2
    for t in texts:
        for s in leaks:
            assert s not in t, s[:40]
    # and no self-answer file is ever read by the run (the example values stay out of the prompts)
    ex = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))["answers"]
    assert not any(ex["GOLD_Q-01"] in t for t in texts)


def test_run_items_retry_on_invalid_json_then_error_cell_and_resume_retries_it(env, monkeypatch):
    def reply(key, body, n):
        fmt = body.get("format") or {}
        iid = (fmt.get("properties") or {}).get("item_id", {}).get("enum", [None])[0]
        if iid == "IPIP_E2":
            return "garbage" if n == 2 else None            # first attempt bad, retry good
        if iid == "GSS_HAPPY":
            return '{"item_id": "GSS_HAPPY", "answer": "ECSTATIC"}'   # out of enum, twice
        if iid == "GSS_TRUST":
            return clients.OllamaError("boom")             # server error, twice
        return None
    env.ollama.reply = reply
    out = items.run_items(conditions=("interview",), profile=env.profile)
    calls = qwen_calls(env)
    per_item = {}
    for c in calls:
        per_item.setdefault(c["body"]["format"]["properties"].get("item_id", {}).get("enum", ["game"])[0], []).append(c)
    assert len(per_item["IPIP_E2"]) == 2 and len(per_item["GSS_HAPPY"]) == 2 and len(per_item["GSS_TRUST"]) == 2
    assert per_item["IPIP_E2"][0]["body"] == per_item["IPIP_E2"][1]["body"]
    assert len(per_item["IPIP_E1"]) == 1
    entry = out["entry"]["interview"]
    assert entry["IPIP_E2"]["answer"] in (2, 3, 4) and entry["IPIP_E2"]["attempts"] == 2 and "error" not in entry["IPIP_E2"]
    assert entry["GSS_HAPPY"] == {**entry["GSS_HAPPY"], "answer": None, "attempts": 2}
    assert entry["GSS_HAPPY"]["error"] == "invalid or out-of-range JSON answer after 2 attempts"
    assert entry["GSS_TRUST"]["answer"] is None and entry["GSS_TRUST"]["error"].startswith("ollama: boom")
    assert out["calls"] == 92 + 3 + 19 + 38
    # resume: only the two error cells are redone (now succeeding), nothing else is called
    env.ollama.reply = None
    env.ollama.calls.clear(); env.lms.calls.clear(); env.ensured.clear(); env.searches.clear()
    out2 = items.run_items(conditions=("interview",), profile=env.profile)
    assert [c["body"]["format"]["properties"]["item_id"]["enum"][0] for c in env.ollama.calls] == ["GSS_HAPPY", "GSS_TRUST"]
    assert env.lms.calls == [] and collapse(env.ensured) == ["qwen3_8k"]
    assert [s["query"] for s in env.searches] == [next(i["text"] for i in items.bank_items(env.profile) if i["id"] == x)
                                                  for x in ("GSS_HAPPY", "GSS_TRUST")]
    assert out2["entry"]["interview"]["GSS_HAPPY"]["answer"] == "VERY HAPPY" and "error" not in out2["entry"]["interview"]["GSS_TRUST"]


def test_run_items_is_resumable_and_no_resume_redoes_everything(env):
    items.run_items(conditions=("persona",), profile=env.profile)
    n_calls = len(env.ollama.calls) + len(env.lms.calls)
    assert n_calls == 92 + 19 + 38
    env.ollama.calls.clear(); env.lms.calls.clear(); env.ensured.clear(); env.saves.clear(); env.freed.clear()
    out = items.run_items(conditions=("persona",), profile=env.profile)
    assert env.ollama.calls == [] and env.lms.calls == [] and env.ensured == [] and out["calls"] == 0
    assert out["report"][0] == "distribution [persona]:" and env.freed == [1]
    # judges missing on an existing reply are filled without regenerating the reply
    data = json.loads(env.answers_path.read_text(encoding="utf-8"))
    del data[env.profile.sha]["persona"]["GOLD_Q-02"]["judges"]["qwen25"]
    data[env.profile.sha]["persona"]["GOLD_Q-03"]["judges"]["llama31"] = {"error": "invalid judge JSON"}
    env.answers_path.write_text(json.dumps(data), encoding="utf-8")
    items.run_items(conditions=("persona",), profile=env.profile)
    assert env.lms.calls == [] and [c["key"] for c in env.ollama.calls] == ["llama31", "qwen25"]
    # --no-resume redoes the whole condition
    env.ollama.calls.clear(); env.lms.calls.clear()
    out = items.run_items(conditions=("persona",), profile=env.profile, resume=False)
    assert out["calls"] == n_calls
    lines = [json.loads(ln) for ln in env.audit_path.read_text(encoding="utf-8").splitlines()]
    assert [e["extra"]["resume"] for e in lines] == [True, True, True, False]


def test_run_items_non_interview_conditions_never_retrieve(env):
    out = items.run_items(conditions=("demographic", "persona"), profile=env.profile)
    assert env.searches == [] and out["models"] == ["qwen3_8k", "stheno_q4", "llama31", "qwen25"]
    for c in qwen_calls(env):
        assert "CONTEXT:" not in c["body"]["messages"][0]["content"]
        assert "SELF-RATINGS" not in c["body"]["messages"][0]["content"]
    demo = [c for c in qwen_calls(env)][:92]
    assert all("DIGEST:" not in c["body"]["messages"][0]["content"] for c in demo)
    pers = [c for c in qwen_calls(env)][92:]
    assert all("DIGEST:\n" + DIGEST in c["body"]["messages"][0]["content"] for c in pers)
    for c in env.lms.calls:
        assert "CONTEXT:" not in c["body"]["messages"][0]["content"]
    with pytest.raises(ValueError):
        items.run_items(conditions=("bogus",), profile=env.profile)
    with pytest.raises(ValueError):
        items.run_items(conditions=(), profile=env.profile)


def test_run_items_frees_gpu_and_audits_failure(env, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("index not built")
    monkeypatch.setattr(index, "search_chunks", boom)
    with pytest.raises(RuntimeError, match="index not built"):
        items.run_items(conditions=("interview",), profile=env.profile)
    assert env.freed == [1] and env.ollama.calls == [] and env.lms.calls == []
    lines = [json.loads(ln) for ln in env.audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["condition"] == "interview" and lines[0]["ok"] is False


def test_open_reply_fallback_key_is_recorded(env, monkeypatch):
    monkeypatch.setattr(env.lms, "alive", lambda: False)
    out = items.run_items(conditions=("demographic",), profile=env.profile)
    cell = out["entry"]["demographic"]["GOLD_Q-01"]
    assert cell["voice"] == "llama32_3b" and env.lms.calls == []
    fb = [c for c in env.ollama.calls if c["key"] == "llama32_3b"]
    assert len(fb) == 19 and fb[0]["body"]["options"] == {"temperature": 0.8, "num_ctx": 4096, "num_predict": 300}
    assert "llama32_3b" in out["models"] and "stheno_q4" not in out["models"]


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _example_waves():
    w1 = json.loads(config.EXAMPLE_SELF_ANSWERS_PATH.read_text(encoding="utf-8"))
    w2 = json.loads(config.EXAMPLE_SELF_ANSWERS_RETEST_PATH.read_text(encoding="utf-8"))
    return w1, w2


def _twin_from(answers: dict, judges=None) -> dict:
    return {iid: {"answer": v, "judges": dict(judges or {})} for iid, v in answers.items()}


def test_scored_value_applies_reverse_key(profile):
    by = {i["id"]: i for i in items.bank_items(profile)}
    fwd = next(i for i in by.values() if i["instrument"] == "ipip50" and not i["reverse"])
    rev = next(i for i in by.values() if i["instrument"] == "ipip50" and i["reverse"])
    assert items.scored_value(fwd, 2) == 2 and items.scored_value(rev, 2) == 4 and items.scored_value(rev, 5) == 1
    assert items.scored_value(rev, None) is None
    # a twin answer equal to the truth on a reverse item scores MAE 0; opposite ends score MAE 4
    truth = {rev["id"]: 5}
    x, y = items._pairs([rev], {rev["id"]: 5}, truth, items.scored_value)
    assert x.tolist() == [1.0] and y.tolist() == [1.0]
    x, y = items._pairs([rev], {rev["id"]: 1}, truth, items.scored_value)
    assert abs(x[0] - y[0]) == 4.0


def test_score_on_the_example_waves_is_deterministic_with_ci_and_normalized(env):
    w1, w2 = _example_waves()
    judges = {"llama31": {**GOOD_SCORES, "overall": 4}, "qwen25": {**GOOD_SCORES, "overall": 3}}
    better = {"llama31": {**GOOD_SCORES, "overall": 5}, "qwen25": {**GOOD_SCORES, "overall": 4}}
    twin = {"interview": _twin_from(w2["answers"], better),                       # perfect twin
            "persona": _twin_from(w1["answers"], judges),                         # as good as the retest
            "demographic": _twin_from({k: (3 if k.startswith("IPIP") else v) for k, v in w1["answers"].items()}, judges)}
    sc = items.score(twin=twin, profile=env.profile)
    assert sc["conditions"] == ["demographic", "persona", "interview"]
    assert sc["waves"]["ground_truth"] == "wave2" and sc["waves"]["retest"] is True and sc["waves"]["example"] is True
    assert sc["waves"]["wave1"].endswith("self_answers.example.json") and sc["waves"]["wave2"].endswith("self_answers_retest.example.json")
    rows = sc["rows"]
    assert all(set(r) == {"condition", "instrument", "domain", "n", "n_items", "metric", "value", "ci95", "retest", "normalized"} for r in rows)
    assert [r["domain"] for r in rows if r["condition"] == "interview" and r["instrument"] == "ipip50"] == \
        [d for d in ("E", "A", "C", "N", "O", "all") for _ in range(3)]
    # interview == truth: MAE 0, r 1, acc 1; normalized = 1/retest
    e = {r["metric"]: r for r in rows if (r["condition"], r["instrument"], r["domain"]) == ("interview", "ipip50", "E")}
    assert e["mae"]["value"] == 0.0 and e["r"]["value"] == 1.0 and e["acc"]["value"] == 1.0 and e["mae"]["n"] == 10
    assert e["acc"]["retest"] == 0.925 and e["acc"]["normalized"] == round(1.0 / 0.925, 3)
    assert e["mae"]["ci95"] == [0.0, 0.0] and e["r"]["ci95"] == [1.0, 1.0]
    # persona == wave 1: every retest-normalised metric is exactly 1.0 (twin metric == retest metric)
    for r in rows:
        if r["condition"] == "persona" and r["instrument"] in ("ipip50", "gss", "game") and r["value"] is not None \
                and r["retest"] not in (None, 0):
            assert r["normalized"] == 1.0, r
    # demographic: flat 3s give zero variance -> r undefined (None), acc below the retest
    d = {r["metric"]: r for r in rows if (r["condition"], r["instrument"], r["domain"]) == ("demographic", "ipip50", "all")}
    assert d["r"]["value"] is None and d["r"]["ci95"] is None and d["r"]["normalized"] is None
    assert d["acc"]["value"] < d["acc"]["retest"] and 0 < d["acc"]["normalized"] < 1
    assert d["acc"]["ci95"][0] <= d["acc"]["value"] <= d["acc"]["ci95"][1]
    # gss: categorical accuracy with n = 37; the retest accuracy is 31/37 (six items drift in the example)
    g = next(r for r in rows if (r["condition"], r["instrument"]) == ("persona", "gss"))
    assert g["domain"] == "all" and g["metric"] == "accuracy" and g["n"] == 37 and g["n_items"] == 37
    assert g["retest"] == round(31 / 37, 4) and g["value"] == g["retest"] and g["normalized"] == 1.0
    assert 0 < g["ci95"][0] <= g["value"] <= g["ci95"][1] <= 1
    # games: per-item mae/acc, the family acc row, PD accuracy
    games = [(r["domain"], r["metric"]) for r in rows if (r["condition"], r["instrument"]) == ("interview", "game")]
    assert games == [("dictator", "mae"), ("dictator", "acc"), ("trust_send", "mae"), ("trust_send", "acc"),
                     ("trust_return", "mae"), ("trust_return", "acc"), ("public_goods", "mae"), ("public_goods", "acc"),
                     ("all", "acc"), ("prisoners_dilemma", "accuracy")]
    pd = next(r for r in rows if (r["condition"], r["instrument"], r["domain"]) == ("interview", "game", "prisoners_dilemma"))
    assert pd["value"] == 1.0 and pd["retest"] == 1.0
    # gold: mean judge overall / 5 across judges; no retest metric
    go = next(r for r in rows if (r["condition"], r["instrument"]) == ("interview", "gold"))
    assert go["metric"] == "judge_overall" and go["value"] == 0.9 and go["n"] == 19 and go["retest"] is None and go["normalized"] == "n/a"
    assert next(r for r in rows if (r["condition"], r["instrument"]) == ("persona", "gold"))["value"] == 0.7
    # deterministic with seed 0 (bootstrap), and a different seed may move the CI but not the value
    sc2 = items.score(twin=twin, profile=env.profile)
    assert sc2["rows"] == rows and sc2["decision"] == sc["decision"]
    sc3 = items.score(twin=twin, profile=env.profile, seed=7, n_boot=200)
    assert [r["value"] for r in sc3["rows"]] == [r["value"] for r in rows]
    assert sc["decision"].startswith("Decision: interview beats demographic and persona on ")
    assert sc["decision"].endswith(": yes") and "ceiling pending" not in sc["decision"]
    # table rows and persistence
    table = items.summary_rows(sc)
    assert len(table) == len(rows) and table[0][:5] == ["demographic", "ipip50", "E", "10", "mae"]
    assert all(len(r) == len(items.SCORE_HEADERS) for r in table)
    p = items.save_scores(sc)
    assert p == config.ITEM_SCORES_PATH and items.load_scores()["decision"] == sc["decision"]
    assert items.decision_line(items.load_scores()) == sc["decision"]


def test_score_without_wave2_reports_ceiling_pending(env):
    w1, w2 = _example_waves()
    twin = {"interview": _twin_from(w1["answers"])}
    waves = {"wave1": (config.EXAMPLE_SELF_ANSWERS_PATH, w1), "wave2": (config.EXAMPLE_SELF_ANSWERS_RETEST_PATH, None), "example": True}
    sc = items.score(twin=twin, waves=waves, profile=env.profile)
    assert sc["waves"]["ground_truth"] == "wave1" and sc["waves"]["retest"] is False and sc["waves"]["wave2"] is None
    for r in sc["rows"]:
        if r["instrument"] != "gold":
            assert r["normalized"] == "ceiling pending" and r["retest"] is None, r
    assert "ceiling pending" in sc["decision"] and "n/a (conditions not run yet: demographic, persona)" in sc["decision"]
    table = items.summary_rows(sc)
    assert {row[-1] for row in table if row[1] != "gold"} == {"ceiling pending"}
    # a low raw interview GSS accuracy is flagged while the ceiling is pending
    bad = {k: ("NOT TOO HAPPY" if k.startswith("GSS_") and v != "NOT TOO HAPPY" else v) for k, v in w1["answers"].items()}
    sc = items.score(twin={"interview": _twin_from(bad)}, waves=waves, profile=env.profile)
    assert "fix retrieval (recall@5) before content (raw gss accuracy" in sc["decision"]
    # plain {id: value} mappings work too; no answers at all raises
    sc = items.score(twin=twin, waves={"wave1": w1["answers"], "wave2": None}, profile=env.profile)
    assert sc["waves"]["wave1"] is None and sc["rows"]
    with pytest.raises(ValueError, match="no self answers"):
        items.score(twin=twin, waves={"wave1": None, "wave2": None}, profile=env.profile)
    # nothing cached for this profile: no rows, decision still a string
    sc = items.score(profile=env.profile)
    assert sc["rows"] == [] and sc["conditions"] == [] and sc["decision"].startswith("Decision:")


def _scores(vals: dict, normalized=None, retest=True) -> dict:
    rows = []
    for cond, per in vals.items():
        for (inst, dom, met), v in per.items():
            rows.append({"condition": cond, "instrument": inst, "domain": dom, "n": 10, "n_items": 10, "metric": met,
                         "value": v, "ci95": [v, v], "retest": 0.9, "normalized": normalized if normalized is not None else v})
    return {"conditions": list(vals), "rows": rows, "waves": {"retest": retest}}


def test_decision_line_verdicts_and_retrieval_flag():
    m = {("ipip50", "all", "acc"): 0.8, ("ipip50", "all", "r"): 0.7, ("gss", "all", "accuracy"): 0.8,
         ("game", "all", "acc"): 0.9, ("gold", "all", "judge_overall"): 0.8}
    lower = {k: v - 0.2 for k, v in m.items()}
    line = items.decision_line(_scores({"demographic": lower, "persona": lower, "interview": m}))
    assert line == ("Decision: interview beats demographic and persona on ipip50 acc, ipip50 r, gss accuracy, "
                    "game acc, gold judge_overall: yes")
    line = items.decision_line(_scores({"demographic": m, "persona": lower, "interview": lower}))
    assert line.endswith(": no")
    mixed = {**lower, ("gss", "all", "accuracy"): 0.95}
    line = items.decision_line(_scores({"demographic": m, "persona": lower, "interview": mixed}))
    assert ": partial (yes on gss accuracy; no on ipip50 acc, ipip50 r, game acc, gold judge_overall)" in line
    # the normalised GSS accuracy below 0.5 flags retrieval
    line = items.decision_line(_scores({"demographic": lower, "persona": lower, "interview": m}, normalized=0.41))
    assert "fix retrieval (recall@5) before content (normalized gss accuracy 0.41 < 0.5)" in line
    line = items.decision_line(_scores({"demographic": lower, "persona": lower, "interview": m}, normalized=0.9))
    assert "fix retrieval" not in line
    # ceiling pending: raw value used and flagged as such
    sc = _scores({"demographic": lower, "persona": lower, "interview": {**m, ("gss", "all", "accuracy"): 0.3}},
                 normalized="ceiling pending", retest=False)
    line = items.decision_line(sc)
    assert "raw gss accuracy 0.30" in line and "ceiling pending" in line
    # missing conditions
    line = items.decision_line(_scores({"interview": m}))
    assert "n/a (conditions not run yet: demographic, persona)" in line
    # a missing metric in one condition is skipped, not a crash
    part = {k: v for k, v in lower.items() if k[0] != "gold"}
    line = items.decision_line(_scores({"demographic": part, "persona": lower, "interview": m}))
    assert "gold judge_overall" not in line and line.endswith(": yes")


def test_bootstrap_ci_and_metric_helpers():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([1.0, 2.0, 3.0, 5.0])
    assert items.bootstrap_ci("mae", x, y, n_boot=100, seed=0) == items.bootstrap_ci("mae", x, y, n_boot=100, seed=0)
    lo, hi = items.bootstrap_ci("mae", x, y, n_boot=500, seed=0)
    assert 0.0 <= lo <= 0.25 <= hi <= 1.0
    assert items.bootstrap_ci("mae", np.zeros(0), np.zeros(0)) is None
    assert items.bootstrap_ci("r", np.array([1.0, 2.0]), np.array([1.0, 2.0])) is None   # fewer than 3 items
    assert items.bootstrap_ci("r", np.array([2.0, 2.0, 2.0]), np.array([1.0, 2.0, 3.0])) is None   # zero variance
    assert items.bootstrap_ci("mean", np.array([0.5]), None) == [0.5, 0.5]
    assert items._point("acc", x, y, 4.0) == 0.9375 and items._point("r", x, y) == round(float(np.corrcoef(x, y)[0, 1]), 4)


# ---------------------------------------------------------------------------
# answer files
# ---------------------------------------------------------------------------

def test_save_answers_and_resolve_waves(env):
    waves = items.resolve_waves()
    assert waves["example"] is True and waves["wave1"][0] == config.EXAMPLE_SELF_ANSWERS_PATH
    assert waves["wave1"][1]["wave"] == 1 and waves["wave2"][1]["wave"] == 2 and len(waves["wave2"][1]["answers"]) == 112
    p = items.save_answers(1, {"IPIP_E1": 2, "GOLD_Q-01": "slow"}, "2026-09-14", "Mara Ellison")
    assert p == config.SELF_ANSWERS_PATH and p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == {"wave": 1, "date": "2026-09-14", "name": "Mara Ellison",
                                                        "answers": {"IPIP_E1": 2, "GOLD_Q-01": "slow"}}
    waves = items.resolve_waves()
    assert waves["example"] is False and waves["wave1"][0] == config.SELF_ANSWERS_PATH
    assert waves["wave1"][1]["date"] == "2026-09-14" and waves["wave2"] == (config.SELF_ANSWERS_RETEST_PATH, None)
    p2 = items.save_answers("2", {"IPIP_E1": 3}, "2026-09-28", "Mara Ellison")
    assert p2 == config.SELF_ANSWERS_RETEST_PATH and items.resolve_waves()["wave2"][1]["answers"] == {"IPIP_E1": 3}
    with pytest.raises(ValueError):
        items.save_answers(3, {}, "2026-09-14", "x")
    assert items.load_answers(env.tmp / "missing.json") is None
    (env.tmp / "bad.json").write_text("[1]", encoding="utf-8")
    assert items.load_answers(env.tmp / "bad.json") is None


def test_resolve_waves_with_only_a_real_wave2(env):
    """A real retest saved before (or without) wave 1 is real mode with wave 1 None, never the example pair."""
    assert not config.SELF_ANSWERS_PATH.exists()
    items.save_answers(2, {"IPIP_E1": 3}, "2026-09-28", "Mara Ellison")
    waves = items.resolve_waves()
    assert waves["example"] is False
    assert waves["wave1"] == (config.SELF_ANSWERS_PATH, None)
    assert waves["wave2"][0] == config.SELF_ANSWERS_RETEST_PATH and waves["wave2"][1]["answers"] == {"IPIP_E1": 3}
    sc = items.score()                                   # wave 2 is the truth, no retest ceiling
    assert sc["waves"]["ground_truth"] == "wave2" and not sc["waves"]["retest"] and not sc["waves"]["example"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_score_alone_never_touches_a_model(env, capsys):
    w1, _ = _example_waves()
    results = {env.profile.sha: {"interview": _twin_from(w1["answers"]), "meta": {}}}
    env.answers_path.parent.mkdir(parents=True, exist_ok=True)
    env.answers_path.write_text(json.dumps(results), encoding="utf-8")
    assert items.main(["--score"]) == 0
    out = capsys.readouterr().out
    assert env.ollama.calls == [] and env.lms.calls == [] and env.ensured == [] and env.searches == [] and env.freed == []
    assert "condition" in out and "Decision:" in out and config.ITEM_SCORES_PATH.exists()
    assert "retest: yes" in out
    assert items.main(["--show"]) == 0
    out = capsys.readouterr().out
    assert "interview: 112/111 answered" not in out and "interview: 111/111 answered" in out
    assert env.ollama.calls == []


def test_cli_run_parses_conditions_and_resume(env, monkeypatch):
    seen = []

    def fake_run(conditions=("interview",), progress=None, profile=None, resume=True):
        seen.append((tuple(conditions), resume, profile.name if profile else None))
        return {"calls": 0, "models": [], "report": [], "entry": {}, "sha": "x", "conditions": list(conditions), "excluded": []}
    monkeypatch.setattr(items, "run_items", fake_run)
    monkeypatch.setattr(items, "score", lambda **kw: {"rows": [], "decision": "Decision: n/a", "waves": {}})
    assert items.main(["--run", "--condition", "all"]) == 0
    assert items.main(["--run"]) == 0
    assert items.main(["--run", "--condition", "persona", "--no-resume", "--score"]) == 0
    assert seen == [(CONDITIONS, True, "Mara Ellison"), (("interview",), True, "Mara Ellison"), (("persona",), False, "Mara Ellison")]
    with pytest.raises(SystemExit):
        items.main(["--run", "--condition", "bogus"])
    assert items.main([]) == 0
    assert env.ollama.calls == [] and env.lms.calls == []
