"""Hermetic tests for twin.pipelines.reflect: lenses, corpus text, exact qwen3:8b request bodies (fake client
built on the real `_chat_body`), the sha-comment cache and the '## <lens>' file format. No network, no GPU.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import clients, gpu, index
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH, EXAMPLE_TRANSCRIPT_PATH
from twin.pipelines import reflect
from twin.profile import load_profile, parse_profile
from twin.transcript import load_transcript

_REAL_OLLAMA = clients.ollama
FOUR = ["Psychologist", "Behavioral economist", "Political scientist", "Demographer"]
Q01_GOLD = "slow, i watch how they treat people who can't do anything for them"


class FakeOllama:
    def __init__(self, contents=None):
        self.calls: list[dict] = []
        self.contents = list(contents) if contents is not None else None

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = _REAL_OLLAMA._chat_body(key, messages, options, format, tools, num_predict, stream,
                                          images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        if self.contents is None:
            content = f"notes {len(self.calls)} for the lens in the system prompt."
        else:
            content = self.contents.pop(0) if self.contents else ""
        return {"model": s.name, "message": {"role": "assistant", "content": content}, "done": True,
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9,
                "load_duration": 0}


@pytest.fixture(scope="module")
def mara():
    return load_profile(EXAMPLE_PROFILE_V2_PATH)


@pytest.fixture(scope="module")
def ari():
    return load_profile(EXAMPLE_PROFILE_PATH)


@pytest.fixture(scope="module")
def ttext() -> str:
    return reflect.transcript_text(load_transcript(EXAMPLE_TRANSCRIPT_PATH))


@pytest.fixture
def env(monkeypatch, tmp_path: Path):
    fake = FakeOllama()
    ensured: list[str] = []
    monkeypatch.setattr(clients, "ollama", fake)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    path = tmp_path / "reflections.md"
    monkeypatch.setattr(reflect, "REFLECTIONS_PATH", path)
    return SimpleNamespace(ollama=fake, ensured=ensured, path=path)


# ---------------------------------------------------------------------------
# lenses and prompts
# ---------------------------------------------------------------------------

def test_lenses_constant_and_politics_gate(mara, ari):
    assert reflect.LENSES == tuple(FOUR)
    assert reflect.lenses_for(mara) == FOUR                       # Mara has the Society and politics chunk
    assert reflect.lenses_for(ari) == ["Psychologist", "Behavioral economist", "Demographer"]
    with_pol = parse_profile("# Identity\nx\n# Beliefs and attitudes\n## Society and politics\ny\n")
    without = parse_profile("# Identity\nx\n# Beliefs and attitudes\n## Technology\ny\n")
    assert "Political scientist" in reflect.lenses_for(with_pol)
    assert "Political scientist" not in reflect.lenses_for(without)
    assert reflect.lenses_for(without) == ["Psychologist", "Behavioral economist", "Demographer"]


def test_reflect_system_prompt():
    s = reflect.REFLECT_SYSTEM("Behavioral economist", "Mara Ellison")
    assert s.startswith("You are an experienced behavioral economist")
    assert "Mara Ellison" in s and "120-220 words" in s and "third person" in s
    assert "no headings" in s and "never invent" in s
    assert reflect.REFLECT_SYSTEM("Psychologist", "Ari") != s


def test_corpus_text_excludes_eval_and_changelog_and_appends_transcript(mara, ttext):
    c = reflect.corpus_text(mara, ttext)
    assert c.startswith("PROFILE:\nname: Mara Ellison\nupdated: 2026-09-14")
    for sec in ("# Identity", "# Voice", "# Values", "# Beliefs and attitudes", "# Decisions", "# Expert reflections",
                "# Goals", "# Boundaries"):
        assert f"\n\n{sec}\n" in c, sec
    assert "# Eval" not in c and "# Changelog" not in c
    assert "## Q-01" not in c and "Question:" not in c and Q01_GOLD not in c
    assert "v2.0 (2026-09-14)" not in c
    assert c.endswith("\n\nINTERVIEW TRANSCRIPT:\n" + ttext)
    assert "## T-001" in c and "## T-039" not in c
    empty = reflect.corpus_text(mara, "")
    assert empty.endswith("\n\nINTERVIEW TRANSCRIPT:\n")
    assert reflect.corpus_text(mara, None) == empty


def test_transcript_text_only_included_turns(ttext):
    assert ttext.startswith("# Block 1: Life story & future\n## T-001\nQ: ")
    assert "## T-038" in ttext and "## T-039" not in ttext and "# Block 7" not in ttext
    assert Q01_GOLD not in ttext
    assert ttext.count("## T-") == 38


def test_reflections_key_formula(mara):
    t_sha = hashlib.sha256(b"hello").hexdigest()
    assert reflect.reflections_key(mara, "hello") == hashlib.sha256(f"{mara.sha}|{t_sha}".encode()).hexdigest()
    assert reflect.reflections_key(mara, "") != reflect.reflections_key(mara, "hello")
    assert reflect.reflections_key(mara, None) == reflect.reflections_key(mara, "")


# ---------------------------------------------------------------------------
# build_reflections
# ---------------------------------------------------------------------------

def test_build_reflections_one_call_per_lens_with_exact_body(env, mara, ttext):
    body = reflect.build_reflections(mara, ttext)
    assert len(env.ollama.calls) == 4
    assert env.ensured == ["qwen3_long"], "one MANAGER.session for all lenses"
    user = reflect.corpus_text(mara, ttext)
    for lens, call in zip(FOUR, env.ollama.calls):
        assert call["key"] == "qwen3_long" and call["tab"] == "reflect"
        b = call["body"]
        assert b["model"] == "qwen3:8b"
        assert b["think"] is False
        assert b["keep_alive"] == 0
        assert b["options"] == {"temperature": 0.3, "num_ctx": 40960, "num_predict": 400}
        assert b["stream"] is False and "format" not in b and "tools" not in b
        assert [m["role"] for m in b["messages"]] == ["system", "user"]
        assert b["messages"][0]["content"] == reflect.REFLECT_SYSTEM(lens, "Mara Ellison")
        assert b["messages"][1]["content"] == user
    lines = env.path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"<!-- sha: {reflect.reflections_key(mara, ttext)} -->"
    expected = "\n\n".join(f"## {lens}\nnotes {i} for the lens in the system prompt." for i, lens in enumerate(FOUR, 1))
    assert body == expected
    assert "\n".join(lines[1:]) == expected
    assert reflect.load_reflections(env.path) == {lens: f"notes {i} for the lens in the system prompt."
                                                  for i, lens in enumerate(FOUR, 1)}
    assert reflect.load_reflections() == reflect.load_reflections(env.path)
    assert reflect.reflections_sha() == reflect.reflections_key(mara, ttext)


def test_build_reflections_skips_political_lens_without_the_chunk(env, ari):
    reflect.build_reflections(ari, "", tab="index")
    assert [c["body"]["messages"][0]["content"].split(" writing")[0] for c in env.ollama.calls] == [
        "You are an experienced psychologist", "You are an experienced behavioral economist",
        "You are an experienced demographer"]
    assert all(c["tab"] == "index" for c in env.ollama.calls)
    assert list(reflect.load_reflections()) == ["Psychologist", "Behavioral economist", "Demographer"]
    assert "Political scientist" not in env.path.read_text(encoding="utf-8")


def test_build_reflections_retries_once_on_empty(env, mara):
    env.ollama.contents = ["", "psych text", "econ", "<think>hmm</think>## Pol\npol text", "demo"]
    body = reflect.build_reflections(mara, "")
    assert len(env.ollama.calls) == 5
    assert env.ollama.calls[0]["body"] == env.ollama.calls[1]["body"]
    assert env.ensured == ["qwen3_long"]
    got = reflect.load_reflections()
    assert got == {"Psychologist": "psych text", "Behavioral economist": "econ", "Political scientist": "Pol\npol text",
                   "Demographer": "demo"}
    assert "<think>" not in body
    # empty twice -> exactly two calls for that lens, the block is written empty and dropped on load
    env.ollama.calls.clear()
    env.ollama.contents = ["", "   ", "b", "c", "d"]
    reflect.build_reflections(mara, "")
    assert len(env.ollama.calls) == 5
    assert "Psychologist" not in reflect.load_reflections()
    body = reflect.load_body()
    assert body.startswith("## Psychologist\n") and "## Behavioral economist\nb" in body
    assert reflect.load_reflections() == {"Behavioral economist": "b", "Political scientist": "c", "Demographer": "d"}


def test_clean_strips_think_tags_and_heading_marks():
    assert reflect._clean("<think>x</think>\n# Title\ntext\n\n\n\n### sub\nmore") == "Title\ntext\n\nsub\nmore"
    assert reflect._clean("") == "" and reflect._clean(None) == ""


# ---------------------------------------------------------------------------
# cache: ensure_reflections, load_reflections, reflections_sha
# ---------------------------------------------------------------------------

def test_ensure_reflections_caches_by_key_and_rebuilds_on_change_or_force(env, mara, ttext):
    first = reflect.ensure_reflections(mara, ttext)
    assert len(env.ollama.calls) == 4 and first.startswith("## Psychologist\n")
    assert reflect.ensure_reflections(mara, ttext) == first
    assert len(env.ollama.calls) == 4, "matching key: no model call"
    assert env.ensured == ["qwen3_long"]
    # a different transcript text changes the key -> rebuild
    reflect.ensure_reflections(mara, ttext + "\nextra")
    assert len(env.ollama.calls) == 8
    assert reflect.reflections_sha() == reflect.reflections_key(mara, ttext + "\nextra")
    # force rebuilds even when the key matches
    reflect.ensure_reflections(mara, ttext + "\nextra", force=True)
    assert len(env.ollama.calls) == 12
    # a stale or malformed sha line rebuilds too
    env.path.write_text("<!-- sha: 0000 -->\n## Psychologist\nold\n", encoding="utf-8")
    assert reflect.ensure_reflections(mara, ttext) != "## Psychologist\nold"
    assert len(env.ollama.calls) == 16


def test_load_reflections_and_sha_when_missing_or_malformed(env):
    assert reflect.load_reflections() == {} and reflect.reflections_sha() is None and reflect.load_body() == ""
    env.path.write_text("no sha line\n## Psychologist\ntext\n", encoding="utf-8")
    assert reflect.reflections_sha() is None
    assert reflect.load_reflections() == {"Psychologist": "text"}
    env.path.write_text("<!-- sha: abc -->\nintro ignored\n## A\n\n## B\nb1\nb2\n\n## C\n  \n", encoding="utf-8")
    assert reflect.reflections_sha() == "abc"
    assert reflect.load_reflections() == {"B": "b1\nb2"}
    other = env.path.with_name("other.md")
    other.write_text("<!-- sha: zzz -->\n## D\nd\n", encoding="utf-8")
    assert reflect.reflections_sha(other) == "zzz" and reflect.load_reflections(other) == {"D": "d"}
    assert reflect.reflections_sha(str(other)) == "zzz"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_prints_lenses_and_char_counts_then_stops_ollama(env, mara, monkeypatch, capsys):
    stops: list[int] = []
    monkeypatch.setattr(reflect, "load_profile", lambda path=None: mara)
    monkeypatch.setattr(index, "resolve_transcript_source", lambda no_redact=False, quiet=False: EXAMPLE_TRANSCRIPT_PATH)
    monkeypatch.setattr(index, "_stop_all_ollama", lambda: stops.append(1))
    assert reflect.main([]) == 0
    out = capsys.readouterr().out
    assert "profile: " in out and "Mara Ellison" in out
    assert f"transcript: {EXAMPLE_TRANSCRIPT_PATH}" in out and "chars of included turns" in out
    assert "lenses: Psychologist, Behavioral economist, Political scientist, Demographer" in out
    for lens in FOUR:
        assert f"{lens}: " in out and " chars" in out
    assert f"wrote {env.path} (key {reflect.reflections_sha()})" in out
    assert stops == [1] and len(env.ollama.calls) == 4
    # cached second run: no model call, still stops Ollama; --force rebuilds
    assert reflect.main([]) == 0
    assert len(env.ollama.calls) == 4 and stops == [1, 1]
    assert reflect.main(["--force"]) == 0
    assert len(env.ollama.calls) == 8 and stops == [1, 1, 1]


def test_cli_reports_redaction_required(env, mara, monkeypatch, capsys):
    monkeypatch.setattr(reflect, "load_profile", lambda path=None: mara)

    def boom(no_redact=False, quiet=False):
        raise index.RedactionRequired("run python -m twin.redact first")

    monkeypatch.setattr(index, "resolve_transcript_source", boom)
    assert reflect.main([]) == 2
    assert "error: run python -m twin.redact first" in capsys.readouterr().out
    assert env.ollama.calls == []
