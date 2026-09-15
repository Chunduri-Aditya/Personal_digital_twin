"""Act tab: hermes3 native tool calling (search_profile, get_datetime, calculator, draft_message).

Every model call runs inside ``gpu.MANAGER.session``. Clients, the index and the GPU manager are
reached through their module objects (``clients.ollama.chat``, ``index.search_chunks``,
``gpu.MANAGER.session``) so tests can monkeypatch them with fakes.
"""
from __future__ import annotations

import ast
import datetime as _dt
import inspect
import json
import operator
import re
import sys
from typing import Any, Callable

from twin import audit, clients, gpu, index, prompts
from twin.pipelines import digest, voice
from twin.profile import Profile, load_profile

AGENT_KEY = "hermes3"
VOICE_KEY = "stheno_q4"
SEARCH_INDEX = "lms_nomic"      # LM Studio nomic: embedding here does not evict hermes3 on Ollama
TAB = "act"
NO_ANSWER = "I could not produce an answer."
DRAFT_INSTRUCTION = ("Write the message in this voice, 1-4 sentences, no greeting to yourself, "
                     "sign-off optional.")
# draft_message's own next_step asks for a search_profile lookup first. Once search_profile or an earlier
# draft_message has already returned, _agent_loop swaps in this write-now step instead: the unchanged step sent
# hermes3 back into the lookup until max_steps (demo rehearsal 2026-09-14: 0 of 6 drafts; docs/DEMO.md section 9).
DRAFT_WRITE_NOW = ("You already have the style rules, the samples and the profile facts from the earlier tool "
                   "results. Do not call any more tools: reply now with only the message text, 1-4 sentences, in "
                   "this voice. Sign as {name} if you sign.")
# Requests that ask for the time/date must show a get_datetime call before the final answer; when hermes3
# answers without one, the loop sends one nudge and allows one extra step (stage 4(a) of the plan).
_TIME_REQUEST_RE = re.compile(r"\b(time|date|today|now|day)\b", re.I)
DATETIME_NUDGE = "You did not call get_datetime; call it now, then answer every part of the request."

# ---- profile cache -----------------------------------------------------------
_PROFILE: Profile | None = None


def _profile() -> Profile:
    """Return the cached profile, loading it on first use."""
    global _PROFILE
    if _PROFILE is None:
        _PROFILE = load_profile()
    return _PROFILE


def reload_profile() -> Profile:
    """Drop the cached profile and load it again (after the profile file changes)."""
    global _PROFILE
    _PROFILE = None
    return _profile()


# ---- safe calculator ---------------------------------------------------------
_MAX_EXPR_CHARS = 500
_MAX_EXPONENT = 1000
_MAX_ABS = 1e100          # operand magnitude cap (keeps 1000-exponent powers cheap)


def _pow(a, b):
    """Power with a capped exponent so the evaluator can never build a giant integer."""
    if abs(b) > _MAX_EXPONENT:
        raise ValueError(f"exponent too large (max {_MAX_EXPONENT})")
    return a ** b


