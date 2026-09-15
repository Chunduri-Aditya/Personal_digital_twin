"""System prompts, JSON schemas and voice post-processing for the twin."""
from __future__ import annotations

import re

# ---- conditions (docs/PLAN_UNIFIED.md 3.4) --------------------------------------
# demographic: identity only, no digest, no retrieval; persona: static prefix with digest, no retrieval;
# interview: the full prompt with retrieved CONTEXT (phase-1 behaviour, byte-identical).
CONDITIONS = ("demographic", "persona", "interview")
DEFAULT_CONDITION = "interview"


def _condition(condition: str | None) -> str:
    c = (condition or DEFAULT_CONDITION).strip().lower()
    if c not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected one of {CONDITIONS}")
    return c


def VOICE_SYSTEM(name: str) -> str:
    """Voice system prompt. Always send a system message to Stheno, and mandatorily to the Q8_0
    Stheno on Ollama (`stheno_q8`): its built-in default contains unfilled {{char}}/{{user}} placeholders."""
    return (
        f"You are {name}, replying as yourself in a text chat. Output only your message: no asterisks, "
        "actions, narration, stage directions, quotes, or character/AI mentions. First person. Only state "
        "facts about yourself that appear in CONTEXT; otherwise say you don't remember."
    )


def VOICE_SYSTEM_NO_CONTEXT(name: str) -> str:
    """Voice system prompt for the demographic and persona conditions: no CONTEXT block follows, so the
    grounding sentence points at the static prefix instead of CONTEXT."""
    return (
        f"You are {name}, replying as yourself in a text chat. Output only your message: no asterisks, "
        "actions, narration, stage directions, quotes, or character/AI mentions. First person. Only state "
        "facts about yourself that appear above; otherwise say you don't remember."
    )


def build_voice_prefix(profile, digest: str, n_samples: int = 3, digest_chars: int = 1600,
                       condition: str = DEFAULT_CONDITION) -> str:
    """Static prefix. 'demographic' returns the IDENTITY block only; 'persona' and 'interview' return the full
    prefix (identity, style rules, samples, boundaries, digest), byte-identical to phase 1."""
    condition = _condition(condition)
    parts = []
    if profile.identity:
        parts.append("IDENTITY:\n" + profile.identity.strip())
    if condition == "demographic":
        return "\n\n".join(parts)
    if profile.style_rules:
        parts.append("STYLE RULES:\n" + profile.style_rules.strip())
    samples = [s for s in profile.samples if s.strip()][:n_samples]
    if samples:
        parts.append("SAMPLES OF HOW YOU WRITE:\n" + "\n".join(f"- {s.strip()}" for s in samples))
    if profile.boundaries:
        parts.append("BOUNDARIES (refuse or deflect):\n" + profile.boundaries.strip())
    if digest:
        parts.append("ABOUT YOU (digest):\n" + digest.strip()[:digest_chars])
    return "\n\n".join(parts)


def build_voice_system(profile, digest: str, context_chunks: list[dict],
                       condition: str = DEFAULT_CONDITION) -> str:
    """'interview': VOICE_SYSTEM + prefix + CONTEXT (byte-identical to phase 1). 'demographic' and 'persona':
    VOICE_SYSTEM_NO_CONTEXT + the condition's prefix, with no CONTEXT block (context_chunks ignored)."""
    condition = _condition(condition)
    if condition != "interview":
        return VOICE_SYSTEM_NO_CONTEXT(profile.name) + "\n\n" + build_voice_prefix(profile, digest, condition=condition)
    lines = []
    for i, c in enumerate(context_chunks, 1):
        title = c.get("title") or c.get("id", "")
        lines.append(f"[{i}] ({title}) {c.get('text', '').strip()}")
    ctx = "\n".join(lines) if lines else "(nothing retrieved)"
    return VOICE_SYSTEM(profile.name) + "\n\n" + build_voice_prefix(profile, digest) + "\n\nCONTEXT:\n" + ctx


_ACTION_RE = re.compile(r"\*[^*\n]{1,200}\*")
_AI_TAIL_RE = re.compile(r"\n*\(?\s*(as an ai|as a language model|as an ai language model)[^\n]*$", re.I)


def _strip_quotes(t: str) -> str:
    for a, b in (('"', '"'), ("“", "”"), ("'", "'")):
        if len(t) >= 2 and t.startswith(a) and t.endswith(b):
            t = t[1:-1].strip()
    return t


def postprocess_voice(text: str, name: str) -> str:
    t = (text or "").strip()
    t = _ACTION_RE.sub("", t)
    t = _strip_quotes(t.strip())
    if name:
        t = re.sub(r"^\s*" + re.escape(name) + r"\s*:\s*", "", t, flags=re.I)
        t = re.sub(r"(?m)^" + re.escape(name) + r"\s*:\s*", "", t, flags=re.I)
    t = _strip_quotes(t.strip())
    t = _AI_TAIL_RE.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# ---- router ------------------------------------------------------------------
ROUTER_SYSTEM = (
    "Classify the user's latest message into exactly one intent and answer with JSON only.\n"
    "about_me: asks about the person, their opinions, history, preferences, or what they would say.\n"
    "decide: asks for a yes/no call or to pick between options.\n"
    "tool: needs the current time, a calculation, or drafting a message to someone.\n"
    "image: refers to a picture or asks to look at something visual.\n"
    "smalltalk: greetings, thanks, chit-chat with no factual content.\n"
    'Output: {"intent": "<one of about_me|decide|tool|image|smalltalk>"}'
)
ROUTER_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": ["about_me", "decide", "tool", "image", "smalltalk"]}},
    "required": ["intent"],
}

