"""Ask tab: streaming chat with the twin (``/ask``, ``/ask_clear``; the Enter-key submit is private). The
condition dropdown (docs/PLAN_UNIFIED.md 3.4) is the LAST input of /ask, so phase-1 positional calls still work.

Layout (docs/PLAN_FINISH.md P4 and the Nocturne sheet docs/design/tokens.md section 5, styled by static/tabs/ask.css
on the frame contract in static/twin.css): ``#ask-main`` puts the conversation ``#ask-conversation`` beside the
evidence rail ``#ask-rail``. The conversation holds the transcript sheet ``#ask-chat`` (the twin's replies beside the
owner's monogram, your messages on the accent tint, an empty-chat placeholder) and one composer panel
``#ask-composer`` (Message with Send as the only primary action and a quiet Clear, then the settings row). The rail
holds its empty state, the hint line, the checker panel and the Trace panel. Labels, placeholders, defaults,
api_names, queues, inputs, outputs and every handler return are unchanged."""
from __future__ import annotations

import base64
import html
import time

import gradio as gr

from twin import prompts
from twin.gpu import MANAGER
from twin.pipelines import ask
from twin.ui import state

TOKEN_YIELD_INTERVAL_S = 0.08      # throttle chatbot updates while tokens stream
CONDITION_CHOICES = [(c, c) for c in prompts.CONDITIONS]
# The evidence rail's empty state; static/tabs/ask.css hides it once the Trace lists a step.
RAIL_EMPTY = ("Each reply's evidence shows here: the Trace of its steps, the consistency check when it is on, and a "
              "hint when the message reads like a job for Act.")

# The monogram glyph for the chat avatar. Deliberately colourless (default black on transparent): an <img> cannot
# read CSS custom properties, so static/tabs/ask.css paints it in --twin-accent on --twin-accent-soft (a drop-shadow
# copy of the glyph), which keeps the avatar on the tokens in both themes. Web fonts are not visible inside an SVG
# image, so the family list falls back to a local sans.
_AVATAR_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
               '<text x="32" y="45" text-anchor="middle" font-family="Inter, \'Segoe UI\', system-ui, sans-serif" '
               'font-size="34" font-weight="600">{initial}</text></svg>')