_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _pow,
}
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _check_operand(v: Any) -> Any:
    """Reject non-numeric or oversized intermediate values."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("only int and float values are allowed")
    if abs(v) > _MAX_ABS:
        raise ValueError(f"operand too large (max magnitude {_MAX_ABS:g})")
    return v


def _eval_node(node: ast.AST) -> Any:
    """Recursively evaluate a whitelisted arithmetic AST node."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"unsupported literal {node.value!r}; only numbers are allowed")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_check_operand(_eval_node(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _check_operand(_eval_node(node.left))
        right = _check_operand(_eval_node(node.right))
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Name):
        raise ValueError(f"names are not allowed ({node.id!r})")
    if isinstance(node, ast.Call):
        raise ValueError("function calls are not allowed")
    if isinstance(node, ast.Attribute):
        raise ValueError("attribute access is not allowed")
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def safe_calc(expression: str) -> float:
    """Evaluate an arithmetic expression (+ - * / // % ** and parentheses) without eval/exec.

    Uses ``ast.parse(mode="eval")`` and walks a whitelist of node types. Names, calls, attributes,
    strings and everything else raise ValueError. Exponents are capped at 1000 and operand magnitude
    at 1e100. The result is rounded to 12 decimal places so 0.17 * 240 comes back as 40.8.
    """
    if not isinstance(expression, str):
        raise ValueError("expression must be a string")
    expr = expression.strip()
    if not expr:
        raise ValueError("expression is empty")
    if len(expr) > _MAX_EXPR_CHARS:
        raise ValueError(f"expression too long (max {_MAX_EXPR_CHARS} characters)")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        raise ValueError(f"could not parse expression: {e}") from None
    try:
        value = _eval_node(tree)
    except ZeroDivisionError:
        raise ValueError("division by zero") from None
    except RecursionError:
        raise ValueError("expression is nested too deeply") from None
    except (OverflowError, MemoryError):
        raise ValueError("result is too large") from None
    if isinstance(value, complex) or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("result is not a real number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError("result is too large") from None
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("result is not finite")
    return round(result, 12)


# ---- tools -------------------------------------------------------------------
def _clamp_k(k: Any, default: int = 4) -> int:
    """Coerce k to an int in 1..8, falling back to the default on garbage."""
    try:
        n = int(k)
    except (TypeError, ValueError):
        n = default
    return min(max(n, 1), 8)


def search_profile(query: str, k: int = 4) -> dict:
    """Tool: search the profile with the LM Studio nomic index (does not evict hermes3)."""
    q = str(query or "").strip()
    if not q:
        return {"results": [], "error": "query is empty"}
    chunks = index.search_chunks(SEARCH_INDEX, q, k=_clamp_k(k), tab=TAB)
    results = [
        {
            "id": c.get("id", ""),
            "title": c.get("title", ""),
            "text": c.get("text", ""),
            "score": round(float(c.get("score", 0.0)), 4),
        }
        for c in chunks
    ]
    return {"results": results}


def get_datetime() -> dict:
    """Tool: local date and time as ISO 8601 with seconds, weekday name and timezone name."""
    now = _dt.datetime.now().astimezone()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
        "timezone": now.tzname() or "",
    }


_PERCENT_OF_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*of\b", re.I)      # "17% of 240" -> "(17/100)*240"
_PERCENT_END_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%(?=\s*(?:$|\)|[-+*/]))")  # "17%" / "17% + 1" -> "(17/100)"; "17 % 5" stays modulo


def _normalise_expression(expression: str) -> str:
    """Turn the natural-language arithmetic hermes3 tends to send ("17% of 240", "2^8", "3 × 4") into what
    safe_calc accepts. Binary modulo ("17 % 5") is left alone."""
    e = expression.replace("×", "*").replace("÷", "/").replace("^", "**")
    e = _PERCENT_OF_RE.sub(lambda m: f"({m.group(1)}/100)*", e)
    e = _PERCENT_END_RE.sub(lambda m: f"({m.group(1)}/100)", e)
    return e


def calculator(expression: str) -> dict:
    """Tool: evaluate an arithmetic expression with safe_calc; errors come back as a message."""
    if isinstance(expression, (int, float)) and not isinstance(expression, bool):
        expression = str(expression)
    try:
        expr = _normalise_expression(expression) if isinstance(expression, str) else expression
        return {"expression": expression, "result": safe_calc(expr)}
    except ValueError as e:
        return {"expression": expression, "error": str(e)}


def draft_message(recipient_role: str, intent: str) -> dict:
    """Tool: hand back the style rules and two samples so the model drafts in the person's voice."""
    prof = _profile()
    role = str(recipient_role or "")
    return {
        "recipient_role": role,
        "intent": str(intent or ""),
        "sender_name": prof.name,
        "style_rules": prof.style_rules,
        "samples": list(prof.samples[:2]),
        "instruction": DRAFT_INSTRUCTION,
        "next_step": (f"Before writing, call search_profile once with query \"how I talk to {role or 'this person'}\" "
                      f"to get facts about the recipient, then write the draft. Sign as {prof.name} if you sign."),
    }


TOOL_IMPL: dict[str, Callable[..., dict]] = {
    "search_profile": search_profile,
    "get_datetime": get_datetime,
    "calculator": calculator,
    "draft_message": draft_message,
}


# ---- agent loop --------------------------------------------------------------
def _dumps(obj: Any) -> str:
    """JSON-encode a tool result; non-serialisable values are stringified."""
    return json.dumps(obj, ensure_ascii=False, default=str)


