"""Onboarding tab: a ``gr.Walkthrough`` with four steps (interview, save + redact, rebuild the index, self-report
items), each with a status line from file checks and a copyable command, plus ``/onboarding_check``.

``READY = True``: the frame wires the model-less tab-select hook and opens this tab first while
``data/twin_profile.md`` is missing. Nothing here calls a model: the checks read files and the index shas.
"""
from __future__ import annotations

import gradio as gr

from twin import config, index
from twin import profile as profile_mod
from twin.pipelines import items as items_mod
from twin.ui import state

READY = True

STEP_KEYS = ("interview", "redact", "index", "items")
STEP_LABELS = {
    "interview": "1. Run the interview",
    "redact": "2. Save the profile and transcript, then redact",
    "index": "3. Rebuild the index",
    "items": "4. Answer the self-report items",
}
STEP_HELP = {
    "interview": ("Paste `docs/opus_interview_prompt.md` into claude.ai with Claude Opus and answer in your own words "
                  "(about 90-120 minutes, one sitting). At the end of every block Claude prints that block's turns; "
                  "after block 7 it prints the complete profile."),
    "redact": ("Save the seven transcript blocks as `data/interview_transcript.md` and the profile as "
               "`data/twin_profile.md`, then redact: emails, phones, addresses and third-party names are replaced by "
               "role tags before anything is indexed. The index only ever reads the redacted copy."),
    "index": ("Embed the profile, the redacted transcript and the expert reflections into the three indexes, refresh "
              "`chunks.json` and the digest, then lint the profile. Rebuild only between GPU stages, never during one."),
    "items": ("Fill the Items tab (about 45 minutes) and save wave 1 today; about two weeks later save wave 2 (the "
              "retest ceiling), then **Run twin** for all three conditions and read the decision line."),
}
COMMANDS = {
    "interview": "Get-Content docs\\opus_interview_prompt.md | Set-Clipboard   # then paste into claude.ai (Opus)",
    "redact": "$env:PYTHONUTF8=1; python -m twin.redact data\\interview_transcript.md",
    "index": "$env:PYTHONUTF8=1; python -m twin.index --build all --digest --reflect; python -m twin.profile --lint",
    "items": "$env:PYTHONUTF8=1; python -m twin.pipelines.items --run --condition all --score   # or the Items tab",
}


def _rel(p) -> str:
    try:
        return str(p.relative_to(config.PROJECT_ROOT))
    except (ValueError, AttributeError):
        return str(p)


def _profile():
    if state.PROFILE is not None:
        return state.PROFILE
    return profile_mod.load_profile()


# ---- per-step checks: (done, markdown) --------------------------------------------------
def interview_status() -> tuple[bool, str]:
    p = config.PROFILE_PATH
    if p.exists():
        try:
            prof = profile_mod.load_profile(p)
            return True, (f"**Done.** `{_rel(p)}` ({prof.name or '?'}, updated {prof.updated or '?'}, schema "
                          f"{prof.schema_version or 'v1'}, sha {prof.sha[:8]}): {len(prof.chunks)} chunks, "
                          f"{len(prof.decisions)} decisions, {len(prof.eval)} eval questions.")
        except Exception as e:  # noqa: BLE001
            return False, f"**To do.** `{_rel(p)}` exists but does not parse: `{type(e).__name__}: {str(e)[:200]}`."
    example = profile_mod.resolve_profile_path()
    return False, (f"**To do.** `{_rel(p)}` is missing; the app runs on the example profile `{_rel(example)}` "
                   "until the interview is done.")


def redact_status() -> tuple[bool, str]:
    t = config.TRANSCRIPT_PATH
    if not t.exists():
        ex = config.EXAMPLE_TRANSCRIPT_PATH
        return False, (f"**To do.** `{_rel(t)}` is missing"
                       + (f"; the example transcript `{_rel(ex)}` stands in" if ex.exists() else "") + ".")
    try:
        src = index.resolve_transcript_source(quiet=True)
    except index.RedactionRequired as e:
        return False, f"**To do.** {e}"
    except Exception as e:  # noqa: BLE001
        return False, f"**To do.** transcript check failed: `{type(e).__name__}: {str(e)[:200]}`."
    if src is not None and src == config.REDACTED_TRANSCRIPT_PATH:
        report = ""
        try:
            from twin import redact
            rep = redact.load_report() or {}
            counts = rep.get("counts") or {}
            if counts:
                report = " Redaction report: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + "."
        except Exception:  # noqa: BLE001
            pass
        return True, (f"**Done.** `{_rel(t)}` saved and `{_rel(config.REDACTED_TRANSCRIPT_PATH)}` matches its "
                      f"sha ({index.file_sha(t)[:8]}).{report}")
    return False, f"**To do.** `{_rel(config.REDACTED_TRANSCRIPT_PATH)}` is missing or out of date: run the command."