def _text_of(content) -> str:
    """Text of a chatbot message content: str, a {"type": "text"} part, or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text") or "" if content.get("type", "text") == "text" else ""
    if isinstance(content, (list, tuple)):
        return "".join(_text_of(c) for c in content)
    return ""


def _history_as_text(history) -> list[dict]:
    """Chatbot value -> [{"role", "content": str}] of non-empty user/assistant turns (Gradio 6 hands the
    content back as a list of typed parts, which twin.pipelines.ask would otherwise drop)."""
    out = []
    for m in history or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        text = _text_of(m.get("content")).strip()
        if role in ("user", "assistant") and text:
            out.append({"role": role, "content": text})
    return out


def _snapshot(chat: list[dict]) -> list[dict]:
    """Copy of the chat list so each yielded value is independent of later token appends."""
    return [dict(m) for m in chat]


def _checker_markdown(ev: dict) -> str:
    """Badge text for a checker event."""
    data = ev.get("data") or {}
    summary = ev.get("text") or ""
    verdict = data.get("consistent")
    if verdict is None:
        head = f"**Checker (qwen2.5): unavailable** — {summary}"
    elif verdict and not data.get("unsupported_claims") and not data.get("contradictions"):
        head = f"**Checker (qwen2.5): CONSISTENT** — {summary}"
    else:
        head = f"**Checker (qwen2.5): {'CONSISTENT' if verdict else 'INCONSISTENT'}** — {summary}"
    parts = [head]
    for label, key in (("Unsupported claims", "unsupported_claims"), ("Contradictions", "contradictions")):
        items = data.get(key) or []
        if items:
            parts.append(f"{label}:\n" + "\n".join(f"- {x}" for x in items))
    return "\n\n".join(parts)


def _hint_markdown(hints: list[str]) -> str:
    """Hint line under the chat."""
    return "\n\n".join(f"_Hint: {h}_" for h in hints)


def ask_send(message, history, use_q8, temperature, use_checker, condition=prompts.DEFAULT_CONDITION):
    """Generator: stream one Ask turn into the chatbot; yields (chatbot, trace_md, checker_md, hint_md, textbox).
    `condition` (last, optional) is one of prompts.CONDITIONS; interview is the phase-1 turn."""
    turns = _history_as_text(history)
    message = (message or "").strip()
    if not message:
        yield turns, "_(empty message)_", "", "", ""
        return
    chat = turns + [{"role": "user", "content": message}, {"role": "assistant", "content": ""}]
    trace: list[str] = []
    hints: list[str] = []
    checker_md = ""
    pieces: list[str] = []
    yield chat, state._trace_markdown(trace), checker_md, _hint_markdown(hints), ""
    # The heartbeat and the tab pre-warm follow the voice actually in use: with Q8 on they must not evict
    # fluffy/l3-8b-stheno-v3.2:q8_0 to re-warm the Q4 the user is not using.
    MANAGER.set_tab_model("ask", "stheno_q8" if use_q8 else "stheno_q4")
    gen = None
    last_yield = 0.0
    try:
        gen = ask.ask_turn(message, turns, use_q8=bool(use_q8), temperature=float(temperature),
                           use_checker=bool(use_checker), condition=str(condition or prompts.DEFAULT_CONDITION))
        for ev in gen:
            kind = ev.get("kind")
            if kind == "token":
                pieces.append(ev.get("text") or "")
                chat[-1]["content"] = "".join(pieces)
                now = time.perf_counter()
                if now - last_yield < TOKEN_YIELD_INTERVAL_S:
                    continue
                last_yield = now
            elif kind == "trace":
                trace.append(ev.get("text") or "")
            elif kind == "hint":
                hints.append(ev.get("text") or "")
            elif kind == "checker":
                checker_md = _checker_markdown(ev)
            elif kind == "done":
                reply = (ev.get("text") or "").strip()
                chat[-1]["content"] = reply or "".join(pieces).strip() or "(empty reply)"
            yield _snapshot(chat), state._trace_markdown(trace), checker_md, _hint_markdown(hints), ""
    except Exception as e:  # noqa: BLE001
        state._log_exc("ask_turn")
        trace.append(f"error: {type(e).__name__}: {e}")
        chat[-1]["content"] = ("".join(pieces).strip() + "\n\n" if pieces else "") + state._err_text(e)
        yield _snapshot(chat), state._trace_markdown(trace), checker_md, _hint_markdown(hints), ""
    finally:
        if gen is not None:
            try:
                gen.close()
            except Exception:  # noqa: BLE001
                state._log_exc("ask_turn close")


def ask_clear():
    """Empty the chat and its side panels."""
    return [], "", "", "", ""


# ---- presentation helpers (build time only; no endpoint returns these) ----------------------------------------------

def twin_initial(name: str | None) -> str:
    """The owner's monogram letter, from the same helper the masthead uses (imported late: frame imports this module)."""
    from twin.ui import frame
    return frame.avatar_initial(name)


def twin_avatar(name: str | None) -> dict | None:
    """The twin's chat avatar for gr.Chatbot(avatar_images=(None, ...)): the monogram glyph as an inline SVG data URL,
    handed over as a FileData-shaped dict so Gradio serves it as is (no file on disk); None without a name."""
    initial = twin_initial(name)
    if not initial:
        return None
    svg = _AVATAR_SVG.format(initial=html.escape(initial))
    url = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {"path": "twin-avatar.svg", "url": url}


def empty_chat_html(name: str | None) -> str:
    """The empty-chat placeholder: the monogram, one line that invites the first question, one line on where the
    reply and its Trace appear. Uses the profile's first name when there is one."""
    first = html.escape(next(iter((name or "").split()), ""))
    who, whose = (first, f"{first}'s") if first else ("the twin", "the twin's")
    avatar = twin_avatar(name)
    mark = (f'<span class="ask-empty-mark" aria-hidden="true"><img src="{avatar["url"]}" alt=""></span>'
            if avatar else "")
    return (f'<div class="ask-empty">{mark}<div class="ask-empty-text">'
            f'<p class="ask-empty-title">Ask {who} a question to start.</p>'
            f"<p>Replies stream here in {whose} voice. The Trace beside the chat lists the steps behind each one.</p>"
            f"</div></div>")


