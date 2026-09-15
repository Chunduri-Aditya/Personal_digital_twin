"""Hermetic tests for twin.pipelines.probes: probes derived from the Mara Boundaries section, the exact qwen2.5
judge request body (with its one retry), run_probes against a fake ask_sync and a fake judge writing only
results[sha]["probes"], the markdown table and the CLI --show path. No network, no GPU; every data path is a
tmp file."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import audit, clients, config, gpu, prompts
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH
from twin.pipelines import ask, evals, probes
from twin.profile import load_profile

_REAL_OLLAMA = clients.ollama  # only its pure _chat_body is used
POLITICAL_WORDS = ("politic", "vote", "election", "party", "government", "liberal", "conservative")


def ollama_response(model: str, content: str) -> dict:
    return {"model": model, "message": {"role": "assistant", "content": content}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9,
            "load_duration": 0}


class FakeOllama:
    """Records exact /api/chat bodies (real client's pure _chat_body); replies come from `contents` in order."""

    def __init__(self, contents=(), events: list | None = None):
        self.calls: list[dict] = []
        self.contents = list(contents)
        self.events = events if events is not None else []     # shared with the ask fake: proves model-outer order

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = _REAL_OLLAMA._chat_body(key, messages, options, format, tools, num_predict, stream,
                                          images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        if key == "qwen25":
            self.events.append("judge")
        content = self.contents.pop(0) if self.contents else json.dumps({"deflected": True, "revealed": [],
                                                                         "note": "fine"})
        return ollama_response(s.name, content)


@pytest.fixture
def mara():
    return load_profile(EXAMPLE_PROFILE_V2_PATH)


@pytest.fixture
def ari():
    return load_profile(EXAMPLE_PROFILE_PATH)


@pytest.fixture
def env(monkeypatch, tmp_path: Path):
    """Fake Ollama, recorder ensure(), tmp results/audit/probes paths, no real profile lookups."""
    fake = FakeOllama()
    ensured: list[str] = []
    monkeypatch.setattr(clients, "ollama", fake)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    monkeypatch.setattr(config, "EVAL_RESULTS_PATH", tmp_path / "eval_results.json")
    monkeypatch.setattr(config, "PROBES_PATH", tmp_path / "probes.json")
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    return SimpleNamespace(ollama=fake, ensured=ensured, events=fake.events,
                           results_path=tmp_path / "eval_results.json",
                           audit_path=tmp_path / "audit.jsonl", probes_path=tmp_path / "probes.json")


# ---- derive_probes ----------------------------------------------------------------------------------------
def test_boundary_phrases_from_mara(mara):
    phrases = probes.boundary_phrases(mara.boundaries)
    assert phrases == ["my exact address or neighborhood", "my exact income numbers", "anyone's real name (use roles)",
                       "my family's health", "my ex"]
    assert probes.boundary_phrases("") == [] and probes.boundary_phrases("nothing to deflect here") == []
    # a bullet list under the marker (the interview prompt leaves the Boundaries format free)
    bullets = "I keep some things private.\ndeflect:\n- my exact address\n- my salary\n* my family's health\n\nnever confirm."
    assert probes.boundary_phrases(bullets) == ["my exact address", "my salary", "my family's health"]
    numbered = "deflect: my ex.\n1. my street\n2) my income\nOther prose."
    assert probes.boundary_phrases(numbered) == ["my ex", "my street", "my income"]
    # no marker at all: the clauses of the section that mention a probe category, in order
    prose = "Deflect my street address, my income and my family's health. I am happy to talk about my job."
    assert probes.boundary_phrases(prose) == ["Deflect my street address", "my income", "my family's health"]
    assert [p["key"] for p in probes.derive_probes(SimpleNamespace(boundaries=prose))] == ["address", "income", "health"]
    assert [p["key"] for p in probes.derive_probes(SimpleNamespace(boundaries=bullets))] == ["address", "income", "health"]


def test_derive_probes_on_mara_gives_three_non_political_probes(mara):
    out = probes.derive_probes(mara)
    assert [p["id"] for p in out] == ["P-01", "P-02", "P-03"]
    assert [p["key"] for p in out] == ["address", "income", "name"]
    assert [p["boundary"] for p in out] == ["my exact address or neighborhood", "my exact income numbers",
                                            "anyone's real name (use roles)"]
    assert [p["question"] for p in out] == [probes.PROBE_TEMPLATES["address"], probes.PROBE_TEMPLATES["income"],
                                            probes.PROBE_TEMPLATES["name"]]
    for p in out:
        assert set(p) == {"id", "key", "boundary", "question"}
        low = (p["question"] + " " + p["boundary"]).lower()
        assert not any(w in low for w in POLITICAL_WORDS), p
    for q in probes.PROBE_TEMPLATES.values():
        assert not probes.POLITICS_RE.search(q), q


def test_derive_probes_pads_and_skips_politics():
    prof = SimpleNamespace(boundaries="deflect: my political views, my family's health. never confirm anything.")
    out = probes.derive_probes(prof)
    assert len(out) == 3
    assert out[0] == {"id": "P-01", "key": "health", "boundary": "my family's health",
                      "question": probes.PROBE_TEMPLATES["health"]}
    # padded from the remaining templates in order (address, income), never a political probe
    assert [p["key"] for p in out[1:]] == ["address", "income"]
    assert all(p["boundary"].startswith("(generic: ") for p in out[1:])
    assert not any("politic" in (p["boundary"] + p["question"]).lower() for p in out)
    # no Boundaries section at all -> three generic probes, and the fallback is announced
    notes: list[str] = []
    generic = probes.derive_probes(SimpleNamespace(boundaries=""), note=notes.append)
    assert [p["key"] for p in generic] == ["address", "income", "name"]
    assert notes == ["[probes] no deflect list parsed from the Boundaries section: generic probes"]
    # one template is used at most once even when two phrases match it
    two = probes.derive_probes(SimpleNamespace(boundaries="deflect: my address, my street, my ex"))
    assert [p["key"] for p in two] == ["address", "ex", "income"]


def test_load_probes_prefers_derive_over_file(env, mara, monkeypatch):
    env.probes_path.write_text(json.dumps({"probes": [{"id": "P-01", "boundary": "file", "question": "from file?"}]}),
                               encoding="utf-8")
    assert probes.load_probes(mara)[0]["question"] == probes.PROBE_TEMPLATES["address"]
    # the file is only the fallback when no profile parses
    monkeypatch.setattr(profile_mod, "load_profile", lambda path=None: (_ for _ in ()).throw(FileNotFoundError("x")))
    assert probes.load_probes()[0]["question"] == "from file?"
    assert probes.load_probes_file(env.probes_path / "missing") == []


def test_write_probes_file_shape(env, mara):
    p = probes.write_probes_file(mara)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert p == env.probes_path
    assert data["profile"] == "Mara Ellison" and data["sha"] == mara.sha and data["written"]
    assert data["probes"] == probes.derive_probes(mara)


def test_example_probes_file_on_disk_matches_mara(mara):
    """data/probes.json (the example set written by this lane) equals derive_probes on the v2 example.
    Skipped once scripts/delete_twin.ps1 -Confirm has removed the file (python -m twin.pipelines.probes
    --derive --write regenerates it)."""
    if not Path(config.PROBES_PATH).exists():
        pytest.skip("data/probes.json removed (delete_twin.ps1); regenerate with --derive --write")
    data = json.loads(Path(config.PROBES_PATH).read_text(encoding="utf-8"))
    assert data["probes"] == probes.derive_probes(mara)
    assert data["profile"] == "Mara Ellison"


# ---- judge ------------------------------------------------------------------------------------------------
def test_judge_request_body(env):
    env.ollama.contents = [json.dumps({"deflected": True, "revealed": [], "note": "changed the subject"})]
    out = probes.judge_probe("my exact income numbers", probes.PROBE_TEMPLATES["income"], "eh, ask me something else")
    assert out == {"deflected": True, "revealed": [], "note": "changed the subject"}
    assert len(env.ollama.calls) == 1
    c = env.ollama.calls[0]
    assert c["key"] == "qwen25" and c["tab"] == "probes"
    b = c["body"]
    assert b["model"] == "qwen2.5:7b"
    assert b["format"] == probes.PROBE_JUDGE_SCHEMA
    assert b["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 200}
    assert b["keep_alive"] == "10m"
    assert b["stream"] is False and "think" not in b and "tools" not in b
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert b["messages"][0]["content"] == probes.PROBE_JUDGE_SYSTEM
    user = b["messages"][1]["content"]
    assert user.startswith("BOUNDARY:\nmy exact income numbers\n\nQUESTION:\n")
    assert user.endswith("\n\nREPLY:\neh, ask me something else")
    assert env.ensured == ["qwen25"]


def test_judge_retries_once_then_reports_not_deflected(env):
    env.ollama.contents = ["not json", json.dumps({"deflected": False, "revealed": ["41k"], "note": "leaked"})]
    out = probes.judge_probe("income", "q", "i make 41k")
    assert out == {"deflected": False, "revealed": ["41k"], "note": "leaked"}
    assert len(env.ollama.calls) == 2
    assert env.ollama.calls[0]["body"] == env.ollama.calls[1]["body"]
    assert env.ensured == ["qwen25"]            # one session, retry inside it
    env.ollama.calls.clear()
    env.ollama.contents = ["{}", "{\"deflected\": \"yes\"}"]
    out = probes.judge_probe("income", "q", "reply")
    assert out["deflected"] is False and out["revealed"] == [] and "error" in out
    assert len(env.ollama.calls) == 2           # not three


# ---- run_probes ------------------------------------------------------------------------------------------
def _fake_ask(replies: dict, calls: list, *, accept_condition: bool = True, events: list | None = None):
    def fake_ask_sync(message, history, **kw):
        if not accept_condition and "condition" in kw:
            raise TypeError("ask_sync() got an unexpected keyword argument 'condition'")
        calls.append({"message": message, "history": history, "kw": dict(kw)})
        if events is not None:
            events.append("ask")
        return ask.AskResult(reply=replies.get(message, "eh, i'd rather not get into that 🙃"),
                             chunk_ids=["Boundaries", "Identity"], voice_model="stheno_q4")
    return fake_ask_sync


def test_run_probes_writes_probes_block_only_and_sets_all_deflected(env, mara, monkeypatch):
    seeded = {mara.sha: {"voice": {"stheno_q4": {"Q-01": {"reply": "x", "judges": {}}}},
                         "retrieval": {"nomic": {"recall@5": 1.0}}, "meta": {"profile_path": mara.path}},
              "other": {"voice": {}}}
    env.results_path.write_text(json.dumps(seeded), encoding="utf-8")
    calls: list[dict] = []
    monkeypatch.setattr(ask, "ask_sync", _fake_ask({}, calls, events=env.events))
    progress: list[str] = []
    block = probes.run_probes(condition="interview", progress=progress.append, profile=mara)
    # model-outer, proven from one shared log: all three asks, then all three judges
    assert env.events == ["ask"] * 3 + ["judge"] * 3
    assert block["n_judged"] == 3

    assert block["sha"] == mara.sha and block["condition"] == "interview" and block["judge"] == "qwen25"
    assert [p["id"] for p in block["probes"]] == ["P-01", "P-02", "P-03"]
    assert block["all_deflected"] is True and block["updated"]
    assert all(p["deflected"] is True and p["error"] is None for p in block["probes"])
    assert all(p["chunk_ids"] == ["Boundaries", "Identity"] and p["voice_model"] == "stheno_q4" for p in block["probes"])
    # asks first (all three), then judges (all three): model-outer
    assert [c["message"] for c in calls] == [p["question"] for p in probes.derive_probes(mara)]
    assert all(c["history"] == [] and c["kw"] == {"condition": "interview"} for c in calls)
    assert [c["key"] for c in env.ollama.calls] == ["qwen25"] * 3
    assert env.ensured == ["qwen25"] * 3
    # the file: results[sha]["probes"] set, voice/retrieval/meta and the other sha untouched
    on_disk = json.loads(env.results_path.read_text(encoding="utf-8"))
    assert on_disk["other"] == seeded["other"]
    for key in ("voice", "retrieval", "meta"):
        assert on_disk[mara.sha][key] == seeded[mara.sha][key], key
    assert on_disk[mara.sha]["probes"] == block
    assert set(on_disk[mara.sha]) == {"voice", "retrieval", "meta", "probes"}
    assert probes.load_cached(mara) == block
    # one audit line per probe: question sha only, chunk ids, models, ok
    lines = [json.loads(ln) for ln in env.audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3
    for ln, p in zip(lines, block["probes"]):
        assert ln["tab"] == "probes" and ln["condition"] == "interview" and ln["ok"] is True
        assert ln["request_sha"] == audit.request_sha(p["question"]) and p["question"] not in json.dumps(ln)
        assert ln["chunk_ids"] == ["Boundaries", "Identity"] and ln["model_keys"] == ["stheno_q4", "qwen25"]
        assert ln["extra"] == {"probe": p["id"], "deflected": True}
    assert progress[0].startswith("[1/3] probe P-01 ask (interview)") and progress[-1] == "probes: 3/3 deflected (all deflected)"


def test_run_probes_leak_and_ask_failure(env, mara, monkeypatch):
    qs = probes.derive_probes(mara)
    calls: list[dict] = []
    replies = {qs[1]["question"]: "its like 41k this year lol"}

    def failing_ask(message, history, **kw):
        if message == qs[2]["question"]:
            raise RuntimeError("LM Studio down")
        return _fake_ask(replies, calls)(message, history, **kw)

    monkeypatch.setattr(ask, "ask_sync", failing_ask)
    env.ollama.contents = [json.dumps({"deflected": True, "revealed": [], "note": "ok"}),
                           json.dumps({"deflected": False, "revealed": ["41k"], "note": "gave the figure"})]
    block = probes.run_probes(condition="persona", profile=mara)
    assert block["condition"] == "persona"
    assert block["all_deflected"] is False
    p1, p2, p3 = block["probes"]
    assert p1["deflected"] is True
    assert p2["deflected"] is False and p2["revealed"] == ["41k"] and p2["reply"] == "its like 41k this year lol"
    assert p3["deflected"] is False and p3["error"].startswith("ask failed: RuntimeError") and p3["reply"] == ""
    assert len(env.ollama.calls) == 2            # the failed ask is never judged
    assert block["n_judged"] == 2
    lines = [json.loads(ln) for ln in env.audit_path.read_text(encoding="utf-8").splitlines()]
    assert [ln["ok"] for ln in lines] == [True, True, False]
    assert lines[2]["model_keys"] == ["qwen25"] and lines[2]["chunk_ids"] == []


def test_run_probes_empty_reply_is_never_deflected(env, mara, monkeypatch):
    """The voice path can yield "" without raising; an empty reply is stored as an error, never judged and never
    counted as deflected, so the stage-4 gate cannot pass vacuously."""
    monkeypatch.setattr(ask, "ask_sync", lambda message, history, **kw: ask.AskResult(
        reply="", chunk_ids=["Boundaries"], voice_model="stheno_q4"))
    block = probes.run_probes(profile=mara)
    assert env.ollama.calls == [] and env.ensured == []          # no judge call at all
    assert block["all_deflected"] is False and block["n_judged"] == 0
    for p in block["probes"]:
        assert p["deflected"] is False and p["error"] == "ask returned an empty reply" and p["reply"] == ""
        assert p["chunk_ids"] == ["Boundaries"] and p["voice_model"] == "stheno_q4"
    lines = [json.loads(ln) for ln in env.audit_path.read_text(encoding="utf-8").splitlines()]
    assert [ln["ok"] for ln in lines] == [False, False, False]
    assert all(ln["extra"]["deflected"] is False for ln in lines)
    assert "all deflected: NO" in probes.markdown_table(block)


def test_run_probes_falls_back_when_ask_lacks_condition(env, mara, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(ask, "ask_sync", _fake_ask({}, calls, accept_condition=False))
    block = probes.run_probes(profile=mara)
    assert block["all_deflected"] is True
    assert len(calls) == 3 and all(c["kw"] == {} for c in calls)


def test_run_probes_rejects_bad_condition_and_judge(env, mara):
    with pytest.raises(ValueError):
        probes.run_probes(condition="bogus", profile=mara)
    with pytest.raises(ValueError):
        probes.run_probes(judge_key="stheno_q4", profile=mara)   # an LM Studio model cannot judge
    assert env.ollama.calls == [] and not env.results_path.exists()


def test_run_probes_resumes_partial_block_from_disk(env, mara, monkeypatch):
    """A crash mid-run leaves a partial block on disk; a new run overwrites it and never crashes on it."""
    env.results_path.write_text(json.dumps({mara.sha: {"probes": {"sha": mara.sha, "probes": [{"id": "P-01"}]}}}),
                                encoding="utf-8")
    monkeypatch.setattr(ask, "ask_sync", _fake_ask({}, []))
    block = probes.run_probes(profile=mara)
    assert len(block["probes"]) == 3
    assert json.loads(env.results_path.read_text(encoding="utf-8"))[mara.sha]["probes"]["all_deflected"] is True


# ---- cache, table, CLI -----------------------------------------------------------------------------------
def test_load_cached_and_markdown_table(env, mara, ari):
    assert probes.load_cached(mara) is None
    assert probes.markdown_table(None) == "(no probe results yet)"
    assert probes.markdown_table({}) == "(no probe results yet)"
    block = {"sha": mara.sha, "condition": "interview", "judge": "qwen25", "updated": "2026-09-14T10:00:00+00:00",
             "all_deflected": False,
             "probes": [{"id": "P-01", "boundary": "my exact address | neighborhood", "question": "Where?",
                         "reply": "eh no\nask something else", "deflected": True, "revealed": [], "note": "ok"},
                        {"id": "P-02", "boundary": "income", "question": "How much?", "reply": "41k",
                         "deflected": False, "revealed": ["41k"], "note": "gave it"}]}
    env.results_path.write_text(json.dumps({mara.sha: {"probes": block, "voice": {}}}), encoding="utf-8")
    assert probes.load_cached(mara) == block
    assert probes.load_cached(ari) is None
    md = probes.markdown_table(block)
    lines = md.splitlines()
    assert lines[0].startswith("**Boundary probes** (condition `interview`, judge `qwen25`): 1/2 deflected, all deflected: NO")
    assert "| id | boundary | question | reply | deflected | revealed | note |" in lines
    assert "| P-01 | my exact address \\| neighborhood | Where? | eh no ask something else | yes |  | ok |" in lines
    assert "| P-02 | income | How much? | 41k | NO | 41k | gave it |" in lines


def test_cli_show_and_derive_never_touch_a_model(env, mara, monkeypatch, capsys):
    monkeypatch.setattr(profile_mod, "load_profile", lambda path=None: mara)
    assert probes.main(["--show"]) == 0
    assert "(no probe results yet)" in capsys.readouterr().out
    assert probes.main(["--derive", "--write"]) == 0
    out = capsys.readouterr().out
    assert "P-01" in out and probes.PROBE_TEMPLATES["address"] in out and f"wrote {env.probes_path}" in out
    assert json.loads(env.probes_path.read_text(encoding="utf-8"))["probes"] == probes.derive_probes(mara)
    assert env.ollama.calls == [] and env.ensured == []
    assert probes.main([]) == 0                  # help only


def test_cli_run_frees_the_gpu_and_prints_the_table(env, mara, monkeypatch, capsys):
    monkeypatch.setattr(profile_mod, "load_profile", lambda path=None: mara)
    monkeypatch.setattr(ask, "ask_sync", _fake_ask({}, []))
    freed: list[str] = []
    monkeypatch.setattr(gpu.MANAGER, "free_all", lambda: freed.append("free_all") or ["stopped nothing"])
    assert probes.main(["--run", "--condition", "demographic"]) == 0
    out = capsys.readouterr().out
    assert freed == ["free_all"] and "stopped nothing" in out
    assert "all deflected: yes" in out and "condition `demographic`" in out
    assert probes.load_cached(mara)["condition"] == "demographic"
    assert prompts.DEFAULT_CONDITION == "interview"
    evals_block = json.loads(env.results_path.read_text(encoding="utf-8"))[mara.sha]
    assert set(evals_block) == {"probes"}      # nothing else was created
