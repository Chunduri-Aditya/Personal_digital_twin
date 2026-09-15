"""Hermetic tests for twin.redact: regex rules, the deterministic name heuristic, role tags, the qwen3_8k pass
(fake client records the exact /api/chat body) and whole-transcript redaction into tmp files. No network, no GPU.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import clients, gpu, redact
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_V2_PATH, EXAMPLE_TRANSCRIPT_PATH, spec
from twin.profile import load_profile
from twin.transcript import parse_transcript

_REAL_OLLAMA = clients.ollama  # only its pure _chat_body is used

PLANTED_NAME = "Tobias Wren"
PLANTED_EMAIL = "bookings@saltlinecoffee.com"
PLANTED = ("Tobias", "Wren", "saltlinecoffee", "bookings@")


def ollama_response(model: str, content: str) -> dict:
    return {"model": model, "message": {"role": "assistant", "content": content}, "done": True,
            "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5, "eval_duration": 1e9, "load_duration": 0}


class FakeOllama:
    """Records exact /api/chat bodies (built by the real client's pure `_chat_body`); replies pop from `replies`."""

    def __init__(self, replies=None):
        self.calls: list[dict] = []
        self.replies = list(replies or [])
        self.ps_entries: list[dict] = []
        self.stopped: list[str] = []

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None, stream=False,
             images_on_last_user=None, tab=""):
        s, body = _REAL_OLLAMA._chat_body(key, messages, options, format, tools, num_predict, stream,
                                          images_on_last_user)
        self.calls.append({"key": key, "body": body, "tab": tab})
        content = self.replies.pop(0) if self.replies else json.dumps({"names": []})
        return ollama_response(s.name, content)

    def ps(self):
        return list(self.ps_entries)

    def stop(self, name):
        self.stopped.append(name)


@pytest.fixture(scope="module")
def mara():
    return load_profile(EXAMPLE_PROFILE_V2_PATH)


@pytest.fixture
def env(monkeypatch, tmp_path: Path, mara):
    fake = FakeOllama()
    ensured: list[str] = []
    monkeypatch.setattr(clients, "ollama", fake)
    monkeypatch.setattr(gpu.MANAGER, "ensure", lambda key: ensured.append(key))
    monkeypatch.setattr(redact, "REDACTION_REPORT_PATH", tmp_path / "redaction_report.json")
    monkeypatch.setattr(redact, "TRANSCRIPT_PATH", tmp_path / "interview_transcript.md")
    monkeypatch.setattr(redact, "REDACTED_TRANSCRIPT_PATH", tmp_path / "interview_transcript.redacted.md")
    monkeypatch.setattr(profile_mod, "resolve_profile_path", lambda: EXAMPLE_PROFILE_V2_PATH)
    example = tmp_path / "interview_transcript.example.md"
    shutil.copy(EXAMPLE_TRANSCRIPT_PATH, example)
    return SimpleNamespace(ollama=fake, ensured=ensured, tmp=tmp_path, example=example, mara=mara,
                           report_path=tmp_path / "redaction_report.json")


# ---------------------------------------------------------------------------
# regex layer
# ---------------------------------------------------------------------------

def test_regex_rule_names_and_order():
    names = [n for n, _, _ in redact.REGEX_RULES]
    assert set(names) == {"email", "phone", "address", "id-number", "profile-url"}
    assert names.index("email") < names.index("profile-url"), "emails are taken before URLs"
    for _, pat, tag in redact.REGEX_RULES:
        assert hasattr(pat, "finditer") and tag.startswith("[") and tag.endswith("]")


