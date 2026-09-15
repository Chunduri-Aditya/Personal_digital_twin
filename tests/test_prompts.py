"""Tests for the condition-aware prompt builders in twin.prompts (docs/PLAN_UNIFIED.md 3.4).

Pure string assembly on the Ari and Mara example profiles; no network, no GPU.
"""
from __future__ import annotations

import pytest

from twin import prompts
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH
from twin.profile import load_profile

DIGEST = "Ari is a quiet backend developer who picks boring, reliable options and hedges a lot."
CHUNKS = [
    {"id": "Decisions/D-01", "section": "Decisions", "subsection": "D-01", "title": "D-01: Bought the boring phone",
     "text": "Situation: needed a phone. Choice: the boring one.", "score": 0.71},
    {"id": "Values", "section": "Values", "subsection": "", "title": "Values",
     "text": "boring reliability: i pick the option that still works in four years.", "score": 0.66},
    {"id": "Interview/T-004a", "section": "Interview", "subsection": "T-004a", "title": "",
     "text": "Q: what did you learn?\nA: that i'm allergic to being managed.", "source": "transcript"},
]


@pytest.fixture(scope="module")
def ari():
    return load_profile(EXAMPLE_PROFILE_PATH)


@pytest.fixture(scope="module")
def mara():
    return load_profile(EXAMPLE_PROFILE_V2_PATH)


def full_prefix(p, digest: str, n_samples: int = 3, digest_chars: int = 1600) -> str:
    """The phase-1 static prefix, assembled independently of the module."""
    parts = ["IDENTITY:\n" + p.identity.strip(), "STYLE RULES:\n" + p.style_rules.strip(),
             "SAMPLES OF HOW YOU WRITE:\n" + "\n".join(f"- {s.strip()}" for s in p.samples[:n_samples]),
             "BOUNDARIES (refuse or deflect):\n" + p.boundaries.strip()]
    if digest:
        parts.append("ABOUT YOU (digest):\n" + digest.strip()[:digest_chars])
    return "\n\n".join(parts)


def samples_block(prefix: str) -> str:
    return prefix.split("SAMPLES OF HOW YOU WRITE:\n", 1)[1].split("\n\n", 1)[0]


def context_block(chunks) -> str:
    lines = [f"[{i}] ({c.get('title') or c.get('id', '')}) {c.get('text', '').strip()}" for i, c in enumerate(chunks, 1)]
    return "\n".join(lines) if lines else "(nothing retrieved)"


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

def test_conditions_and_default():
    assert prompts.CONDITIONS == ("demographic", "persona", "interview")
    assert prompts.DEFAULT_CONDITION == "interview"
    assert prompts.DEFAULT_CONDITION in prompts.CONDITIONS


def test_voice_system_no_context_differs_only_in_the_grounding_sentence():
    a = prompts.VOICE_SYSTEM("Ari")
    b = prompts.VOICE_SYSTEM_NO_CONTEXT("Ari")
    assert a.endswith("Only state facts about yourself that appear in CONTEXT; otherwise say you don't remember.")
    assert b.endswith("Only state facts about yourself that appear above; otherwise say you don't remember.")
    assert a.rsplit("Only state facts", 1)[0] == b.rsplit("Only state facts", 1)[0]
    assert a.startswith("You are Ari, replying as yourself") and b.startswith("You are Ari, replying as yourself")
    assert "CONTEXT" not in b


# ---------------------------------------------------------------------------
# build_voice_prefix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("who", ["ari", "mara"])
def test_prefix_persona_and_interview_are_byte_identical_to_phase_one(who, request):
    p = request.getfixturevalue(who)
    base = prompts.build_voice_prefix(p, DIGEST)
    assert base == full_prefix(p, DIGEST)
    assert prompts.build_voice_prefix(p, DIGEST, condition="interview") == base
    assert prompts.build_voice_prefix(p, DIGEST, condition="persona") == base
    assert prompts.build_voice_prefix(p, DIGEST, condition=prompts.DEFAULT_CONDITION) == base
    assert prompts.build_voice_prefix(p, DIGEST, 3, 1600) == base
    assert "IDENTITY:\n" in base and "STYLE RULES:\n" in base and "SAMPLES OF HOW YOU WRITE:\n" in base
    assert "BOUNDARIES (refuse or deflect):\n" in base and "ABOUT YOU (digest):\n" + DIGEST in base
    assert samples_block(base) == "\n".join(f"- {s.strip()}" for s in p.samples[:3])


