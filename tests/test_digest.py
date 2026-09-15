"""Hermetic tests for twin.pipelines.digest against a fake Ollama client (exact request bodies, no network).

digest.py binds `DIGEST_PATH` at import (`from ..config import DIGEST_PATH`), so the tests patch
`twin.pipelines.digest.DIGEST_PATH` to a tmp file.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import clients, gpu
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH
from twin.pipelines import digest
from twin.profile import NO_CHUNK_SECTIONS, load_profile
from twin.prompts import DIGEST_SYSTEM

_REAL_OLLAMA = clients.ollama  # only its pure _chat_body is used
Q01_QUESTION = "How do you decide whether to take a job offer?"
Q01_ANSWER = "mostly time, not money."


class FakeOllama:
    """Records exact /api/chat bodies (built by the real client's pure `_chat_body`); replies from `contents`."""

    def __init__(self, contents=("a digest.",)):
        self.calls: list[dict] = []
        self.contents = list(contents)

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = _REAL_OLLAMA._chat_body(key, messages, options, format, tools, num_predict, stream,
                                          images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        content = self.contents.pop(0) if self.contents else ""
        return {"model": s.name, "message": {"role": "assistant", "content": content}, "done": True,
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9,
                "load_duration": 0}


@pytest.fixture
def env(monkeypatch, tmp_path: Path):
    fake = FakeOllama()
    ensured: list[str] = []
    monkeypatch.setattr(clients, "ollama", fake)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    path = tmp_path / "digest.md"
    monkeypatch.setattr(digest, "DIGEST_PATH", path)
    return SimpleNamespace(ollama=fake, ensured=ensured, path=path, profile=load_profile(EXAMPLE_PROFILE_PATH))


def test_build_digest_request_body(env):
    text = digest.build_digest(env.profile)
    assert text == "a digest."
    assert len(env.ollama.calls) == 1
    call = env.ollama.calls[0]
    assert call["key"] == "qwen3_long" and call["tab"] == "digest"
    b = call["body"]
    assert b["model"] == "qwen3:8b"
    assert b["think"] is False
    assert b["keep_alive"] == 0
    assert b["options"] == {"temperature": 0.3, "num_ctx": 40960, "num_predict": 500}
    assert b["stream"] is False
    assert "format" not in b and "tools" not in b
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert b["messages"][0]["content"] == DIGEST_SYSTEM


def test_user_text_has_profile_sections_but_not_eval(env):
    digest.build_digest(env.profile)
    user = env.ollama.calls[0]["body"]["messages"][1]["content"]
    assert user.startswith("PROFILE:\n\n")
    for sec in ("# Identity", "# Voice", "# Values", "# Preferences", "# People", "# Decisions", "# Goals",
                "# Boundaries"):
        assert sec in user, sec
    assert "## D-03: Buying a laptop" in user
    assert "# Eval" not in user
    assert Q01_QUESTION not in user and Q01_ANSWER not in user
    assert "## Q-01" not in user and "Question:" not in user
    assert user == "PROFILE:\n\n" + digest.profile_text_without_eval(env.profile)


def test_mara_text_excludes_eval_and_changelog(env):
    """v2 profile: the digest prompt carries every section except Eval AND Changelog (plan 3.1 / D1)."""
    mara = load_profile(EXAMPLE_PROFILE_V2_PATH)
    assert "Changelog" in mara.sections and "Eval" in mara.sections and NO_CHUNK_SECTIONS == ("Eval", "Changelog")
    text = digest.profile_text_without_eval(mara)
    assert text.startswith("name: Mara Ellison\nupdated: 2026-09-14")
    assert "# Changelog" not in text and "v2.0 (2026-09-14)" not in text and "initial synthetic example" not in text
    assert "# Eval" not in text and "## Q-01" not in text and "Question:" not in text
    assert "How do you decide whether to trust a new person?" not in text
    for sec in ("# Identity", "# Voice", "# Beliefs and attitudes", "# Routines", "# Life events", "# Self-ratings",
                "# Interview highlights", "# Expert reflections", "# Goals", "# Boundaries"):
        assert sec in text, sec
    assert "## D-15: Chose the cheaper apartment" in text and "## Psychologist" in text
    heads = [ln[2:] for ln in text.splitlines() if ln.startswith("# ")]
    assert heads == [s for s in mara.sections if s not in NO_CHUNK_SECTIONS]
    digest.build_digest(mara)
    user = env.ollama.calls[0]["body"]["messages"][1]["content"]
    assert user == "PROFILE:\n\n" + text and "Changelog" not in user


def test_written_file_first_line_is_sha_comment(env):
    digest.build_digest(env.profile)
    lines = env.path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"<!-- sha: {env.profile.sha} -->"
    assert lines[1:] == ["a digest."]
    assert digest.digest_sha() == env.profile.sha
    assert digest.digest_sha(env.path) == env.profile.sha


def test_load_digest_returns_text_without_sha_line(env):
    env.path.write_text(f"<!-- sha: {env.profile.sha} -->\nline one\nline two\n", encoding="utf-8")
    assert digest.load_digest() == "line one\nline two"
    env.path.unlink()
    assert digest.load_digest() == ""
    assert digest.digest_sha() is None
    env.path.write_text("no sha header\nbody\n", encoding="utf-8")
    assert digest.digest_sha() is None
    assert digest.load_digest() == "no sha header\nbody"


def test_ensure_digest_with_matching_sha_makes_zero_calls(env):
    env.path.write_text(f"<!-- sha: {env.profile.sha} -->\ncached digest\n", encoding="utf-8")
    assert digest.ensure_digest(env.profile) == "cached digest"
    assert env.ollama.calls == []
    assert env.ensured == []


def test_ensure_digest_rebuilds_on_sha_mismatch_and_force(env):
    env.path.write_text("<!-- sha: 0000 -->\nstale digest\n", encoding="utf-8")
    assert digest.ensure_digest(env.profile) == "a digest."
    assert len(env.ollama.calls) == 1
    assert digest.digest_sha() == env.profile.sha
    env.ollama.contents = ["fresh digest."]
    assert digest.ensure_digest(env.profile) == "a digest."  # now cached
    assert len(env.ollama.calls) == 1
    assert digest.ensure_digest(env.profile, force=True) == "fresh digest."
    assert len(env.ollama.calls) == 2
    assert digest.load_digest() == "fresh digest."


def test_empty_content_gets_exactly_one_retry(env):
    env.ollama.contents = ["", "second try."]
    assert digest.build_digest(env.profile) == "second try."
    assert len(env.ollama.calls) == 2
    assert env.ollama.calls[0]["body"] == env.ollama.calls[1]["body"]
    env.ollama.calls.clear()
    env.ollama.contents = ["", "   "]
    assert digest.build_digest(env.profile) == ""
    assert len(env.ollama.calls) == 2  # not three
    assert env.path.read_text(encoding="utf-8").splitlines()[0] == f"<!-- sha: {env.profile.sha} -->"


def test_manager_ensure_recorded_with_qwen3_long(env):
    digest.build_digest(env.profile)
    assert env.ensured == ["qwen3_long"]
    env.ollama.contents = ["", "x"]
    digest.build_digest(env.profile)
    assert env.ensured == ["qwen3_long", "qwen3_long"]  # one session per build, retry inside it