@pytest.mark.parametrize("text,want,rule", [
    ("mail me at bookings@saltlinecoffee.com ok", "mail me at [email] ok", "email"),
    ("or first.last+tag@sub.example.co.uk today", "or [email] today", "email"),
    ("call 555-0123 tonight", "call [phone] tonight", "phone"),
    ("call +1 555 0100 tonight", "call [phone] tonight", "phone"),
    ("call (020) 7946 0958 now", "call [phone] now", "phone"),
    ("lived at 221B Baker Street for a bit", "lived at [address] for a bit", "address"),
    ("lived at 12 Harbour Rd. for a bit", "lived at [address] for a bit", "address"),
    ("moved to 4 Long Winding Lane last year", "moved to [address] last year", "address"),
    ("my account 123456789 ok", "my account [id-number] ok", "id-number"),
    ("card 1234 5678 9012 3456 ok", "card [id-number] ok", "id-number"),
    ("id 12-3456-7890 ok", "id [id-number] ok", "id-number"),
    ("see https://github.com/maradraws ok", "see [profile-url] ok", "profile-url"),
    ("see x.com/mara_e ok", "see [profile-url] ok", "profile-url"),
    ("see instagram.com/@mara.draws ok", "see [profile-url] ok", "profile-url"),
    ("see https://www.linkedin.com/in/mara-ellison ok", "see [profile-url] ok", "profile-url"),
    ("see https://reddit.com/u/mara ok", "see [profile-url] ok", "profile-url"),
])
def test_each_regex_rule_on_crafted_strings(text, want, rule):
    red, report = redact.redact_text(text, use_llm=False)
    assert red == want
    assert report["counts"][rule] == 1, report["counts"]
    assert sum(report["counts"].values()) == 1
    assert report["replacements"] == [f"[{rule}]"]


def test_regex_layer_leaves_dates_times_and_small_numbers_alone():
    text = ("date it today, 2026-09-14, and we're good. i drew from 4 to about 1am, 14 minutes, 12 hour days, "
            "$9, 30 percent, 9:30, the new one is 1200 dollars")
    red, report = redact.redact_text(text, use_llm=False)
    assert red == text
    assert sum(report["counts"].values()) == 0 and report["replacements"] == []


def test_regex_counts_every_hit_and_orders_tags():
    text = "a@b.io then c@d.io then https://github.com/someone then 555-0123"
    red, report = redact.redact_text(text, use_llm=False)
    assert red == "[email] then [email] then [profile-url] then [phone]"
    assert report["counts"]["email"] == 2 and report["counts"]["profile-url"] == 1 and report["counts"]["phone"] == 1
    assert report["replacements"] == ["[email]", "[email]", "[profile-url]", "[phone]"]


def test_phone_with_country_code_is_tagged_phone():
    red, report = redact.redact_text("call +1 555-123-4567 tonight", use_llm=False)
    assert red == "call [phone] tonight"
    assert report["counts"]["phone"] == 1 and report["counts"]["id-number"] == 0


def test_phone_rule_runs_before_id_number_but_leaves_bare_ids_alone():
    names = [n for n, _, _ in redact.REGEX_RULES]
    assert names.index("phone") < names.index("id-number")
    red, report = redact.redact_text("acct 123456789 card 1234 5678 9012 3456 ph +44 20 7946 0958", use_llm=False)
    assert red == "acct [id-number] card [id-number] ph [phone]"
    assert report["counts"]["id-number"] == 2 and report["counts"]["phone"] == 1


def test_userinfo_url_is_profile_url_and_trailing_slash_is_consumed():
    red, report = redact.redact_text("see https://user@host.example.com/x and https://www.linkedin.com/in/mara-ellison/ ok",
                                     use_llm=False)
    assert red == "see [profile-url] and [profile-url] ok"
    assert report["counts"]["profile-url"] == 2 and report["counts"]["email"] == 0


# ---------------------------------------------------------------------------
# name heuristic
# ---------------------------------------------------------------------------

CRAFTED = ("i met Tobias Wren on Tuesday, Mara said hi. Honestly it was fine, we drew a Heron and a heron. "
           "Later on Wren texted me in March and the Block was quiet")