@pytest.mark.parametrize("who", ["ari", "mara"])
def test_prefix_demographic_is_identity_only(who, request):
    p = request.getfixturevalue(who)
    d = prompts.build_voice_prefix(p, DIGEST, condition="demographic")
    assert d == "IDENTITY:\n" + p.identity.strip()
    for tag in ("STYLE RULES:", "SAMPLES OF HOW YOU WRITE:", "BOUNDARIES", "ABOUT YOU"):
        assert tag not in d
    assert DIGEST not in d and p.style_rules.strip() not in d
    assert prompts.build_voice_prefix(p, "", condition="demographic") == d


def test_prefix_without_digest_and_with_truncation(ari):
    no_digest = prompts.build_voice_prefix(ari, "")
    assert no_digest == full_prefix(ari, "")
    assert "ABOUT YOU" not in no_digest
    long = "x" * 3000
    assert prompts.build_voice_prefix(ari, long).endswith("ABOUT YOU (digest):\n" + "x" * 1600)
    assert prompts.build_voice_prefix(ari, long, digest_chars=100).endswith("ABOUT YOU (digest):\n" + "x" * 100)
    five = samples_block(prompts.build_voice_prefix(ari, DIGEST, n_samples=5))
    assert five == "\n".join(f"- {s.strip()}" for s in ari.samples[:5]) and five.count("\n- ") == 4
    assert prompts.build_voice_prefix(ari, DIGEST, condition="Persona") == prompts.build_voice_prefix(ari, DIGEST)
    assert prompts.build_voice_prefix(ari, DIGEST, condition=" INTERVIEW ") == prompts.build_voice_prefix(ari, DIGEST)


def test_prefix_rejects_unknown_condition(ari):
    with pytest.raises(ValueError, match="unknown condition"):
        prompts.build_voice_prefix(ari, DIGEST, condition="ablation")
    with pytest.raises(ValueError):
        prompts.build_voice_system(ari, DIGEST, [], condition="nope")
    # an empty or None condition falls back to the default (interview)
    assert prompts.build_voice_system(ari, DIGEST, CHUNKS, condition="") == prompts.build_voice_system(ari, DIGEST, CHUNKS)
    assert prompts.build_voice_prefix(ari, DIGEST, condition=None) == prompts.build_voice_prefix(ari, DIGEST)


# ---------------------------------------------------------------------------
# build_voice_system
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("who", ["ari", "mara"])
def test_system_interview_is_byte_identical_to_the_three_arg_call(who, request):
    p = request.getfixturevalue(who)
    three = prompts.build_voice_system(p, DIGEST, CHUNKS)
    assert prompts.build_voice_system(p, DIGEST, CHUNKS, condition="interview") == three
    assert prompts.build_voice_system(p, DIGEST, CHUNKS, condition=prompts.DEFAULT_CONDITION) == three
    assert three == (prompts.VOICE_SYSTEM(p.name) + "\n\n" + full_prefix(p, DIGEST) + "\n\nCONTEXT:\n"
                     + context_block(CHUNKS))
    assert three.count("CONTEXT:") == 1
    assert "[1] (D-01: Bought the boring phone) Situation: needed a phone. Choice: the boring one." in three
    assert "[3] (Interview/T-004a) Q: what did you learn?" in three   # empty title falls back to the id
    assert three.index("CONTEXT:") > three.index(DIGEST)


def test_system_interview_with_nothing_retrieved(ari):
    s = prompts.build_voice_system(ari, DIGEST, [])
    assert s.endswith("\n\nCONTEXT:\n(nothing retrieved)")
    assert s.startswith(prompts.VOICE_SYSTEM("Ari"))


