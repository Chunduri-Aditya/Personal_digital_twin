"""Items tab: the self-report form grouped by instrument (IPIP-50, games, gold, GSS), the wave save, the twin run
per condition and the scoring table (``/items_save``, ``/items_run``, ``/items_score``).

``READY = True``: the frame wires the model-less tab-select hook. The form is pre-filled from the wave-1 answers
``twin.pipelines.items.resolve_waves()`` finds (the real file, else the Mara example); picking wave 2 reloads the
form from the retest file or blanks it (a retest must not show the day-0 answers). ``/items_run`` is the only
model-backed endpoint here (gpu queue; ``skipped: TWIN_NO_WARM=1`` under the switch); ``/items_score`` never
touches a model.
"""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

import gradio as gr

from twin import config
from twin import profile as profile_mod
from twin.pipelines import items as items_mod
from twin.prompts import CONDITIONS
from twin.ui import state

READY = True
CONDITION_CHOICES = ["all", *CONDITIONS]
WAVE_CHOICES = ["1", "2"]
NO_WARM_NOTE = "skipped: TWIN_NO_WARM=1"
NO_SCORES_NOTE = "_(no scores yet: run the twin, then Score)_"
_PROGRESS_RE = re.compile(r"^\[(\d+)/(\d+)\]")


# ---- data adapters ----------------------------------------------------------------------
def bank() -> list[dict]:
    """Bank items in bank order for the app profile (gold text overridden, exclusions applied); [] on failure."""
    try:
        return items_mod.bank_items(state.PROFILE)
    except Exception:  # noqa: BLE001
        state._log_exc("bank_items")
        return []


def _profile_name() -> str:
    if state.PROFILE is not None and state.PROFILE.name:
        return state.PROFILE.name
    try:
        return profile_mod.load_profile().name
    except Exception:  # noqa: BLE001
        return ""


def wave_values(wave) -> tuple[str, dict]:
    """(date, {item_id: value}) of the chosen wave from resolve_waves(); (today, {}) when that wave has no file."""
    waves = items_mod.resolve_waves()
    key = "wave2" if str(wave).strip() == "2" else "wave1"
    doc = waves[key][1]
    if not doc:
        return date.today().isoformat(), {}
    return str(doc.get("date") or date.today().isoformat()), dict(doc.get("answers") or {})


def _fmt_path(p) -> str:
    try:
        return str(p.relative_to(config.PROJECT_ROOT))
    except (ValueError, AttributeError):
        return str(p)


def files_markdown() -> str:
    """The item files on disk: both waves (real or example), the twin answers per condition and the scores."""
    lines = []
    try:
        waves = items_mod.resolve_waves()
        src = "example (Mara) answers stand in until you save wave 1" if waves["example"] else "your answers"
        for key, label in (("wave1", "Wave 1 (day 0)"), ("wave2", "Wave 2 (day-14 retest)")):
            p, doc = waves[key]
            if doc:
                lines.append(f"- {label}: `{_fmt_path(p)}` dated {doc.get('date', '?')}, {len(doc.get('answers') or {})} answers")
            else:
                lines.append(f"- {label}: `{_fmt_path(p)}` not saved yet"
                             + (" (the normalized column reads *ceiling pending* until it exists)" if key == "wave2" else ""))
        lines[0] = lines[0] + f" ({src})"
    except Exception as e:  # noqa: BLE001
        lines.append(f"- waves: {state._err_text(e)}")
    try:
        sha = state.PROFILE.sha if state.PROFILE is not None else None
        entry = items_mod.load_twin_answers().get(sha) if sha else None
        cov = items_mod.coverage_lines(entry, bank()) if entry else []
        lines.append(f"- Twin answers `{_fmt_path(config.TWIN_ANSWERS_PATH)}`: " + ("; ".join(cov) if cov else "none for this profile yet"))
        sc = items_mod.load_scores()
        if sc and sc.get("sha") == sha:
            lines.append(f"- Scores `{_fmt_path(config.ITEM_SCORES_PATH)}`: updated {sc.get('updated', '?')}, "
                         f"{len(sc.get('rows') or [])} rows")
        else:
            lines.append(f"- Scores `{_fmt_path(config.ITEM_SCORES_PATH)}`: none for this profile yet")
    except Exception as e:  # noqa: BLE001
        lines.append(f"- twin answers/scores: {state._err_text(e)}")
    return "\n".join(lines)


