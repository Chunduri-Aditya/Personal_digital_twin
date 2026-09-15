"""Parser tests for twin.profile (plus the pure-text helpers in twin.index and twin.prompts).

No network, no subprocess, no GPU: everything here is string parsing on
data/twin_profile.example.md and on synthetic profiles built in the tests.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH
from twin.profile import Chunk, Decision, EvalQA, Profile, chunk_ids, load_profile, parse_profile

SECTIONS = ["Identity", "Voice", "Values", "Preferences", "People", "Decisions", "Goals", "Boundaries", "Eval"]
PREF_KEYS = ["Food", "Tech and tools", "Work style", "Free time", "Money", "Communication"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def example_text() -> str:
    return EXAMPLE_PROFILE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def loaded() -> Profile:
    return load_profile(EXAMPLE_PROFILE_PATH)


@pytest.fixture(scope="module")
def parsed(example_text: str) -> Profile:
    return parse_profile(example_text, str(EXAMPLE_PROFILE_PATH))


# ---------------------------------------------------------------------------
# frontmatter, sha, path
# ---------------------------------------------------------------------------

def test_example_file_exists():
    assert EXAMPLE_PROFILE_PATH.exists(), f"missing {EXAMPLE_PROFILE_PATH}"


def test_frontmatter_values(loaded: Profile, parsed: Profile):
    for p in (loaded, parsed):
        assert p.name == "Ari"
        assert p.updated == "2026-09-13"
        assert p.path == str(EXAMPLE_PROFILE_PATH)


def test_sha_is_sha256_of_file_bytes(loaded: Profile):
    assert HEX64.match(loaded.sha), loaded.sha
    assert loaded.sha == hashlib.sha256(EXAMPLE_PROFILE_PATH.read_bytes()).hexdigest()


def test_parse_profile_sha_is_64_hex(parsed: Profile):
    assert HEX64.match(parsed.sha), parsed.sha


def test_frontmatter_parses_synthetic():
    text = "---\nname: Zed\nupdated: 2030-01-02\n---\n# Identity\nhello\n"
    p = parse_profile(text)
    assert p.name == "Zed"
    assert p.updated == "2030-01-02"
    assert p.path == ""
    assert p.identity == "hello"
    assert "---" not in p.sections.get("Identity", "")


def test_frontmatter_missing_gives_empty_name():
    p = parse_profile("# Identity\nno frontmatter here\n")
    assert p.name == ""
    assert p.updated == ""
    assert p.identity == "no frontmatter here"


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------

def test_sections_present_in_order(loaded: Profile):
    assert list(loaded.sections.keys()) == SECTIONS


def test_section_text_excludes_heading_line(loaded: Profile):
    for name, text in loaded.sections.items():
        assert not text.lstrip().startswith("# "), name
        assert f"# {name}" not in text.splitlines()[0:1], name


def test_convenience_fields_non_empty(loaded: Profile):
    assert loaded.identity.startswith("Ari, early 30s")
    assert loaded.boundaries.startswith("- never give an exact address")
    assert loaded.values.startswith("- honesty over comfort")
    assert loaded.goals.startswith("- keep the gym")
    assert loaded.people.startswith("- my manager")


def test_preferences_dict(loaded: Profile):
    assert list(loaded.preferences.keys()) == PREF_KEYS
    for k, v in loaded.preferences.items():
        assert v.strip(), k
    assert loaded.preferences["Food"].startswith("- cook at home most nights")


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------

def test_fifteen_decisions_with_sequential_ids(loaded: Profile):
    assert len(loaded.decisions) == 15
    assert [d.id for d in loaded.decisions] == [f"D-{i:02d}" for i in range(1, 16)]


def test_every_decision_has_all_fields(loaded: Profile):
    for d in loaded.decisions:
        assert isinstance(d, Decision)
        assert d.title.strip(), d.id
        assert d.situation.strip(), d.id
        assert isinstance(d.options, list), d.id
        assert len(d.options) >= 2, (d.id, d.options)
        assert all(o.strip() and o == o.strip() for o in d.options), (d.id, d.options)
        assert d.choice.strip(), d.id
        assert d.why.strip(), d.id
        assert d.outcome.strip(), d.id
        assert d.choice in d.options, (d.id, d.choice, d.options)


def test_decision_field_values_d03(loaded: Profile):
    d = loaded.decisions[2]
    assert d.id == "D-03"
    assert d.title == "Buying a laptop"
    assert d.situation.startswith("The old laptop's battery died after four years.")
    assert d.options == ["Premium thin laptop", "Mid-range business laptop with a good keyboard", "Gaming laptop"]
    assert d.choice == "Mid-range business laptop with a good keyboard"
    assert d.why.startswith("I type all day so the keyboard matters")
    assert d.outcome == "Two years in, still fine, replaced the battery myself once."


def test_decision_fields_do_not_bleed_into_each_other(loaded: Profile):
    for d in loaded.decisions:
        for label in ("Situation:", "Options:", "Choice:", "Why:", "Outcome:"):
            for value in (d.situation, d.choice, d.why, d.outcome):
                assert label not in value, (d.id, label)


def test_options_line_with_three_options_splits_into_three():
    text = (
        "---\nname: X\nupdated: 2030-01-01\n---\n"
        "# Decisions\n"
        "## D-01: Pick one\n"
        "Situation: Three things on the table.\n"
        "Options: Alpha | Beta two | Gamma three\n"
        "Choice: Beta two\n"
        "Why: Because.\n"
        "Outcome: unknown yet\n"
    )
    p = parse_profile(text)
    assert len(p.decisions) == 1
    d = p.decisions[0]
    assert d.id == "D-01"
    assert d.title == "Pick one"
    assert d.options == ["Alpha", "Beta two", "Gamma three"]
    assert d.choice == "Beta two"
    assert d.outcome == "unknown yet"
    assert chunk_ids(p) == ["Decisions/D-01"]


def test_options_line_with_two_options_splits_into_two():
    text = "# Decisions\n## D-07: T\nSituation: s\nOptions: A | B\nChoice: A\nWhy: w\nOutcome: o\n"
    assert parse_profile(text).decisions[0].options == ["A", "B"]


def test_decision_multiline_field_is_joined():
    text = (
        "# Decisions\n## D-02: T\n"
        "Situation: first line\nsecond line\n"
        "Options: A | B\nChoice: A\nWhy: w1\nw2\nOutcome: o\n"
    )
    d = parse_profile(text).decisions[0]
    assert d.situation == "first line second line"
    assert d.why == "w1 w2"
    assert d.outcome == "o"


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------

def test_twenty_eval_items_with_sequential_ids(loaded: Profile):
    assert len(loaded.eval) == 20
    assert [q.qid for q in loaded.eval] == [f"Q-{i:02d}" for i in range(1, 21)]


def test_every_eval_item_has_question_and_answer(loaded: Profile):
    for q in loaded.eval:
        assert isinstance(q, EvalQA)
        assert q.question.strip(), q.qid
        assert q.answer.strip(), q.qid
        assert not q.question.startswith("Question:"), q.qid
        assert not q.answer.startswith("Answer:"), q.qid


def test_eval_values_q01(loaded: Profile):
    q = loaded.eval[0]
    assert q.question == "How do you decide whether to take a job offer?"
    assert q.answer.startswith("mostly time, not money.")


def test_eval_section_kept_in_sections_but_produces_no_chunks(loaded: Profile):
    assert "Eval" in loaded.sections
    assert loaded.sections["Eval"].strip()
    for cid in chunk_ids(loaded):
        assert not cid.startswith("Eval"), cid
    assert all(c.section != "Eval" for c in loaded.chunks)


# ---------------------------------------------------------------------------
# chunks
# ---------------------------------------------------------------------------

def test_expected_chunk_ids_present(loaded: Profile):
    ids = chunk_ids(loaded)
    for want in ("Decisions/D-03", "Voice/Style rules", "Voice/Sample 1", "Preferences/Food",
                 "Identity", "Boundaries"):
        assert want in ids, (want, ids)


def test_chunk_ids_are_unique(loaded: Profile):
    ids = chunk_ids(loaded)
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]


def test_chunk_ids_helper_matches_chunks(loaded: Profile):
    assert chunk_ids(loaded) == [c.id for c in loaded.chunks]


def test_every_chunk_has_text_and_correct_section(loaded: Profile):
    for c in loaded.chunks:
        assert isinstance(c, Chunk)
        assert c.text.strip(), c.id
        assert c.section in SECTIONS, c.id
        assert c.id.split("/", 1)[0] == c.section, (c.id, c.section)
        assert c.title.strip(), c.id
        if "/" in c.id:
            assert c.subsection == c.id.split("/", 1)[1], (c.id, c.subsection)
        else:
            assert c.subsection == "", (c.id, c.subsection)
            assert c.title == c.section


def test_chunk_text_has_no_heading_lines(loaded: Profile):
    for c in loaded.chunks:
        for ln in c.text.splitlines():
            assert not ln.startswith("# "), (c.id, ln)
            assert not ln.startswith("## "), (c.id, ln)


def test_decision_chunk_keeps_full_heading_as_title(loaded: Profile):
    c = next(c for c in loaded.chunks if c.id == "Decisions/D-03")
    assert c.section == "Decisions"
    assert c.subsection == "D-03"
    assert c.title == "D-03: Buying a laptop"
    assert c.text.startswith("Situation:")
    assert "Outcome:" in c.text


def test_exact_chunk_layout(loaded: Profile):
    ids = chunk_ids(loaded)
    expected = (
        ["Identity", "Voice/Style rules"]
        + [f"Voice/Sample {i}" for i in range(1, 16)]
        + ["Values"]
        + [f"Preferences/{k}" for k in PREF_KEYS]
        + ["People"]
        + [f"Decisions/D-{i:02d}" for i in range(1, 16)]
        + ["Goals", "Boundaries"]
    )
    assert ids == expected


def test_no_intro_chunks_in_example(loaded: Profile):
    # Voice, Preferences and Decisions have no text before their first "##"
    assert not [i for i in chunk_ids(loaded) if i.endswith("/intro")]


def test_single_section_chunks_are_whole_section(loaded: Profile):
    ident = next(c for c in loaded.chunks if c.id == "Identity")
    assert ident.text == loaded.identity
    bnd = next(c for c in loaded.chunks if c.id == "Boundaries")
    assert bnd.text == loaded.boundaries


# ---------------------------------------------------------------------------
# voice
# ---------------------------------------------------------------------------

def test_style_rules_non_empty(loaded: Profile):
    assert loaded.style_rules.strip()
    assert loaded.style_rules.startswith("- lowercase almost always")
    assert loaded.style_rules == next(c.text for c in loaded.chunks if c.id == "Voice/Style rules")


def test_fifteen_samples_in_order(loaded: Profile):
    assert len(loaded.samples) == 15
    assert loaded.samples[0] == "hey. running like 10 min late, order me whatever you're having"
    assert loaded.samples[1].startswith("eh i don't think the new framework")
    assert loaded.samples[9] == "yo. pizza tonight? i'm cooking otherwise and you know how that goes"
    assert loaded.samples[14] == "ha. no. i'm not joining a startup that pays in vibes"
    sample_chunks = [c.text for c in loaded.chunks if c.id.startswith("Voice/Sample ")]
    assert loaded.samples == sample_chunks
    assert all(s.strip() for s in loaded.samples)


# ---------------------------------------------------------------------------
# long section splitting
# ---------------------------------------------------------------------------

def _para(n: int, width: int = 400) -> str:
    return (f"paragraph {n} " * (width // 12 + 1))[:width].strip()


def test_long_section_without_subsections_splits_on_blank_lines():
    paras = [_para(i) for i in range(1, 5)]  # 4 x 400 chars = 1600 > 1500
    body = "\n\n".join(paras)
    assert len(body) > 1500
    text = "---\nname: X\nupdated: 2030-01-01\n---\n# Identity\n" + body + "\n\n# Boundaries\nshort\n"
    p = parse_profile(text)
    ids = chunk_ids(p)
    assert "Identity" not in ids
    assert "Identity/1" in ids
    assert "Identity/2" in ids
    ident = [c for c in p.chunks if c.section == "Identity"]
    assert [c.id for c in ident] == [f"Identity/{i}" for i in range(1, 5)]
    assert [c.text for c in ident] == paras
    for c in ident:
        assert c.section == "Identity"
        assert c.title.strip()
    assert "Boundaries" in ids  # short section stays whole
    assert p.identity == body


def test_short_section_without_subsections_stays_single_chunk():
    body = "\n\n".join(_para(i, 300) for i in range(1, 4))  # 900 chars < 1500
    assert len(body) < 1500
    p = parse_profile("# Values\n" + body + "\n")
    assert chunk_ids(p) == ["Values"]
    assert p.chunks[0].text == body


def test_intro_chunk_when_text_precedes_first_subsection():
    text = "# Preferences\nsome intro text\n## Food\n- rice\n## Money\n- cheap\n"
    p = parse_profile(text)
    assert chunk_ids(p) == ["Preferences/intro", "Preferences/Food", "Preferences/Money"]
    intro = p.chunks[0]
    assert intro.text == "some intro text"
    assert intro.subsection == "intro"
    assert p.preferences == {"Food": "- rice", "Money": "- cheap"}


def test_heading_split_ignores_deeper_and_non_heading_hashes():
    text = "# Identity\nline with # inside\n#notaheading\n## Sub\ntext\n### deeper\nmore\n"
    p = parse_profile(text)
    assert list(p.sections) == ["Identity"]
    assert chunk_ids(p) == ["Identity/intro", "Identity/Sub"]
    assert p.chunks[0].text == "line with # inside\n#notaheading"
    assert p.chunks[1].text == "text\n### deeper\nmore"


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------

def test_resolve_profile_path_prefers_real_profile(tmp_path: Path, monkeypatch):
    real = tmp_path / "twin_profile.md"
    real.write_text("---\nname: Real\nupdated: 2030-01-01\n---\n# Identity\nreal\n", encoding="utf-8")
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", real)
    assert profile_mod.resolve_profile_path() == real
    p = load_profile()
    assert p.name == "Real"
    assert p.path == str(real)


def test_resolve_profile_path_falls_back_to_example(tmp_path: Path, monkeypatch):
    # v2: the v2 example (Mara) sits between the real profile and the Ari file, so pin it away too.
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", tmp_path / "does_not_exist.md")
    monkeypatch.setattr(profile_mod, "EXAMPLE_PROFILE_V2_PATH", tmp_path / "no_v2_example.md")
    assert profile_mod.resolve_profile_path() == EXAMPLE_PROFILE_PATH
    assert load_profile().name == "Ari"


def test_resolve_profile_path_order_real_then_v2_example_then_v1_example(tmp_path: Path, monkeypatch):
    real = tmp_path / "twin_profile.md"
    v2 = tmp_path / "twin_profile.example.v2.md"
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", real)
    monkeypatch.setattr(profile_mod, "EXAMPLE_PROFILE_V2_PATH", v2)
    # neither exists -> v1 example (Ari)
    assert profile_mod.resolve_profile_path() == EXAMPLE_PROFILE_PATH
    # v2 example exists, real missing -> v2 example
    v2.write_bytes(EXAMPLE_PROFILE_V2_PATH.read_bytes())
    assert profile_mod.resolve_profile_path() == v2
    assert load_profile().name == "Mara Ellison"
    # real exists -> real, whatever else is on disk
    real.write_text("---\nname: Real\nupdated: 2030-01-01\n---\n# Identity\nreal\n", encoding="utf-8")
    assert profile_mod.resolve_profile_path() == real
    assert load_profile().name == "Real"
    # the shipped v2 example is what the default order falls back to today
    assert EXAMPLE_PROFILE_V2_PATH.exists()


def test_load_profile_accepts_str_path():
    assert load_profile(str(EXAMPLE_PROFILE_PATH)).name == "Ari"


def test_load_profile_tolerates_utf8_bom(tmp_path: Path):
    # Windows Notepad saves UTF-8 with a BOM; the first line is still the first "---" line.
    text = "---\nname: Ari\nupdated: 2026-09-13\n---\n# Identity\nhello\n"
    f = tmp_path / "bom.md"
    f.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    p = load_profile(f)
    assert p.name == "Ari", "frontmatter lost when the file starts with a UTF-8 BOM"
    assert p.updated == "2026-09-13"
    assert p.sha == hashlib.sha256(f.read_bytes()).hexdigest()
    assert parse_profile("﻿" + text).name == "Ari"


def test_crlf_line_endings_parse_like_lf(tmp_path: Path):
    lf = "---\nname: Ari\nupdated: 2026-09-13\n---\n# Identity\nhello\n\n# Decisions\n## D-01: T\nSituation: a\nb\nOptions: A | B | C\nChoice: A\nWhy: w\nOutcome: o\n"
    a = parse_profile(lf)
    b = parse_profile(lf.replace("\n", "\r\n"))
    assert (b.name, b.updated, b.identity) == (a.name, a.updated, a.identity)
    assert chunk_ids(b) == chunk_ids(a)
    assert b.decisions == a.decisions
    assert b.decisions[0].situation == "a b"
    assert b.decisions[0].options == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# twin.index text prefixes
# ---------------------------------------------------------------------------

def test_index_keys_match_contract():
    from twin.index import INDEX_KEYS
    assert INDEX_KEYS == {"nomic": "nomic_ollama", "gemma": "embeddinggemma", "lms_nomic": "nomic_lms"}


@pytest.mark.parametrize("key", ["nomic", "lms_nomic"])
def test_nomic_doc_and_query_prefixes(key):
    from twin.index import doc_text, query_text
    c = Chunk(id="Identity", section="Identity", subsection="", title="Identity", text="Ari, early 30s")
    assert doc_text(key, c) == "search_document: Ari, early 30s"
    assert doc_text(key, {"title": "Identity", "text": "Ari, early 30s"}) == "search_document: Ari, early 30s"
    assert query_text(key, "who are you") == "search_query: who are you"


def test_gemma_doc_and_query_prefixes():
    from twin.index import doc_text, query_text
    c = Chunk(id="Decisions/D-03", section="Decisions", subsection="D-03", title="D-03: Buying a laptop",
              text="Situation: old laptop died")
    assert doc_text("gemma", c) == "title: D-03: Buying a laptop | text: Situation: old laptop died"
    assert doc_text("gemma", {"title": "T", "text": "X"}) == "title: T | text: X"
    assert query_text("gemma", "what laptop") == "task: search result | query: what laptop"


# ---------------------------------------------------------------------------
# twin.prompts.postprocess_voice
# ---------------------------------------------------------------------------

def test_postprocess_strips_action_and_name_prefix():
    from twin.prompts import postprocess_voice
    assert postprocess_voice("*smiles* Ari: hey there", "Ari") == "hey there"


def test_postprocess_strips_surrounding_quotes():
    from twin.prompts import postprocess_voice
    assert postprocess_voice('"hey there"', "Ari") == "hey there"
    assert postprocess_voice("“hey there”", "Ari") == "hey there"
    assert postprocess_voice('"Ari: hey there"', "Ari") == "hey there"


def test_postprocess_strips_ai_tail_and_leaves_plain_text_alone():
    from twin.prompts import postprocess_voice
    assert postprocess_voice("hey there\nAs an AI language model I cannot", "Ari") == "hey there"
    assert postprocess_voice("hey there", "Ari") == "hey there"
    assert postprocess_voice("", "Ari") == ""
    assert postprocess_voice("ari: yo", "Ari") == "yo"


# ===========================================================================
# schema v2 (docs/PLAN_UNIFIED.md 3.1): the Mara example, new fields, lint, CLI
# ===========================================================================

V2_SECTIONS = ["Identity", "Voice", "Values", "Beliefs and attitudes", "Preferences", "Routines", "People",
               "Decisions", "Life events", "Self-ratings", "Interview highlights", "Expert reflections", "Goals",
               "Boundaries", "Eval", "Changelog"]
LENSES = ["Psychologist", "Behavioral economist", "Political scientist", "Demographer"]
BELIEFS = ["Work and money", "Society and politics", "Technology", "Religion and meaning", "Risk and change"]
LIFE_EVENTS = ["Leaving home at 18", "The year i was fully broke", "Losing my grandmother"]
HIGHLIGHTS = ["On failure", "On money", "On being told what to do", "On close friends"]
MARA_IDS = (
    ["Identity", "Voice/Style rules"] + [f"Voice/Sample {i}" for i in range(1, 16)] + ["Values"]
    + [f"Beliefs and attitudes/{k}" for k in BELIEFS]
    + [f"Preferences/{k}" for k in PREF_KEYS]
    + ["Routines/Weekday", "Routines/Weekend", "People"]
    + [f"Decisions/D-{i:02d}" for i in range(1, 16)]
    + [f"Life events/{k}" for k in LIFE_EVENTS] + ["Self-ratings"]
    + [f"Interview highlights/{k}" for k in HIGHLIGHTS]
    + [f"Expert reflections/{k}" for k in LENSES]
    + ["Goals", "Boundaries"]
)
POLITICS_ID = "Beliefs and attitudes/Society and politics"
LINT_KEYS = {"chunks_over", "chunks_under", "prefix_tokens", "prefix_budget", "words", "word_band",
             "missing_sections", "warnings", "eval_chunks", "changelog_chunks"}


@pytest.fixture(scope="module")
def mara() -> Profile:
    return load_profile(EXAMPLE_PROFILE_V2_PATH)


def test_v2_frontmatter_fields(mara: Profile, loaded: Profile):
    assert EXAMPLE_PROFILE_V2_PATH.exists()
    assert mara.name == "Mara Ellison" and mara.updated == "2026-09-14"
    assert mara.schema_version == "v2"
    assert mara.embedder == "nomic-embed-text (768-dim)"
    assert mara.eval_frozen is True
    assert mara.consent == "", "consent is optional and the example has none"
    assert mara.sha == hashlib.sha256(EXAMPLE_PROFILE_V2_PATH.read_bytes()).hexdigest()
    # the v1 file keeps the defaults
    assert (loaded.schema_version, loaded.embedder, loaded.eval_frozen, loaded.consent) == ("", "", False, "")
    assert loaded.reflections == {} and loaded.beliefs == {} and loaded.routines == {}
    assert loaded.life_events == {} and loaded.highlights == {} and loaded.self_ratings == ""


def test_v2_frontmatter_consent_and_booleans_synthetic():
    p = parse_profile("---\nname: Zed\nupdated: 2030-01-01\nschema_version: v2\nembedder: nomic\n"
                      "eval_frozen: false\nconsent: 2030-01-02 stored locally, roles only\n---\n# Identity\nhi\n")
    assert p.consent == "2030-01-02 stored locally, roles only"
    assert p.eval_frozen is False and p.schema_version == "v2" and p.embedder == "nomic"
    for raw, want in (("true", True), ("yes", True), ("1", True), ("on", True), ("no", False), ("", False), ("nope", False)):
        assert parse_profile(f"---\nname: Z\neval_frozen: {raw}\n---\n# Identity\nx\n").eval_frozen is want, raw


def test_v2_sections_present_in_order(mara: Profile):
    assert list(mara.sections) == V2_SECTIONS
    assert mara.sections["Changelog"].startswith("v2.0 (2026-09-14)")
    assert mara.sections["Eval"].strip()


def test_changelog_and_eval_are_never_chunked(mara: Profile):
    assert "Changelog" in mara.sections and "Eval" in mara.sections
    for c in mara.chunks:
        assert c.section not in ("Eval", "Changelog"), c.id
        assert not c.id.startswith(("Eval", "Changelog")), c.id
    assert profile_mod.NO_CHUNK_SECTIONS == ("Eval", "Changelog")
    gold = mara.eval[0].answer
    assert gold and all(gold not in c.text for c in mara.chunks)
    assert all("v2.0 (2026-09-14)" not in c.text for c in mara.chunks)
    p = parse_profile("# Identity\nx\n# Changelog\nv1 first\n# Eval\n## Q-01\nQuestion: q?\nAnswer: a.\n")
    assert chunk_ids(p) == ["Identity"]
    assert p.sections["Changelog"] == "v1 first" and p.eval[0].answer == "a."


def test_mara_chunk_ids_exact(mara: Profile):
    assert chunk_ids(mara) == MARA_IDS
    assert len(mara.chunks) == 61 and len(set(chunk_ids(mara))) == 61
    for c in mara.chunks:
        assert c.id.split("/", 1)[0] == c.section
        assert c.section in V2_SECTIONS and c.text.strip()
        assert c.source == "profile"


def test_v2_new_section_chunk_shapes(mara: Profile):
    by_id = {c.id: c for c in mara.chunks}
    c = by_id["Expert reflections/Psychologist"]
    assert c.section == "Expert reflections" and c.subsection == "Psychologist" and c.title == "Psychologist"
    assert c.text.startswith("Introverted and mildly anxious")
    c = by_id["Beliefs and attitudes/Technology"]
    assert c.subsection == "Technology" and c.text.startswith("i'm torn")
    c = by_id["Life events/Leaving home at 18"]
    assert c.subsection == "Leaving home at 18" and c.title == "Leaving home at 18"
    assert by_id["Routines/Weekday"].text.startswith("wake around 9:30")
    assert by_id["Self-ratings"].subsection == "" and by_id["Self-ratings"].title == "Self-ratings"
    assert by_id["Interview highlights/On money"].text.startswith("i've been broke enough")
    assert by_id[POLITICS_ID].subsection == "Society and politics"


def test_v2_convenience_dicts(mara: Profile):
    assert list(mara.reflections) == LENSES
    assert mara.reflections["Demographer"].startswith("Late-20s urban freelance creative")
    assert list(mara.beliefs) == BELIEFS
    assert list(mara.routines) == ["Weekday", "Weekend"]
    assert mara.routines["Weekend"].startswith("i don't really separate weekends")
    assert list(mara.life_events) == LIFE_EVENTS
    assert list(mara.highlights) == HIGHLIGHTS
    assert mara.self_ratings.startswith("extraversion: low") and mara.self_ratings == mara.sections["Self-ratings"].strip()
    assert list(mara.preferences) == PREF_KEYS
    assert len(mara.decisions) == 15 and len(mara.eval) == 20 and len(mara.samples) == 15
    assert mara.eval[0].question == "How do you decide whether to trust a new person?"
    for d in (mara.reflections, mara.beliefs, mara.routines, mara.life_events, mara.highlights):
        assert all(v.strip() and "## " not in v for v in d.values())
    by_id = {c.id: c for c in mara.chunks}
    assert mara.reflections["Psychologist"] == by_id["Expert reflections/Psychologist"].text
    assert mara.beliefs["Risk and change"] == by_id["Beliefs and attitudes/Risk and change"].text


def test_chunk_source_field_defaults_to_profile():
    c = Chunk("Identity", "Identity", "", "Identity", "text")
    assert c.source == "profile"
    assert Chunk("Interview/T-001", "Interview", "T-001", "T-001: x", "Q: q\nA: a", "transcript").source == "transcript"
    assert list(Chunk.__dataclass_fields__) == ["id", "section", "subsection", "title", "text", "source"]


def test_approx_tokens():
    from twin.profile import approx_tokens
    assert approx_tokens("") == 1 and approx_tokens(None) == 1
    assert approx_tokens("ab") == 1 and approx_tokens("abcd") == 1
    assert approx_tokens("a" * 400) == 100 and approx_tokens("a" * 1200) == 300 and approx_tokens("a" * 1204) == 301
    for n in (7, 13, 99, 1201):
        assert approx_tokens("x" * n) == max(1, round(n / 4))


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

def test_lint_keys_and_politics_warning_on_mara(mara: Profile):
    from twin.prompts import build_voice_prefix
    rep = profile_mod.lint(mara)
    assert set(rep) == LINT_KEYS
    assert rep["eval_chunks"] == 0 and rep["changelog_chunks"] == 0
    assert rep["prefix_budget"] == 1500 and rep["word_band"] == (4000, 7000)
    assert rep["prefix_tokens"] == profile_mod.approx_tokens(build_voice_prefix(mara, ""))
    assert 0 < rep["prefix_tokens"] < 1500
    assert rep["missing_sections"] == []
    assert rep["chunks_over"] == []
    assert isinstance(rep["words"], int) and rep["words"] > 1000
    assert any(POLITICS_ID in w for w in rep["warnings"]), rep["warnings"]
    assert any("politics" in w.lower() for w in rep["warnings"])
    for cid, n in rep["chunks_under"]:
        assert n < 80 and cid in chunk_ids(mara)
        assert not cid.startswith(("Voice/Sample", "Identity", "Boundaries", "Goals", "Self-ratings")), cid
    under_ids = [cid for cid, _ in rep["chunks_under"]]
    assert "Voice/Sample 1" not in under_ids and "Self-ratings" not in under_ids
    assert "Beliefs and attitudes/Technology" in under_ids
    assert rep["words"] == profile_mod.substantive_words(mara)


def test_lint_ari_missing_sections_and_no_politics_warning(loaded: Profile):
    rep = profile_mod.lint(loaded, "a digest")
    assert rep["missing_sections"] == ["Beliefs and attitudes", "Routines", "Life events", "Self-ratings",
                                       "Interview highlights", "Expert reflections", "Changelog"]
    assert not any("politics" in w.lower() for w in rep["warnings"])
    assert any("schema_version" in w for w in rep["warnings"]) and any("embedder" in w for w in rep["warnings"])
    assert rep["eval_chunks"] == 0 and rep["changelog_chunks"] == 0
    assert rep["prefix_tokens"] > profile_mod.lint(loaded)["prefix_tokens"], "the digest counts toward the prefix"
    assert [cid for cid, _ in rep["chunks_under"]] == [f"Preferences/{k}" for k in PREF_KEYS]


def test_lint_digest_is_capped_and_budget_warning():
    from twin.prompts import build_voice_prefix
    p = parse_profile("---\nname: Z\n---\n# Identity\n" + ("word " * 1500).strip() + "\n# Boundaries\nb\n")
    rep = profile_mod.lint(p, "d" * 5000)
    assert rep["prefix_tokens"] == profile_mod.approx_tokens(build_voice_prefix(p, "d" * 5000))
    assert rep["prefix_tokens"] > 1500
    assert any("exceeds the 1500 budget" in w for w in rep["warnings"])
    small = parse_profile("# Identity\nhi\n")
    assert profile_mod.lint(small, "x" * 8000)["prefix_tokens"] == profile_mod.approx_tokens(
        "IDENTITY:\nhi\n\nABOUT YOU (digest):\n" + "x" * 1600)


def test_lint_flags_oversized_chunks_and_word_band():
    para = ("token " * 330).strip()          # ~1980 chars -> about 495 tokens in one paragraph
    p = parse_profile("# Values\n" + para + "\n\n" + "short\n")
    rep = profile_mod.lint(p)
    assert rep["chunks_over"] and rep["chunks_over"][0][0] == "Values/1" and rep["chunks_over"][0][1] > 300
    assert any("over 300 tokens" in w for w in rep["warnings"])
    assert any("under the 4000-7000 band" in w for w in rep["warnings"])
    big = parse_profile("# Identity\n" + "\n\n".join(("w " * 400).strip() for _ in range(20)) + "\n")
    assert profile_mod.lint(big)["words"] == 8000
    assert any("over the 4000-7000 band" in w for w in profile_mod.lint(big)["warnings"])


def test_lint_counts_stray_eval_chunks():
    p = parse_profile("# Identity\nx\n")
    p.chunks.append(Chunk("Eval/Q-01", "Eval", "Q-01", "Q-01", "gold answer text"))
    p.chunks.append(Chunk("Changelog", "Changelog", "", "Changelog", "v1"))
    rep = profile_mod.lint(p)
    assert rep["eval_chunks"] == 1 and rep["changelog_chunks"] == 1
    assert any("Eval chunk" in w for w in rep["warnings"]) and any("Changelog chunk" in w for w in rep["warnings"])


def test_substantive_words_skips_eval_changelog_and_heading_marks():
    p = parse_profile("# Identity\none two three\n# Preferences\n## Food\nfour five\n# Eval\n## Q-01\nQuestion: q?\n"
                      "Answer: many many words here\n# Changelog\nv1 lots of words\n")
    assert profile_mod.substantive_words(p) == 6


def test_lint_cli_reports_digest_state_and_exit_codes(mara: Profile, monkeypatch, tmp_path: Path, capsys):
    digest = tmp_path / "digest.md"
    monkeypatch.setattr(profile_mod, "DIGEST_PATH", digest)
    digest.write_text(f"<!-- sha: {mara.sha} -->\nMara is a freelance illustrator.\n", encoding="utf-8")
    assert profile_mod.main(["--lint", str(EXAMPLE_PROFILE_V2_PATH)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("profile: ") and "Mara Ellison, schema v2" in out[0] and "61 chunks" in out[0]
    assert "changelog chunks: 0" in out and "eval chunks: 0" in out
    prefix = next(ln for ln in out if ln.startswith("prefix: "))
    assert re.match(r"^prefix: \d+ tokens of 1500 budget \(digest: present\)$", prefix)
    assert any(re.match(r"^words: \d+ \(band 4000-7000\)$", ln) for ln in out)
    assert "chunks over 300 tokens: none" in out
    assert any(ln.startswith("chunks under 80 tokens: ") and "Beliefs and attitudes/Technology (" in ln for ln in out)
    assert "missing sections: none" in out
    assert any(ln.startswith("WARNING: chunk 'Beliefs and attitudes/Society and politics' present") for ln in out)
    # stale digest: another sha; missing digest: no file
    digest.write_text("<!-- sha: 0000 -->\nold\n", encoding="utf-8")
    profile_mod.main(["--lint", str(EXAMPLE_PROFILE_V2_PATH)])
    assert "(digest: stale)" in capsys.readouterr().out
    digest.unlink()
    profile_mod.main(["--lint", str(EXAMPLE_PROFILE_V2_PATH)])
    assert "(digest: missing)" in capsys.readouterr().out
    # the Ari file lists its missing v2 sections
    profile_mod.main(["--lint", str(EXAMPLE_PROFILE_PATH)])
    out = capsys.readouterr().out
    assert "missing sections: Beliefs and attitudes, Routines, Life events, Self-ratings, Interview highlights, " \
           "Expert reflections, Changelog" in out
    assert "Society and politics" not in out
    # parse failure -> exit 2 on stderr; no --lint -> help, exit 0
    assert profile_mod.main(["--lint", str(tmp_path / "nope.md")]) == 2
    assert "parse failed" in capsys.readouterr().err
    assert profile_mod.main([]) == 0
    assert "--lint" in capsys.readouterr().out


def test_lint_cli_without_path_uses_resolve_order(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(profile_mod, "DIGEST_PATH", tmp_path / "digest.md")
    monkeypatch.setattr(profile_mod, "PROFILE_PATH", tmp_path / "missing.md")
    monkeypatch.setattr(profile_mod, "EXAMPLE_PROFILE_V2_PATH", tmp_path / "missing_v2.md")
    assert profile_mod.main(["--lint"]) == 0
    assert "(Ari, schema v1" in capsys.readouterr().out
    monkeypatch.setattr(profile_mod, "EXAMPLE_PROFILE_V2_PATH", EXAMPLE_PROFILE_V2_PATH)
    assert profile_mod.main(["--lint"]) == 0
    assert "(Mara Ellison, schema v2" in capsys.readouterr().out