def index_status() -> tuple[bool, str]:
    try:
        prof = _profile()
    except Exception as e:  # noqa: BLE001
        return False, f"**To do.** no profile to check the indexes against: `{type(e).__name__}: {str(e)[:200]}`."
    states = []
    all_fresh = True
    for key in index.INDEX_KEYS:
        try:
            stale = index.is_stale(key, prof)
            stale_src = index.is_stale_sources(key, prof)
        except Exception:  # noqa: BLE001
            stale = stale_src = True
        if not index.index_path(key).exists():
            word = "missing"
        elif stale:
            word = "stale (profile changed)"
        elif stale_src:
            word = "stale (transcript/reflections changed)"
        else:
            word = "fresh"
        all_fresh = all_fresh and word == "fresh"
        states.append(f"`{key}` {word}")
    n, _sha, fresh = state._digest_state()
    digest = "fresh" if fresh else ("missing" if not n else "stale")
    all_fresh = all_fresh and fresh
    head = "**Done.**" if all_fresh else "**To do.**"
    return all_fresh, f"{head} Indexes for `{_rel(prof.path)}`: {', '.join(states)}; digest {digest}."


def items_status() -> tuple[bool, str]:
    p1, p2 = config.SELF_ANSWERS_PATH, config.SELF_ANSWERS_RETEST_PATH
    if not p1.exists():
        return False, (f"**To do.** `{_rel(p1)}` not saved yet: fill the **Items** tab and save wave 1 (the example "
                       "answers stand in until then).")
    w1 = items_mod.load_answers(p1)
    if not w1:
        return False, f"**To do.** `{_rel(p1)}` exists but is not a valid answer file."
    n1 = len(w1.get("answers") or {})
    w2 = items_mod.load_answers(p2) if p2.exists() else None
    if w2:
        tail = f" Wave 2 saved {w2.get('date', '?')} ({len(w2.get('answers') or {})} answers): the retest ceiling is set."
    else:
        tail = " Wave 2 (the day-14 retest) not saved yet: the normalized column reads *ceiling pending* until then."
    return True, f"**Done.** Wave 1 saved {w1.get('date', '?')} ({n1} answers).{tail}"


STEP_CHECKS = {"interview": interview_status, "redact": redact_status, "index": index_status, "items": items_status}


def step_statuses() -> list[tuple[bool, str]]:
    out = []
    for key in STEP_KEYS:
        try:
            out.append(STEP_CHECKS[key]())
        except Exception as e:  # noqa: BLE001
            state._log_exc(f"onboarding {key}")
            out.append((False, state._err_md(e)))
    return out


def first_incomplete(statuses: list[tuple[bool, str]] | None = None) -> int:
    """Index of the first step that is not done (the last step when everything is done)."""
    st = statuses if statuses is not None else step_statuses()
    for i, (done, _md) in enumerate(st):
        if not done:
            return i
    return len(STEP_KEYS) - 1


def onboarding_check():
    """/onboarding_check -> the four status markdowns (file checks only, no model)."""
    return tuple(md for _done, md in step_statuses())


def build(ctx) -> dict:
    """Render the walkthrough and wire /onboarding_check. Styles: static/tabs/onboarding.css (the walkthrough on one
    sheet, step state in the numbers, Check again at its natural width); labels, statuses and wiring are unchanged."""
    statuses = step_statuses()
    status_md: list = []
    with gr.Tab("Onboarding", id="onboarding", elem_id="tab-onboarding") as tab:
        gr.Markdown("Four steps turn the example twin into yours. Each step shows what the files on disk say and the "
                    "command to run from the project root in PowerShell. Nothing on this tab loads a model.",
                    elem_id="onboarding-intro", elem_classes=["twin-intro"])
        with gr.Walkthrough(selected=first_incomplete(statuses), elem_id="onboarding-walkthrough",
                            elem_classes=["onboarding-walkthrough"]) as walkthrough:
            for i, key in enumerate(STEP_KEYS):
                with gr.Step(STEP_LABELS[key], id=i, elem_id=f"onboarding-step-{key}"):
                    status_md.append(gr.Markdown(statuses[i][1], elem_id=f"onboarding-status-{key}",
                                                 elem_classes=["onboarding-status"]))
                    gr.Markdown(STEP_HELP[key], elem_classes=["onboarding-help"])
                    gr.Code(COMMANDS[key], language="shell", lines=1, label="Command (PowerShell, project root)",
                            interactive=False, wrap_lines=True, show_line_numbers=False,
                            elem_id=f"onboarding-cmd-{key}", elem_classes=["onboarding-command"])
        check_btn = gr.Button("Check again", variant="primary", elem_id="onboarding-check")
    check_btn.click(onboarding_check, inputs=None, outputs=status_md, api_name="onboarding_check")
    return {"tab": tab, "walkthrough": walkthrough, "status": status_md, "check_btn": check_btn}