def test_heuristic_finds_planted_two_word_name_and_leftover_surname():
    found = redact.find_names_heuristic(CRAFTED, own_name="Mara Ellison")
    assert "Tobias Wren" in found
    assert "Wren" in found                      # capitalised, not sentence-initial, never lowercase elsewhere
    assert "Mara" not in found and "Ellison" not in found
    assert "Tuesday" not in found and "March" not in found
    assert "Honestly" not in found and "Later" not in found and "Block" not in found
    assert "Heron" not in found, "a word that also appears lowercase elsewhere is not a name"
    assert redact.NAME_HEURISTIC is redact.find_names_heuristic


def test_heuristic_skips_sentence_initial_single_words_but_not_capitalised_runs():
    assert redact.find_names_heuristic("Procreate crashed again. Yesterday too.") == []
    found = redact.find_names_heuristic("Tobias Wren texted.")
    assert found[0] == "Tobias Wren" and "Tobias" not in found     # the run wins; "Tobias" is sentence-initial
    assert redact.find_names_heuristic("i use Procreate daily") == ["Procreate"]
    red, _ = redact.redact_text("Tobias Wren texted.", use_llm=False)
    assert red == "[a person] texted."


def test_heuristic_corpus_allowlist_and_own_name():
    text = "then Sam called"
    assert redact.find_names_heuristic(text) == ["Sam"]
    assert redact.find_names_heuristic(text, corpus="then Sam called. sam is my friend") == []
    assert redact.find_names_heuristic(text, own_name="Sam Ellison") == []


def test_redact_text_heuristic_replaces_with_a_person_and_keeps_own_name(env):
    red, report = redact.redact_text(CRAFTED, use_llm=False, own_name="Mara Ellison")
    assert "Tobias" not in red and "Wren" not in red
    assert "Mara said hi" in red and "on Tuesday" in red and "in March" in red
    assert red.count("[a person]") == 2
    assert report["counts"]["names_heuristic"] == 2 and report["counts"]["names_llm"] == 0
    assert report["replacements"] == ["[a person]", "[a person]"]
    assert env.ollama.calls == [] and env.ensured == []
    assert set(report) == {"counts", "replacements"}
    assert all(isinstance(r, str) and r.startswith("[") for r in report["replacements"])


def test_redact_text_never_puts_removed_strings_in_the_report(env):
    _, report = redact.redact_text("Tobias Wren wrote to a@b.io from 221B Baker Street", use_llm=False)
    blob = json.dumps(report)
    for bad in ("Tobias", "Wren", "a@b.io", "Baker"):
        assert bad not in blob


# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------

def test_roles_from_people_text(mara):
    roles = redact.roles_from_people(mara.people)
    assert roles[-1] == "a person"
    assert "my older brother" in roles
    assert "my best friend from art school" in roles
    assert "my mentor" in roles
    assert "my ex" in roles
    assert all(r == "a person" or r.startswith("my ") for r in roles)
    assert len(roles) == len(set(roles))
    assert redact.roles_from_profile(mara) == roles
    assert redact.roles_from_people("") == ["a person"]
    assert redact.roles_from_people("- my manager (calm, direct)\n- my sister, lives abroad") == [
        "my manager", "my sister", "a person"]


def test_coerce_role():
    roles = ["my older brother", "my mentor", "a person"]
    assert redact.coerce_role("My Mentor", roles) == "my mentor"
    assert redact.coerce_role("my landlord", roles) == "a person"
    assert redact.coerce_role(None, roles) == "a person"


# ---------------------------------------------------------------------------
# qwen3_8k pass
# ---------------------------------------------------------------------------