def _parse_args(raw: Any) -> dict:
    """Normalise tool-call arguments to a dict (JSON strings are parsed; anything else -> {})."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _run_tool(name: str, args: dict) -> dict:
    """Dispatch one tool call; unknown names and exceptions become error dicts for the model."""
    fn = TOOL_IMPL.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        params = inspect.signature(fn).parameters
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            args = {k: v for k, v in args.items() if k in params}   # drop unknown kwargs
        return fn(**args)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _hermes_chat(messages: list[dict]) -> tuple[dict, int]:
    """One hermes3 tool-calling request; retries once when neither content nor tool_calls come back."""
    msg: dict = {}
    retries = 0
    for attempt in range(2):
        resp = clients.ollama.chat(
            AGENT_KEY, messages, tools=prompts.AGENT_TOOLS, options={"temperature": 0.3},
            num_predict=500, tab=TAB,
        )
        msg = dict((resp or {}).get("message") or {})
        if (msg.get("content") or "").strip() or msg.get("tool_calls"):
            break
        retries = attempt + 1
    return msg, min(retries, 1)


def _assistant_message(msg: dict) -> dict:
    """Copy of the model's message in the shape /api/chat accepts back (role, content, tool_calls)."""
    out = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        # hermes3 template: `{{ if .Content }}{{ .Content }}{{- else if .ToolCalls }}<tool_call>...`
        # so non-empty content would hide the tool call from the re-rendered history.
        out["content"] = ""
        out["tool_calls"] = msg["tool_calls"]
    return out


def _summarise_results(entries: list[dict]) -> str:
    """Plain-text summary of tool results, used when the step limit is hit mid-loop."""
    lines = []
    for e in entries:
        lines.append(f"- {e['tool']}({_dumps(e['args'])}) -> {_dumps(e['result'])}")
    return "\n".join(lines) if lines else "(no tool results)"


def _search_chunk_ids(trace: list[dict]) -> list[str]:
    """Ids of every chunk a search_profile call returned during the run, in order, de-duplicated."""
    out: list[str] = []
    for e in trace:
        if e.get("kind") != "tool" or e.get("tool") != "search_profile":
            continue
        for r in ((e.get("result") or {}).get("results") or []):
            cid = str((r or {}).get("id") or "")
            if cid and cid not in out:
                out.append(cid)
    return out


def _audit_run(text: str, out: dict | None) -> None:
    """One audit line per request (docs/PLAN_UNIFIED.md 3.6): the request text is reduced to its sha256; chunk
    ids come from the search_profile results; ok is False when the loop raised. Never raises."""
    try:
        trace = (out or {}).get("trace") or []
        audit.record(TAB, prompts.DEFAULT_CONDITION, text, _search_chunk_ids(trace), [AGENT_KEY], ok=out is not None,
                     extra={"steps": (out or {}).get("steps", 0)})
    except Exception as e:  # noqa: BLE001  (the audit line must never break the tab)
        print(f"[act] audit.record failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


def run_agent(user_message: str, max_steps: int = 5) -> dict:
    """Run the hermes3 tool loop for one request; returns {"answer", "trace", "steps"}. Writes one audit line
    (tab "act", condition "interview") when the loop finishes or raises; an empty request writes none."""
    text = (user_message or "").strip()
    if not text:
        return {"answer": "Type a request first.", "trace": [], "steps": 0}
    out: dict | None = None
    try:
        out = _agent_loop(text, max_steps)
        return out
    finally:
        _audit_run(text, out)


def _agent_loop(text: str, max_steps: int) -> dict:
    """The hermes3 tool loop itself (one manager session); see run_agent."""
    prof = _profile()
    # The hermes3 Ollama template renders the system slot as tool boilerplate whenever tools are
    # sent (`{{- if .Tools }}...{{- else if .System }}{{ .System }}`), so a role:system message is
    # silently dropped. The instructions therefore ride in the first user turn; the system message
    # is kept only for clients/templates that do honour it.
    instruction = prompts.AGENT_SYSTEM(prof.name)
    messages: list[dict] = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": instruction + "\n\nREQUEST:\n" + text},
    ]
    trace: list[dict] = []
    steps = 0
    last_results: list[dict] = []
    wants_time = bool(_TIME_REQUEST_RE.search(text))
    nudged = False
    limit = max(1, int(max_steps))
    with gpu.MANAGER.session(AGENT_KEY, tab=TAB):
        step = 0
        while step < limit:
            step += 1
            steps = step
            msg, retries = _hermes_chat(messages)
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []
            entry = {"step": step, "kind": "assistant", "content": content,
                     "tool_calls": [{"name": (c.get("function") or {}).get("name", ""),
                                     "arguments": (c.get("function") or {}).get("arguments")}
                                    for c in tool_calls]}
            if retries:
                entry["retries"] = retries
            trace.append(entry)
            messages.append(_assistant_message(msg))
            if not tool_calls:
                used_datetime = any(e.get("kind") == "tool" and e.get("tool") == "get_datetime" for e in trace)
                if wants_time and not used_datetime and not nudged:
                    nudged = True
                    limit += 1
                    messages.append({"role": "user", "content": DATETIME_NUDGE})
                    trace.append({"step": step, "kind": "note", "note": "nudge: " + DATETIME_NUDGE})
                    continue
                answer = content if content else NO_ANSWER
                return {"answer": answer, "trace": trace, "steps": steps}
            last_results = []
            for call in tool_calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                args = _parse_args(fn.get("arguments"))
                result = _run_tool(name, args)
                if (name == "draft_message" and isinstance(result, dict) and "next_step" in result
                        and any(e.get("kind") == "tool" and e.get("tool") in ("search_profile", "draft_message")
                                for e in trace)):
                    result["next_step"] = DRAFT_WRITE_NOW.format(name=prof.name)
                messages.append({"role": "tool", "tool_name": name, "content": _dumps(result)})
                tool_entry = {"step": step, "kind": "tool", "tool": name, "args": args, "result": result}
                trace.append(tool_entry)
                last_results.append(tool_entry)
    note = f"Reached the step limit ({steps}) with tool calls still pending; answering from the last tool results."
    trace.append({"step": steps, "kind": "note", "note": note})
    answer = f"I ran out of steps before writing a final answer. Last tool results:\n{_summarise_results(last_results)}"
    return {"answer": answer, "trace": trace, "steps": steps}