def intro_markdown(items: list[dict]) -> str:
    groups = items_mod.items_by_instrument(items)
    counts = ", ".join(f"{items_mod.INSTRUMENT_LABELS.get(k, k)} {len(v)}" for k, v in groups.items())
    try:
        excluded = items_mod.excluded_items(state.PROFILE)
    except Exception:  # noqa: BLE001
        excluded = []
    ex = ("; skipped: " + ", ".join(f"`{iid}` ({why})" for iid, why in excluded)) if excluded else ""
    return (f"Answer the frozen item bank (`data/items/bank.json` v{_bank_version()}) as yourself: {len(items)} items "
            f"({counts}){ex}. Save wave 1 today and wave 2 about two weeks later; wave 2 becomes the ground truth "
            "and wave 1 vs wave 2 the retest ceiling. **Run twin** answers every item under a condition "
            "(demographic: identity only; persona: identity + digest; interview: retrieval + self-ratings) and "
            "**Score** compares the twin with your answers (no model).")


def _bank_version() -> str:
    try:
        return str(items_mod.load_bank().get("version", "?"))
    except Exception:  # noqa: BLE001
        return "?"


def cached_scores() -> tuple[list[list], str]:
    """(rows, decision markdown) from data/items/scores.json when it belongs to the app profile."""
    sc = items_mod.load_scores()
    sha = state.PROFILE.sha if state.PROFILE is not None else None
    if not sc or sc.get("sha") != sha:
        return [], NO_SCORES_NOTE
    return items_mod.summary_rows(sc), decision_markdown(sc)


def decision_markdown(sc: dict) -> str:
    w = sc.get("waves") or {}
    truth = w.get("ground_truth", "?")
    retest = "wave 1 vs wave 2" if w.get("retest") else "none (ceiling pending)"
    return (f"**{sc.get('decision') or items_mod.decision_line(sc)}**\n\n"
            f"_Ground truth: {truth} ({'example' if w.get('example') else 'your'} answers); retest ceiling: {retest}; "
            f"bootstrap {sc.get('n_boot')} resamples, seed {sc.get('seed')}; updated {sc.get('updated', '?')}._")


# ---- components -----------------------------------------------------------------------
def item_component(item: dict, value):
    """One form input per bank item (elem_id ``item-<id>``): IPIP and GSS as Radio, games as Number/Radio,
    gold as Textbox."""
    t, iid, text = item.get("type"), item["id"], (item.get("text") or "").strip()
    eid = f"item-{iid}"
    if t == "likert5":
        lo, _hi = items_mod._range(item, items_mod.LIKERT_RANGE)
        anchors = list(item.get("options") or items_mod.LIKERT_ANCHORS)
        choices = [(f"{i} {a}", i) for i, a in enumerate(anchors, int(lo))]
        return gr.Radio(choices=choices, value=value, label=text, info=iid, elem_id=eid, elem_classes=["item-likert"])
    if t == "categorical":
        return gr.Radio(choices=list(item.get("options") or []), value=value, label=text, info=iid, elem_id=eid,
                        elem_classes=["item-categorical"])
    if t == "number":
        lo, hi = items_mod._range(item, (0, 10))
        return gr.Number(value=value, minimum=lo, maximum=hi, precision=0, step=1, label=f"{iid}: whole number {lo}-{hi}",
                         info=text, elem_id=eid, elem_classes=["item-number"])
    if t == "fraction":
        lo, hi = items_mod._range(item, (0, 1))
        return gr.Number(value=value, minimum=lo, maximum=hi, precision=2, step=0.05, label=f"{iid}: fraction {lo}-{hi}",
                         info=text, elem_id=eid, elem_classes=["item-number"])
    if t == "binary":
        return gr.Radio(choices=list(item.get("options") or ["cooperate", "defect"]), value=value, label=text, info=iid,
                        elem_id=eid, elem_classes=["item-binary"])
    return gr.Textbox(value=value or "", label=text, info=iid, lines=2, elem_id=eid, elem_classes=["item-open"])


def _component_update(item: dict, value):
    t = item.get("type")
    if t in ("likert5", "categorical", "binary"):
        return gr.Radio(value=value)
    if t in ("number", "fraction"):
        return gr.Number(value=value)
    return gr.Textbox(value=value or "")


