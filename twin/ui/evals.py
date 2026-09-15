"""Eval tab: cached bake-off tables, re-runs, the live one-candidate check and the boundary probes
(``/eval_show``, ``/eval_voice_rerun``, ``/eval_retrieval_rerun``, ``/eval_live``).

The condition dropdown (docs/PLAN_UNIFIED.md 3.4) is the LAST input of /eval_live. The probes table
(twin.pipelines.probes, safeguards lane) is shown under the bake-off tables from the cache and re-run after the
voice bake-off; its result is appended to the note. The probes module is optional at import time so the lanes
can land independently."""
from __future__ import annotations

import time

import gradio as gr

from twin import clients, prompts
from twin.pipelines import evals
from twin.ui import state

try:
    from twin.pipelines import probes
except ImportError:      # the safeguards lane's module has not landed (or was removed)
    probes = None

CONDITION_CHOICES = [(c, c) for c in prompts.CONDITIONS]
NO_PROBES = "(no probe results yet)"


def eval_tables():
    """Cached tables for the profile on disk (no model call)."""
    try:
        res = evals.results_for_current_profile()
        return state._clean_rows(evals.summary_rows(res)), state._clean_rows(evals.retrieval_rows(res))
    except Exception:  # noqa: BLE001
        state._log_exc("eval_tables")
        return [], []


def probes_markdown() -> str:
    """Cached boundary-probe table for the profile on disk (no model call); a placeholder without the module."""
    if probes is None:
        return NO_PROBES
    try:
        return probes.markdown_table(probes.load_cached())
    except Exception:  # noqa: BLE001
        state._log_exc("probes_markdown")
        return NO_PROBES


def _run_probes(progress) -> str:
    """Run the boundary probes under the interview condition (after the bake-off) and return their table."""
    if probes is None:
        return "_Boundary probes: module not available._"
    try:
        cache = probes.run_probes(condition="interview", progress=state._progress_callback(progress))
        return "**Boundary probes (interview):**\n\n" + probes.markdown_table(cache)
    except Exception as e:  # noqa: BLE001
        state._log_exc("run_probes")
        return "Boundary probes: " + state._err_md(e)


def eval_voice_rerun(use_claude=True, progress=gr.Progress()):
    """Re-run the voice bake-off (resumes from the cache), then the boundary probes, then refresh the tables. The
    Claude judge runs only when use_claude is ticked and the key is available."""
    t0 = time.perf_counter()
    try:
        want = bool(use_claude) and clients.anthropic_client.available()
        evals.run_voice_bakeoff(use_claude=want, progress=state._progress_callback(progress))
        note = (f"Voice bake-off finished in {(time.perf_counter() - t0) / 60:.1f} min "
                f"(Claude judge {'on' if want else 'off'}).")
    except Exception as e:  # noqa: BLE001
        state._log_exc("run_voice_bakeoff")
        note = state._err_md(e)
    note += "\n\n" + _run_probes(progress)
    summary, retrieval = eval_tables()
    return summary, retrieval, note


def eval_retrieval_rerun(progress=gr.Progress()):
    """Re-run the retrieval bake-off, then refresh the tables."""
    t0 = time.perf_counter()
    try:
        evals.run_retrieval_bakeoff(progress=state._progress_callback(progress))
        note = f"Retrieval bake-off finished in {time.perf_counter() - t0:.0f} s."
    except Exception as e:  # noqa: BLE001
        state._log_exc("run_retrieval_bakeoff")
        note = state._err_md(e)
    summary, retrieval = eval_tables()
    return summary, retrieval, note


def eval_live_handler(candidate, qid, condition=prompts.DEFAULT_CONDITION):
    """One candidate x one eval question under one condition, judged by llama3.1 and (interview only) checked by
    qwen2.5 (not cached)."""
    try:
        return evals.live_one(candidate or evals.CANDIDATES[0], (qid or None),
                              condition=str(condition or prompts.DEFAULT_CONDITION))
    except Exception as e:  # noqa: BLE001
        state._log_exc("live_one")
        return {"error": state._err_text(e)}