def test_find_names_llm_request_body(env):
    env.ollama.replies = [json.dumps({"names": [{"name": "Tobias Wren", "role": "my mentor"},
                                                {"name": "Sam", "role": "the landlord"}]})]
    roles = ["my older brother", "my mentor"]
    out = redact.find_names_llm("Tobias Wren and Sam came over", roles)
    assert out == [{"name": "Tobias Wren", "role": "my mentor"}, {"name": "Sam", "role": "a person"}]
    assert len(env.ollama.calls) == 1
    call = env.ollama.calls[0]
    s = spec("qwen3_8k")
    assert call["key"] == "qwen3_8k" and call["tab"] == "redact"
    b = call["body"]
    assert b["model"] == s.name == "qwen3-8b-8k"
    assert b["format"] == redact.NAMES_SCHEMA
    assert b["think"] is False
    assert b["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 200}
    assert b["keep_alive"] == "10m" and b["stream"] is False and "tools" not in b
    assert [m["role"] for m in b["messages"]] == ["system", "user"]
    assert b["messages"][0]["content"] == redact.NAMES_SYSTEM
    user = b["messages"][1]["content"]
    assert user.startswith("ROLES: my older brother; my mentor; a person")
    assert user.endswith("\n\nTURN:\nTobias Wren and Sam came over")
    assert env.ensured == ["qwen3_8k"], "the call runs inside MANAGER.session('qwen3_8k')"


def test_names_schema_shape():
    assert redact.NAMES_SCHEMA == {
        "type": "object",
        "properties": {"names": {"type": "array", "items": {
            "type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}},
            "required": ["name", "role"]}}},
        "required": ["names"],
    }


def test_find_names_llm_retries_once_on_invalid_json(env):
    env.ollama.replies = ["not json", json.dumps({"names": [{"name": "Sam", "role": "my mentor"}]})]
    out = redact.find_names_llm("Sam came over", ["my mentor"])
    assert out == [{"name": "Sam", "role": "my mentor"}]
    assert len(env.ollama.calls) == 2
    assert env.ollama.calls[0]["body"] == env.ollama.calls[1]["body"]
    assert env.ensured == ["qwen3_8k"], "both attempts inside one session"
    # names not a list -> also invalid; two bad answers -> [] after exactly two calls
    env.ollama.calls.clear()
    env.ollama.replies = [json.dumps({"names": "Sam"}), "{broken"]
    assert redact.find_names_llm("Sam came over", ["my mentor"]) == []
    assert len(env.ollama.calls) == 2


def test_redact_text_llm_path_uses_role_tags(env):
    env.ollama.replies = [json.dumps({"names": [{"name": "Tobias Wren", "role": "my mentor"}]})]
    red, report = redact.redact_text("ok his name was Tobias Wren, and later Wren again", use_llm=True,
                                     roles=["my mentor"], own_name="Mara Ellison")
    assert red == "ok his name was [my mentor], and later Wren again" or red == "ok his name was [my mentor], and later [a person] again"
    assert "Tobias" not in red
    assert report["counts"]["names_llm"] == 1
    assert report["replacements"][0] == "[my mentor]"
    assert len(env.ollama.calls) == 1


def test_redact_text_llm_never_replaces_the_subjects_own_name(env):
    env.ollama.replies = [json.dumps({"names": [{"name": "Mara", "role": "a person"}]})]
    red, report = redact.redact_text("Mara went home", use_llm=True, own_name="Mara Ellison")
    assert red == "Mara went home" and report["counts"]["names_llm"] == 0


def test_redact_text_llm_skips_pronouns_common_nouns_and_acronyms(env):
    """Live run 2026-09-14: qwen3 returned 'you', 'she', 'the cat', 'my grandmother', 'AI' as names and the text
    came back as "when [a person]'re lying". Only candidates with a capitalised, non-allowlisted token apply."""
    text = ("people always know when you're lying, she said, and the cat agreed; my grandmother used the AI "
            "stuff too. later Tobias Wren and Sam came by the harbour, the Harbour was quiet")
    env.ollama.replies = [json.dumps({"names": [
        {"name": "you", "role": "a person"}, {"name": "she", "role": "a person"},
        {"name": "the cat", "role": "a person"}, {"name": "my grandmother", "role": "a person"},
        {"name": "AI", "role": "a person"}, {"name": "Tobias Wren", "role": "my mentor"},
        {"name": "Sam", "role": "a person"}, {"name": "the Harbour", "role": "a person"}]})]
    red, report = redact.redact_text(text, use_llm=True, roles=["my mentor"], own_name="Mara Ellison")
    assert "when you're lying, she said, and the cat agreed; my grandmother used the AI stuff" in red
    assert "the Harbour was quiet" in red, "a word that also appears lowercase in the text is not a name"
    assert "[my mentor]" in red and "[a person] came by" in red
    assert "Tobias" not in red and "Sam" not in red
    assert report["counts"]["names_llm"] == 2
    allow = redact._allowlist("Mara Ellison", None, text)
    assert redact.plausible_name("Tobias Wren", allow) and redact.plausible_name("O'Brien", allow)
    assert not redact.plausible_name("you", allow) and not redact.plausible_name("AI", allow)
    assert not redact.plausible_name("the cat", allow) and not redact.plausible_name("Mara", allow)


# ---------------------------------------------------------------------------
# whole transcript
# ---------------------------------------------------------------------------

def test_redact_transcript_example_without_llm(env):
    src = env.example
    src_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    removed: list[str] = []
    report = redact.redact_transcript(src, use_llm=False, profile=env.mara, on_removed=removed.extend)
    out = env.tmp / "interview_transcript.example.redacted.md"
    assert Path(report["output"]) == out and out.exists()
    assert report["source"] == str(src) and report["source_sha"] == src_sha
    assert report["turns"] == 60 and report["llm"] is False
    assert report["counts"]["email"] == 1 and report["counts"]["names_heuristic"] == 1
    assert report["counts"]["names_llm"] == 0
    assert sum(report["counts"].values()) == 2, report["counts"]
    assert report["replacements"] == ["[email]", "[a person]"]
    assert set(report) == {"source", "source_sha", "output", "turns", "llm", "counts", "replacements", "redacted_at"}
    assert removed == [PLANTED_EMAIL, PLANTED_NAME], "removed strings go to the console callback only"

    text = out.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    assert "redacted: true" in fm and f"source_sha: {src_sha}" in fm and "redacted_at: " in fm
    assert "name: Mara Ellison" in fm and "exclude_blocks: [7]" in fm
    for bad in PLANTED:
        assert bad not in text, bad
    assert "[email]" in text and "[a person]" in text
    t = parse_transcript(text)
    assert len(t.turns) == 60 and t.blocks == 7 and t.exclude_blocks == [7]
    assert t.meta["source_sha"] == src_sha and t.meta["redacted"] == "true"
    assert [x.id for x in t.turns] == [f"T-{i:03d}" for i in range(1, 61)]
    assert t.block_titles[7] == "Gold answers & wrap"
    assert next(x for x in t.turns if x.id == "T-031").answer.count("[a person]") == 1
    assert "[email]" in next(x for x in t.turns if x.id == "T-021").answer
    # every other turn is untouched
    orig = parse_transcript(src.read_text(encoding="utf-8"))
    for a, b in zip(orig.turns, t.turns):
        if a.id not in ("T-021", "T-031"):
            assert (a.question, a.answer) == (b.question, b.answer), a.id

    report_text = env.report_path.read_text(encoding="utf-8")
    for bad in PLANTED:
        assert bad not in report_text, bad
    assert json.loads(report_text) == report
    assert redact.load_report() == report
    assert env.ollama.calls == [] and env.ensured == []


def test_redact_transcript_llm_once_per_turn(env):
    env.ollama.replies = [json.dumps({"names": [{"name": "Tobias Wren", "role": "my mentor"}]})
                          if i == 30 else json.dumps({"names": []}) for i in range(60)]
    report = redact.redact_transcript(env.example, use_llm=True, profile=env.mara)
    assert len(env.ollama.calls) == 60, "one qwen3_8k call per turn"
    assert env.ensured == ["qwen3_8k"] * 60
    assert all(c["body"]["format"] == redact.NAMES_SCHEMA and c["tab"] == "redact" for c in env.ollama.calls)
    assert report["llm"] is True
    assert report["counts"]["names_llm"] == 1 and report["counts"]["names_heuristic"] == 0
    assert report["counts"]["email"] == 1
    assert "[my mentor]" in report["replacements"]
    text = Path(report["output"]).read_text(encoding="utf-8")
    assert "[my mentor]" in text
    for bad in PLANTED:
        assert bad not in text
    # the email was removed by the regex layer before the model saw the turn
    t021 = next(c for c in env.ollama.calls if "found the very first client contact" in c["body"]["messages"][1]["content"])
    assert PLANTED_EMAIL not in t021["body"]["messages"][1]["content"] and "[email]" in t021["body"]["messages"][1]["content"]


def test_default_output_paths(env):
    real = env.tmp / "interview_transcript.md"
    assert redact.default_output_path(real) == env.tmp / "interview_transcript.redacted.md"
    assert redact.default_output_path(env.example) == env.tmp / "interview_transcript.example.redacted.md"
    shutil.copy(env.example, real)
    report = redact.redact_transcript(real, use_llm=False, profile=env.mara)
    assert Path(report["output"]) == env.tmp / "interview_transcript.redacted.md"
    assert (env.tmp / "interview_transcript.redacted.md").exists()


def test_explicit_dst_and_profile_fallback(env):
    dst = env.tmp / "sub" / "custom.md"
    report = redact.redact_transcript(env.example, dst, use_llm=False)   # profile=None -> load_profile() (Mara)
    assert Path(report["output"]) == dst and dst.exists()
    assert report["counts"]["names_heuristic"] == 1
    assert redact.load_report()["output"] == str(dst)


def test_load_report_missing_or_bad(env):
    assert redact.load_report() is None
    env.report_path.write_text("[1, 2]", encoding="utf-8")
    assert redact.load_report() is None
    env.report_path.write_text("{not json", encoding="utf-8")
    assert redact.load_report() is None


def test_missing_source_raises(env):
    with pytest.raises(FileNotFoundError):
        redact.redact_transcript(env.tmp / "nope.md", use_llm=False, profile=env.mara)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_no_llm_on_tmp_copy(env, capsys):
    rc = redact.main([str(env.example), "--no-llm"])
    assert rc == 0
    out = capsys.readouterr().out
    assert (env.tmp / "interview_transcript.example.redacted.md").exists()
    assert "turns: 60, llm pass: no (--no-llm)" in out
    assert "counts: " in out and "email 1" in out and "names_heuristic 1" in out
    assert "tags used: [email] x1, [a person] x1" in out
    assert f"report: {env.report_path}" in out
    # the console (and only the console) shows what was removed, for the user's check
    assert "removed (console only, never written to a file): " in out
    assert PLANTED_EMAIL in out and PLANTED_NAME in out
    for bad in PLANTED:
        assert bad not in env.report_path.read_text(encoding="utf-8")
    assert env.ollama.calls == []


def test_cli_out_flag_and_missing_file(env, capsys):
    dst = env.tmp / "elsewhere.md"
    assert redact.main([str(env.example), "--out", str(dst), "--no-llm"]) == 0
    assert dst.exists() and f"-> {dst}" in capsys.readouterr().out
    assert redact.main([str(env.tmp / "missing.md"), "--no-llm"]) == 2
    assert "error:" in capsys.readouterr().out


def test_cli_llm_mode_stops_loaded_ollama_models(env, capsys):
    env.ollama.ps_entries = [{"name": "qwen3-8b-8k:latest", "model": "qwen3-8b-8k:latest"}]
    assert redact.main([str(env.example)]) == 0
    assert len(env.ollama.calls) == 60
    assert env.ollama.stopped == ["qwen3-8b-8k:latest"]
    assert "llm pass: yes" in capsys.readouterr().out