def build(ctx) -> dict:
    """Render the Ask tab and wire /ask, /ask_clear and the private Enter-key submit."""
    name = getattr(state.PROFILE, "name", "") or ""
    with gr.Tab("Ask", id="ask", elem_id="tab-ask") as tab:
        # the conversation (transcript + composer) beside the evidence rail; the rail stacks under it when narrow
        with gr.Row(elem_id="ask-main", elem_classes=["twin-split"]):
            with gr.Column(scale=5, min_width=360, elem_id="ask-conversation"):
                chatbot = gr.Chatbot(label="Chat with the twin", height=420, elem_id="ask-chat",
                                     placeholder=empty_chat_html(name), avatar_images=(None, twin_avatar(name)))
                # one composer panel: the message row (Send is the area's only primary action), then the settings
                with gr.Column(elem_id="ask-composer", elem_classes=["twin-panel"]):
                    with gr.Row(elem_id="ask-compose", elem_classes=["twin-actions"]):
                        ask_msg = gr.Textbox(label="Message", placeholder="Ask me something...", scale=6, lines=1,
                                             min_width=240)
                        ask_send_btn = gr.Button("Send", variant="primary", scale=0, elem_id="ask-send")
                        ask_clear_btn = gr.Button("Clear", scale=0, elem_id="ask-clear", elem_classes=["twin-quiet"])
                    # Condition first (the one setting the demo changes); the two slow model toggles last
                    with gr.Row(elem_id="ask-settings"):
                        ask_condition = gr.Dropdown(choices=CONDITION_CHOICES, value=prompts.DEFAULT_CONDITION,
                                                    label="Condition", elem_id="ask-condition", min_width=180)
                        ask_temp = gr.Slider(0.5, 1.4, value=1.0, step=0.01, label="Temperature",
                                             elem_id="ask-temperature", min_width=240)
                        ask_q8 = gr.Checkbox(value=False, label="Q8 Stheno (Ollama, slow)", elem_id="ask-q8",
                                             min_width=220)
                        ask_checker = gr.Checkbox(value=False, label="Consistency check (qwen2.5)",
                                                  elem_id="ask-checker-toggle", min_width=240)
            # the evidence rail: the same hint, checker and trace outputs /ask always returned
            with gr.Column(scale=2, min_width=280, elem_id="ask-rail"):
                gr.Markdown(RAIL_EMPTY, elem_id="ask-rail-empty", elem_classes=["twin-empty"])
                ask_hint = gr.Markdown("", elem_id="ask-hint", elem_classes=["twin-hint"])
                ask_badge = gr.Markdown("", elem_id="ask-checker", elem_classes=["trace"])
                with gr.Accordion("Trace", open=False, elem_id="ask-trace-panel"):
                    ask_trace = gr.Markdown("_(no trace yet)_", elem_id="ask-trace", elem_classes=["trace"])

    ask_inputs = [ask_msg, chatbot, ask_q8, ask_temp, ask_checker, ask_condition]   # condition stays LAST
    ask_outputs = [chatbot, ask_trace, ask_badge, ask_hint, ask_msg]
    ask_send_btn.click(ask_send, inputs=ask_inputs, outputs=ask_outputs, api_name="ask", concurrency_id="gpu")
    ask_msg.submit(ask_send, inputs=ask_inputs, outputs=ask_outputs, api_name=False, concurrency_id="gpu")
    ask_clear_btn.click(ask_clear, inputs=None, outputs=ask_outputs, api_name="ask_clear")
    return {"tab": tab, "chatbot": chatbot, "msg": ask_msg, "send_btn": ask_send_btn, "clear_btn": ask_clear_btn,
            "temp": ask_temp, "q8": ask_q8, "checker": ask_checker, "condition": ask_condition, "hint": ask_hint,
            "badge": ask_badge, "trace": ask_trace}