# ---- handlers --------------------------------------------------------------------------
def items_save(wave, date_text, *values):
    """Validate one value per bank item (bank order) and write the wave file; -> (note_md, files_md)."""
    its = bank()
    if len(values) != len(its):
        return state._err_md(ValueError(f"expected {len(its)} item values, got {len(values)}")), files_markdown()
    answers: dict = {}
    unanswered: list[str] = []
    invalid: list[str] = []
    for it, v in zip(its, values):
        cv = items_mod.coerce_value(it, v)
        if cv is None:
            (unanswered if v in (None, "") else invalid).append(it["id"])
        else:
            answers[it["id"]] = cv
    d = (date_text or "").strip() or date.today().isoformat()
    try:
        w = 2 if str(wave).strip() == "2" else 1
        p = items_mod.save_answers(w, answers, d, _profile_name())
    except Exception as e:  # noqa: BLE001
        state._log_exc("save_answers")
        return state._err_md(e), files_markdown()
    note = f"Saved wave {w} dated {d}: {len(answers)} answers, {len(unanswered)} unanswered -> `{_fmt_path(p)}`."
    if unanswered:
        note += " Unanswered: " + ", ".join(f"`{x}`" for x in unanswered[:12]) + (" ..." if len(unanswered) > 12 else "")
    if invalid:
        note += " **Invalid (not saved):** " + ", ".join(f"`{x}`" for x in invalid)
    if w == 2 and not Path(config.SELF_ANSWERS_PATH).exists():
        note += (" **Wave 1 is not saved:** wave 2 is the ground truth but there is no retest ceiling until "
                 f"wave 1 exists at `{_fmt_path(config.SELF_ANSWERS_PATH)}`.")
    elif w == 2:
        note += " Wave 2 is now the ground truth and wave 1 vs wave 2 the retest ceiling: click **Score**."
    return note, files_markdown()


def load_wave(wave):
    """Reload the date and every form value for the chosen wave (blank when that wave has no file)."""
    d, answers = wave_values(wave)
    return [gr.Textbox(value=d)] + [_component_update(it, answers.get(it["id"])) for it in bank()]


def _progress_callback(progress: gr.Progress):
    def cb(text: str) -> None:
        m = _PROGRESS_RE.match(text or "")
        try:
            if m:
                progress((int(m.group(1)), int(m.group(2))), desc=text)
            else:
                progress(None, desc=text)
        except Exception:  # noqa: BLE001
            pass
        print(f"[items] {text}", flush=True)
    return cb


def _score_and_save() -> tuple[list[list], str]:
    """Score and persist; an empty result (no twin answers for this profile yet) is never written to disk."""
    sc = items_mod.score()
    if not sc.get("rows"):
        return [], NO_SCORES_NOTE
    items_mod.save_scores(sc)
    return items_mod.summary_rows(sc), decision_markdown(sc)


def items_run(condition="interview", progress=gr.Progress()):
    """Run the twin over the bank for one condition (or all), then score; -> (note_md, score_rows)."""
    cond = (condition or "interview").strip().lower()
    conds = list(CONDITIONS) if cond == "all" else [cond]
    if state.no_warm():
        rows, _ = cached_scores()
        return f"Run twin ({', '.join(conds)}): {NO_WARM_NOTE}", rows
    t0 = time.perf_counter()
    try:
        out = items_mod.run_items(conditions=conds, progress=_progress_callback(progress))
        note = (f"Twin run ({', '.join(conds)}) finished in {(time.perf_counter() - t0) / 60:.1f} min: "
                f"{out['calls']} model calls; models {', '.join(out['models']) or 'none (all cells cached)'}; "
                f"results `{_fmt_path(config.TWIN_ANSWERS_PATH)}`.")
        if out.get("excluded"):
            note += " Skipped: " + ", ".join(f"`{iid}` ({why})" for iid, why in out["excluded"]) + "."
        if out.get("report"):
            note += "\n\n```\n" + "\n".join(out["report"]) + "\n```"
    except Exception as e:  # noqa: BLE001
        state._log_exc("run_items")
        rows, _ = cached_scores()
        return state._err_md(e), rows
    try:
        rows, decision = _score_and_save()
        note += "\n\n" + decision
    except Exception as e:  # noqa: BLE001
        state._log_exc("score")
        rows, _ = cached_scores()
        note += "\n\n" + state._err_md(e)
    return note, rows


def items_score():
    """Score the cached twin answers against the self answers (no model call); -> (score_rows, decision_md)."""
    try:
        return _score_and_save()
    except Exception as e:  # noqa: BLE001
        state._log_exc("score")
        return [], state._err_md(e)