@pytest.mark.parametrize("condition", ["demographic", "persona"])
@pytest.mark.parametrize("who", ["ari", "mara"])
def test_system_non_interview_has_no_context_block(who, condition, request):
    p = request.getfixturevalue(who)
    s = prompts.build_voice_system(p, DIGEST, CHUNKS, condition=condition)
    assert s == prompts.VOICE_SYSTEM_NO_CONTEXT(p.name) + "\n\n" + prompts.build_voice_prefix(p, DIGEST, condition=condition)
    assert s.startswith(prompts.VOICE_SYSTEM_NO_CONTEXT(p.name))
    assert "CONTEXT:" not in s and "(nothing retrieved)" not in s
    for c in CHUNKS:
        assert c["text"] not in s, "context chunks are ignored outside the interview condition"
    assert prompts.VOICE_SYSTEM(p.name) not in s
    # context is ignored entirely: the same string with and without chunks
    assert prompts.build_voice_system(p, DIGEST, [], condition=condition) == s


def test_system_persona_keeps_digest_and_style_but_demographic_drops_them(ari):
    persona = prompts.build_voice_system(ari, DIGEST, CHUNKS, condition="persona")
    demo = prompts.build_voice_system(ari, DIGEST, CHUNKS, condition="demographic")
    assert DIGEST in persona and "STYLE RULES:" in persona and ari.boundaries.strip() in persona
    assert DIGEST not in demo and "STYLE RULES:" not in demo and "BOUNDARIES" not in demo
    assert demo == prompts.VOICE_SYSTEM_NO_CONTEXT("Ari") + "\n\nIDENTITY:\n" + ari.identity.strip()
    assert len(demo) < len(persona) < len(prompts.build_voice_system(ari, DIGEST, CHUNKS))


def test_phase_one_prompt_constants_unchanged():
    assert prompts.ROUTER_SCHEMA["properties"]["intent"]["enum"] == ["about_me", "decide", "tool", "image", "smalltalk"]
    assert set(prompts.CHECKER_SCHEMA["required"]) == {"consistent", "unsupported_claims", "contradictions"}
    assert set(prompts.JUDGE_SCHEMA["required"]) == {"factual_agreement", "voice_fidelity", "no_roleplay_artifacts",
                                                     "overall", "note"}
    assert prompts.B1_SCHEMA["properties"]["verdict"]["enum"] == ["yes", "no"]
    assert prompts.B2_SCHEMA["properties"]["choice"]["enum"] == ["A", "B"]
    assert [t["function"]["name"] for t in prompts.AGENT_TOOLS] == ["search_profile", "get_datetime", "calculator",
                                                                    "draft_message"]
    assert prompts.VISION_PROMPT == "Describe this image factually in 5 sentences."
    assert "JSON only" in prompts.ROUTER_SYSTEM and "digest" in prompts.DIGEST_SYSTEM


def test_decide_schemas_cap_their_arrays():
    """The grammar Ollama builds from the schema must close the arrays: without maxItems qwen3-8b-8k loops inside
    cited_decisions until num_predict (seen live under the interview condition with the reflection chunks)."""
    for schema in (prompts.B1_SCHEMA, prompts.B2_SCHEMA):
        props = schema["properties"]
        assert props["reasons"]["maxItems"] == prompts.DECIDE_MAX_REASONS >= 3
        assert props["cited_decisions"]["maxItems"] == prompts.DECIDE_MAX_CITED >= 3
        assert props["reasons"]["items"] == {"type": "string"}
        assert props["cited_decisions"]["items"] == {"type": "string"}
    assert set(prompts.B1_SCHEMA["required"]) == {"verdict", "confidence", "reasons", "cited_decisions",
                                                  "what_would_change_my_mind"}
    assert set(prompts.B2_SCHEMA["required"]) == {"choice", "confidence", "reasons", "cited_decisions", "tradeoff"}