# ---- polish with Stheno ------------------------------------------------------
def polish(text: str) -> str:
    """Rewrite a draft in the twin's voice with LM Studio Stheno (Q4), post-processed."""
    draft = (text or "").strip()
    if not draft:
        return ""
    prof = _profile()
    system = prompts.VOICE_SYSTEM(prof.name) + "\n\n" + prompts.build_voice_prefix(prof, digest.load_digest())
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Rewrite this draft in your own voice, same meaning, same length or shorter:\n\n" + draft},
    ]
    # Stheno Q4 on LM Studio (one retry on an empty reply); llama3.2:3b when LM Studio is down.
    raw, _voice_key = voice.reply_in_voice(messages, max_tokens=250, tab=TAB, temperature=1.0)
    out = prompts.postprocess_voice(raw or "", prof.name)
    return out or draft


# ---- trace rendering ---------------------------------------------------------
def _code_block(obj: Any) -> str:
    """Pretty JSON inside a fenced block for the markdown trace."""
    return "```json\n" + json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n```"


def format_trace_markdown(trace: list[dict]) -> str:
    """Render a run_agent trace as markdown for the UI accordion."""
    if not trace:
        return "_(no trace)_"
    parts: list[str] = []
    for e in trace:
        step = e.get("step", "?")
        kind = e.get("kind") or ("tool" if "tool" in e else "assistant")
        if kind == "tool":
            parts.append(f"**Step {step} - tool `{e.get('tool', '')}`**\n\nArguments:\n{_code_block(e.get('args', {}))}\n\n"
                         f"Result:\n{_code_block(e.get('result', {}))}")
        elif kind == "note":
            parts.append(f"**Step {step} - note**\n\n_{e.get('note', '')}_")
        else:
            calls = e.get("tool_calls") or []
            head = f"**Step {step} - assistant**"
            if e.get("retries"):
                head += f" (retried {e['retries']}x after an empty reply)"
            body = e.get("content") or ""
            lines = [head]
            if body:
                lines.append(body)
            if calls:
                lines.append("Requested tools: " + ", ".join(
                    f"`{c.get('name', '')}({_dumps(c.get('arguments') or {})})`" for c in calls))
            parts.append("\n\n".join(lines))
    return "\n\n---\n\n".join(parts)