# ---- UI --------------------------------------------------------------------------------
def build(ctx) -> dict:
    """Render the Items tab and wire /items_save, /items_run, /items_score and the private wave reload.
    Styles: static/tabs/items.css. Save answers, Run twin and Score rewrite data files (Run twin also loads four models
    for minutes), so all three are .twin-caution outlines at their natural width, never a solid call to action
    (docs/DEMO.md section 3 forbids them live); the decision line is the tab's one raised card."""
    its = bank()
    groups = items_mod.items_by_instrument(its)
    _d, w1 = wave_values("1")
    rows0, decision0 = cached_scores()
    inputs: list = []
    with gr.Tab("Items", id="items", elem_id="tab-items") as tab:
        intro = gr.Markdown(intro_markdown(its), elem_id="items-intro", elem_classes=["twin-intro"])
        with gr.Row(elem_id="items-wave-row", elem_classes=["twin-actions"]):
            wave_dd = gr.Dropdown(choices=WAVE_CHOICES, value="1", label="Wave (1 = day 0, 2 = day-14 retest)",
                                  elem_id="items-wave", scale=1)
            date_tb = gr.Textbox(value=date.today().isoformat(), label="Date (YYYY-MM-DD)", elem_id="items-date", scale=1)
            save_btn = gr.Button("Save answers", variant="secondary", elem_id="items-save", scale=0,
                                 elem_classes=["twin-caution"])
        save_note = gr.Markdown("", elem_id="items-save-note")
        files_md = gr.Markdown(files_markdown(), elem_id="items-files")
        with gr.Column(elem_id="items-form"):
            for inst, group in groups.items():
                label = f"{items_mod.INSTRUMENT_LABELS.get(inst, inst)} ({len(group)} items)"
                with gr.Accordion(label, open=(inst == "ipip50"), elem_id=f"items-group-{inst}",
                                  elem_classes=["items-group"]):
                    if inst == "ipip50":
                        gr.Markdown("How accurately does each statement describe you? 1 = Very Inaccurate ... "
                                    "5 = Very Accurate. Domains: " + ", ".join(
                                        f"{d} {items_mod.IPIP_DOMAIN_LABELS[d]}" for d in items_mod.IPIP_DOMAINS) + ".",
                                    elem_classes=["items-note"])
                    elif inst == "gold":
                        gr.Markdown("Your own words, one or two lines each: these are the profile's Eval questions, "
                                    "judged against the twin's replies by llama3.1 and qwen2.5.",
                                    elem_classes=["items-note"])
                    elif inst == "game":
                        gr.Markdown("Fixed parameters from D4: endowment 10, trust transfers tripled, public goods "
                                    "group of 4 with multiplier 1.6, one-shot prisoner's dilemma.",
                                    elem_classes=["items-note"])
                    last_domain = None
                    for it in group:
                        if inst == "ipip50" and it.get("domain") != last_domain:
                            last_domain = it.get("domain")
                            gr.Markdown(f"**{last_domain}: {items_mod.IPIP_DOMAIN_LABELS.get(last_domain, last_domain)}**",
                                        elem_classes=["items-domain"])
                        inputs.append(item_component(it, w1.get(it["id"])))
        with gr.Row(elem_id="items-run-row", elem_classes=["twin-actions"]):
            cond_dd = gr.Dropdown(choices=CONDITION_CHOICES, value="interview", label="Condition",
                                  elem_id="items-condition", scale=1)
            run_btn = gr.Button("Run twin (qwen3-8b-8k, Stheno, two judges)", variant="secondary",
                                elem_id="items-run", scale=0, elem_classes=["twin-caution"])
            score_btn = gr.Button("Score (no model)", variant="secondary", elem_id="items-score", scale=0,
                                  elem_classes=["twin-caution"])
        run_note = gr.Markdown("", elem_id="items-run-note")
        score_df = gr.Dataframe(value=rows0, headers=list(items_mod.SCORE_HEADERS), label="Scores per condition and instrument",
                                interactive=False, wrap=True, elem_id="items-scores", elem_classes=["twin-table"])
        decision_md = gr.Markdown(decision0, elem_id="items-decision", elem_classes=["twin-card", "twin-result"])

    save_btn.click(items_save, inputs=[wave_dd, date_tb, *inputs], outputs=[save_note, files_md], api_name="items_save")
    run_btn.click(items_run, inputs=[cond_dd], outputs=[run_note, score_df], api_name="items_run", concurrency_id="gpu")
    score_btn.click(items_score, inputs=None, outputs=[score_df, decision_md], api_name="items_score")
    wave_dd.change(load_wave, inputs=[wave_dd], outputs=[date_tb, *inputs], api_name=False)
    return {"tab": tab, "intro": intro, "wave": wave_dd, "date": date_tb, "save_btn": save_btn, "save_note": save_note,
            "files": files_md, "inputs": inputs, "condition": cond_dd, "run_btn": run_btn, "run_note": run_note,
            "scores": score_df, "score_btn": score_btn, "decision": decision_md}