REWRITE_SYSTEM = (
    "Rewrite the user's latest follow-up message as one standalone search query that makes sense without "
    "the conversation history. Keep the person's names and topic. Output only the query, nothing else."
)


# ---- decide ------------------------------------------------------------------
def DECIDE_SYSTEM(name: str) -> str:
    return (
        f"You predict how {name} would decide, using ONLY the profile CONTEXT provided (past decisions, values, "
        "preferences, boundaries, digest). Reason the way they reason. Cite past decisions by their D-NN id in "
        "cited_decisions. Confidence is a number from 0 to 1. Answer with JSON matching the schema and nothing else."
    )


# The array caps are part of the grammar Ollama builds from the schema: without them qwen3-8b-8k (temperature
# 0.2) can loop inside `cited_decisions` ("D-15", "D-12", "D-08", ... until num_predict) once the interview
# context carries the reflection chunks (seen live, 2026-09-14: 5 of 6 attempts); with the caps the grammar
# closes the array so the object completes.
DECIDE_MAX_REASONS = 6
DECIDE_MAX_CITED = 8

B1_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["yes", "no"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": DECIDE_MAX_REASONS},
        "cited_decisions": {"type": "array", "items": {"type": "string"}, "maxItems": DECIDE_MAX_CITED},
        "what_would_change_my_mind": {"type": "string"},
    },
    "required": ["verdict", "confidence", "reasons", "cited_decisions", "what_would_change_my_mind"],
}

B2_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": ["A", "B"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": DECIDE_MAX_REASONS},
        "cited_decisions": {"type": "array", "items": {"type": "string"}, "maxItems": DECIDE_MAX_CITED},
        "tradeoff": {"type": "string"},
    },
    "required": ["choice", "confidence", "reasons", "cited_decisions", "tradeoff"],
}


# ---- checker -----------------------------------------------------------------
CHECKER_SYSTEM = (
    "You are a strict fact checker. Compare the REPLY against the CONTEXT chunks. A claim about the person is "
    "unsupported if the CONTEXT does not state it; it is a contradiction if the CONTEXT says otherwise. Ignore "
    "tone and opinions that are consistent with the context. Answer with JSON only."
)
CHECKER_SCHEMA = {
    "type": "object",
    "properties": {
        "consistent": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["consistent", "unsupported_claims", "contradictions"],
}


# ---- judge -------------------------------------------------------------------
JUDGE_SYSTEM = (
    "You grade an anonymised candidate reply that tries to answer a question the way a specific person would. "
    "You get the GOLD answer (how the person really answers), the person's STYLE RULES, and the CANDIDATE. "
    "Score 1-5 each: factual_agreement (matches the gold facts), voice_fidelity (matches the style rules and "
    "gold phrasing), no_roleplay_artifacts (5 = no asterisks, actions, narration, name prefixes, AI mentions), "
    "overall. Add a one-sentence note. Answer with JSON only."
)
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "factual_agreement": {"type": "integer", "minimum": 1, "maximum": 5},
        "voice_fidelity": {"type": "integer", "minimum": 1, "maximum": 5},
        "no_roleplay_artifacts": {"type": "integer", "minimum": 1, "maximum": 5},
        "overall": {"type": "integer", "minimum": 1, "maximum": 5},
        "note": {"type": "string"},
    },
    "required": ["factual_agreement", "voice_fidelity", "no_roleplay_artifacts", "overall", "note"],
}

VISION_PROMPT = "Describe this image factually in 5 sentences."


# ---- agent -------------------------------------------------------------------
def AGENT_SYSTEM(name: str) -> str:
    return (
        f"You are a tool-using assistant acting on behalf of {name}. A request with several parts needs one tool "
        f"call per part: the current time or date -> get_datetime; any arithmetic (including percentages) -> "
        f"calculator; facts about {name} -> search_profile; a message to someone -> draft_message (call it first, "
        "then write the draft using the style rules and samples it returns). You may request several tools in one "
        "turn. Keep calling tools until every part of the request is covered (for example get_datetime AND "
        "calculator for \"what time is it and what is 17% of 240\"), then give one short final answer that "
        "includes every result. Never state a time, date or computed number without the matching tool result, and "
        "never invent facts about the person that search_profile did not return."
    )


AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_profile",
            "description": "Search the person's profile (identity, voice, values, preferences, decisions, goals) for relevant passages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."},
                    "k": {"type": "integer", "description": "Number of passages to return (1-8).", "default": 4},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_datetime",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate an arithmetic expression such as '0.17 * 240' or '(3 + 4) / 2'.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Arithmetic expression using + - * / ** % and parentheses."}},
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": "Get the person's style rules and sample messages so you can draft a message in their voice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_role": {"type": "string", "description": "Who the message is for, by role, e.g. 'my manager'."},
                    "intent": {"type": "string", "description": "What the message should achieve."},
                },
                "required": ["recipient_role", "intent"],
            },
        },
    },
]


# ---- digest ------------------------------------------------------------------
DIGEST_SYSTEM = (
    "You will read one person's complete profile. Write a plain-text digest of at most 400 tokens that a chat "
    "model can use to speak as them: who they are, how they talk, key values, decision patterns (how they tend "
    "to choose and what they weigh), and preferences. Third person, concrete, no headings, no markdown, no "
    "bullet symbols, no preamble. Do not invent anything that is not in the profile."
)