def build(ctx) -> dict:
    """Render the Eval tab and wire /eval_show, /eval_voice_rerun, /eval_retrieval_rerun and /eval_live.

    Layout (docs/PLAN_FINISH.md P4; styles in static/tabs/eval.css): the intro and the ceiling-judge option, the voice
    and retrieval score tables (.twin-table), the boundary probes table (#eval-probes), one action row with the
    no-model Refresh at the left and the two re-runs set apart at its far end (.twin-caution: they load models for
    minutes, so no button here is filled), the note, and the live one-candidate check on its own panel (#eval-live).
    Labels, values, api_names, queues and event wiring are unchanged (the DEMO CONTRACT)."""
    summary0, retrieval0 = eval_tables()
    with gr.Tab("Eval", id="eval", elem_id="tab-eval") as tab:
        gr.Markdown("Cached bake-off results for the current profile (replayed, no model load). "
                    "Re-running writes `data/eval_results.json` after every call and resumes. "
                    "Judges: llama3.1 (primary), qwen2.5 (second judge + consistency checker, always on). "
                    "Rows named `cand@condition` are the persona / demographic ablations. "
                    + state.claude_judge_markdown(), elem_id="eval-intro", elem_classes=["twin-intro"])
        with gr.Row(elem_id="eval-options"):
            eval_use_claude = gr.Checkbox(value=clients.anthropic_client.available(),
                                          interactive=clients.anthropic_client.available(),
                                          label="Use Claude ceiling judge (needs ANTHROPIC_API_KEY)",
                                          elem_id="eval-use-claude")
        eval_summary = gr.Dataframe(value=summary0, headers=list(evals.SUMMARY_HEADERS),
                                    label="Voice bake-off", interactive=False, wrap=True,
                                    elem_id="eval-summary", elem_classes=["twin-table"])
        eval_retrieval = gr.Dataframe(value=retrieval0, headers=list(evals.RETRIEVAL_HEADERS),
                                      label="Retrieval bake-off", interactive=False, wrap=True,
                                      elem_id="eval-retrieval", elem_classes=["twin-table"])
        eval_probes = gr.Markdown(probes_markdown(), elem_id="eval-probes", elem_classes=["eval-md-table"])
        with gr.Row(elem_id="eval-actions", elem_classes=["twin-actions"]):
            eval_refresh_btn = gr.Button("Refresh", scale=0, elem_id="eval-refresh")
            eval_voice_btn = gr.Button("Re-run voice bake-off (~6 min)", scale=0, elem_id="eval-voice-rerun",
                                       elem_classes=["twin-caution"])
            eval_retrieval_btn = gr.Button("Re-run retrieval bake-off", scale=0, elem_id="eval-retrieval-rerun",
                                           elem_classes=["twin-caution"])
        eval_note = gr.Markdown("", elem_id="eval-note", elem_classes=["twin-hint", "eval-md-table"])
        with gr.Column(elem_id="eval-live", elem_classes=["twin-panel"]):
            with gr.Row(elem_id="eval-live-controls"):
                eval_candidate = gr.Dropdown(choices=state._candidate_choices(), value=evals.CANDIDATES[0],
                                             label="Candidate")
                qids = state._eval_qid_choices()
                eval_qid = gr.Dropdown(choices=qids, value=(qids[0][1] if qids else None), label="Eval question")
                eval_condition = gr.Dropdown(choices=CONDITION_CHOICES, value=prompts.DEFAULT_CONDITION,
                                             label="Condition", elem_id="eval-condition")
                eval_live_btn = gr.Button("Live: one candidate x one question (~15 s)", scale=0,
                                          elem_id="eval-live-run", elem_classes=["twin-caution"])
            eval_live_json = gr.JSON(label="Live result", elem_id="eval-live-result")

    # The probes table has no endpoint of its own (the phase-1 endpoint shapes are frozen): it refreshes through
    # private follow-ups of the Refresh and voice re-run clicks.
    eval_refresh_btn.click(eval_tables, inputs=None, outputs=[eval_summary, eval_retrieval],
                           api_name="eval_show").then(probes_markdown, inputs=None, outputs=[eval_probes],
                                                      api_name=False)
    eval_voice_btn.click(eval_voice_rerun, inputs=[eval_use_claude],
                         outputs=[eval_summary, eval_retrieval, eval_note],
                         api_name="eval_voice_rerun", concurrency_id="gpu").then(
        probes_markdown, inputs=None, outputs=[eval_probes], api_name=False)
    eval_retrieval_btn.click(eval_retrieval_rerun, inputs=None,
                             outputs=[eval_summary, eval_retrieval, eval_note],
                             api_name="eval_retrieval_rerun", concurrency_id="gpu")
    eval_live_btn.click(eval_live_handler, inputs=[eval_candidate, eval_qid, eval_condition],
                        outputs=[eval_live_json], api_name="eval_live", concurrency_id="gpu")
    return {"tab": tab, "use_claude": eval_use_claude, "summary": eval_summary, "retrieval": eval_retrieval,
            "probes": eval_probes, "refresh_btn": eval_refresh_btn, "voice_btn": eval_voice_btn,
            "retrieval_btn": eval_retrieval_btn, "note": eval_note, "candidate": eval_candidate, "qid": eval_qid,
            "condition": eval_condition, "live_btn": eval_live_btn, "live_json": eval_live_json}
