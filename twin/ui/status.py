"""Status tab: GPU/model state, telemetry, free/warm/rebuild controls (``/status``, ``/free_gpu``, ``/warm``,
``/rebuild_index``, ``/rebuild_digest``; the 5 s refresh tick is private and GET-only), a persona switcher and
.md importer (``/persona_switch``, ``/persona_import``; twin.personas), plus the safeguards
(docs/PLAN_UNIFIED.md 3.6): the audit tail with counts per day (``/audit_tail``), the redaction report
(``/redaction_report``), the reflections-draft note and the index sources freshness in the status text.

With ``TWIN_NO_WARM=1`` (``state.no_warm()``, read at call time) ``/warm``, ``/rebuild_index`` and
``/rebuild_digest`` return a "skipped: TWIN_NO_WARM=1" note without touching a model. ``/rebuild_index`` runs
``index.build_all(profile, True, with_reflections=True)`` and shows ``RedactionRequired`` / ``LeakError``
messages instead of a traceback; its note ends with the refreshed redaction report summary.
"""
from __future__ import annotations

import html
import time
from pathlib import Path

import gradio as gr

from twin import audit, clients, config, index, personas, redact, telemetry
from twin import profile as profile_mod
from twin.gpu import MANAGER
from twin.pipelines import reflect
from twin.ui import state

NO_WARM_NOTE = "skipped: TWIN_NO_WARM=1"
AUDIT_HEADERS = ["time", "tab", "condition", "request_sha", "chunks", "models", "ok"]
AUDIT_ROWS = 50
AUDIT_DAYS = 14
NO_REDACTION_REPORT = "(no redaction report yet)"
REDACT_HINT = "python -m twin.redact data\\interview_transcript.md"


# ---- safeguards: audit tail, redaction report, reflections note, sources freshness ----------------------
def audit_rows(n: int = AUDIT_ROWS) -> list[list]:
    """Rows under AUDIT_HEADERS for the last `n` audit entries, newest first (like the telemetry table)."""
    rows: list[list] = []
    for e in reversed(audit.tail(n)):
        ids = [str(c) for c in (e.get("chunk_ids") or [])]
        rows.append([
            str(e.get("ts") or "")[:19].replace("T", " "),
            str(e.get("tab") or ""),
            str(e.get("condition") or ""),
            str(e.get("request_sha") or "")[:12],
            f"{len(ids)}: {', '.join(ids)}" if ids else "0",
            ", ".join(str(k) for k in (e.get("model_keys") or [])),
            bool(e.get("ok")),
        ])
    return rows


def audit_counts_markdown(days: int = AUDIT_DAYS) -> str:
    """One line with the requests per day over the last `days` days ("(no audit entries yet)" when empty)."""
    counts = audit.counts_per_day(days)
    if not counts:
        return f"**Audit** (`{Path(audit.AUDIT_PATH).name}`, request text stored as sha256 only): (no audit entries yet)"
    total = sum(n for _, n in counts)
    per_day = ", ".join(f"{d}: {n}" for d, n in counts)
    return (f"**Audit** (`{Path(audit.AUDIT_PATH).name}`, request text stored as sha256 only): {total} requests in "
            f"the last {days} days; per day: {per_day}")


def audit_tail_handler():
    """(audit rows, counts markdown); file reads only."""
    try:
        return audit_rows(), audit_counts_markdown()
    except Exception as e:  # noqa: BLE001
        state._log_exc("audit_tail")
        return [], state._err_md(e)


def redaction_report_summary(report: dict | None = None) -> str:
    """One line: counts, tags, output path, source sha, time; NO_REDACTION_REPORT when there is none."""
    rep = redact.load_report() if report is None else report
    if not rep:
        return NO_REDACTION_REPORT
    counts = rep.get("counts") or {}
    tags: dict[str, int] = {}
    for tag in rep.get("replacements") or []:
        tags[str(tag)] = tags.get(str(tag), 0) + 1
    return (f"turns {rep.get('turns', '?')}, llm pass {'yes' if rep.get('llm') else 'no'}; counts: "
            + (", ".join(f"{k} {v}" for k, v in counts.items()) or "none")
            + "; tags: " + (", ".join(f"{k} x{v}" for k, v in tags.items()) or "none")
            + f"; output `{rep.get('output', '?')}`; source sha {str(rep.get('source_sha') or '')[:12] or '?'}; "
              f"at {rep.get('redacted_at', '?')}")


def redaction_report_markdown() -> str:
    """Markdown block for the redaction report section (redact.load_report(); never a removed string)."""
    rep = redact.load_report()
    if not rep:
        return (f"**Redaction report:** {NO_REDACTION_REPORT} (`{REDACT_HINT}` writes "
                f"`{Path(config.REDACTION_REPORT_PATH).name}`; the index reads only the redacted transcript)")
    counts = rep.get("counts") or {}
    tags: dict[str, int] = {}
    for tag in rep.get("replacements") or []:
        tags[str(tag)] = tags.get(str(tag), 0) + 1
    lines = [
        f"**Redaction report** (`{Path(config.REDACTION_REPORT_PATH).name}`): `{rep.get('source', '?')}` -> "
        f"`{rep.get('output', '?')}`",
        f"- turns: {rep.get('turns', '?')}, llm pass: {'yes' if rep.get('llm') else 'no (--no-llm)'}, "
        f"source sha {str(rep.get('source_sha') or '')[:12] or '?'}, at {rep.get('redacted_at', '?')}",
        "- counts: " + (", ".join(f"{k} {v}" for k, v in counts.items()) or "none"),
        "- tags used: " + (", ".join(f"`{k}` x{v}" for k, v in tags.items()) or "none"),
    ]
    return "\n".join(lines)


def redaction_report_handler():
    """The redaction report markdown; file reads only."""
    try:
        return redaction_report_markdown()
    except Exception as e:  # noqa: BLE001
        state._log_exc("redaction_report")
        return state._err_md(e)


def reflections_note() -> str:
    """The reflect.py draft state: 'review and paste' while the profile lacks # Expert reflections, 'already has
    the section; the draft is not indexed' otherwise, 'no draft yet' when the file is missing."""
    path = Path(reflect.REFLECTIONS_PATH)
    if not path.exists():
        return ("**Reflections:** no draft yet (`python -m twin.index --build all --digest --reflect` writes "
                f"`{path.name}`).")
    key = (reflect.reflections_sha() or "?")[:8]
    n = len(reflect.load_reflections())
    prof = state.PROFILE
    if prof is not None and (getattr(prof, "reflections", None) or "Expert reflections" in (prof.sections or {})):
        return (f"**Reflections:** profile already has # Expert reflections; the draft is not indexed "
                f"(draft {key}, {n} lenses).")
    return f"**Reflections:** reflections draft {key} ({n} lenses): review and paste into # Expert reflections."


def sources_state() -> str:
    """'fresh' | 'STALE (<keys>)' | 'redaction required (...)' for the index sources (profile + transcript +
    reflections shas) via index.is_stale_sources; file reads only.

    This always resolves the transcript the DEFAULT way (the real transcript, else Mara's example), matching
    what the Rebuild index + digest button on this tab actually runs. A persona switched in with
    twin.personas.switch (no transcript of its own) is built correctly by that dedicated flow -- its own
    is_stale_sources call there passes no_transcript=True -- but this general status line, and the general
    Rebuild button below, do not know which persona is active and keep the pre-persona default; use Switch
    persona (not Rebuild index + digest) to rebuild for a persona that has no transcript."""
    prof = state.PROFILE
    if prof is None:
        return "unknown (no profile)"
    try:
        index.resolve_transcript_source(quiet=True)
    except index.RedactionRequired:
        return f"redaction required (`{REDACT_HINT}`)"
    except Exception as e:  # noqa: BLE001
        return f"unknown ({type(e).__name__})"
    stale = []
    for key in index.INDEX_KEYS:
        try:
            if index.is_stale_sources(key, prof):
                stale.append(key)
        except index.RedactionRequired:
            return f"redaction required (`{REDACT_HINT}`)"
        except Exception:  # noqa: BLE001
            stale.append(key)
    return f"STALE ({', '.join(stale)})" if stale else "fresh"


def _fmt_gb(n) -> str:
    """Bytes -> "x.x GB"."""
    try:
        return f"{float(n) / 1e9:.1f} GB"
    except (TypeError, ValueError):
        return "?"


def _last_warm_from_telemetry() -> str:
    """Most recent warm call as recorded by the clients (gpu.py itself keeps no last-warm time)."""
    for r in reversed(telemetry.recent(500)):
        if r.tab == "warm":
            return (f"{time.strftime('%H:%M:%S', time.localtime(r.ts))} {r.model} "
                    f"({'ok' if r.ok else 'failed'}, load {r.load_ms:.0f} ms)")
    return "none yet"


def _ollama_names(entries) -> set[str]:
    """Registry keys of the Ollama models named in a /api/ps or /api/tags list."""
    keys = set()
    for e in entries or []:
        if not isinstance(e, dict) or "error" in e:
            continue
        s = config.by_name(e.get("name") or e.get("model") or "")
        if s is not None:
            keys.add(s.key)
    return keys


def _model_state(s: config.ModelSpec, ps_keys: set[str], tag_keys: set[str], lms: list[dict]) -> str:
    """One word per model for the Models table: loaded / on disk / not pulled / key set / no key."""
    if s.runtime == "ollama":
        if s.key in ps_keys:
            return "loaded"
        return "on disk" if s.key in tag_keys else "not pulled"
    if s.runtime == "lms":
        for m in lms:
            if isinstance(m, dict) and m.get("id") == s.name:
                return "loaded" if m.get("state") == "loaded" else "on disk"
        return "not listed"
    if s.runtime == "anthropic":
        return "key set" if clients.anthropic_client.available() else "no key"
    return "?"


def models_table_markdown(st: dict) -> str:
    """Markdown table of every registry model with its job (CONTRACTS: ModelSpec.job is shown here)."""
    ps_keys = _ollama_names(st.get("ollama_ps"))
    tag_keys = _ollama_names(st.get("ollama_tags"))
    lms = [m for m in (st.get("lms_models") or []) if isinstance(m, dict)]
    rows = ["| key | server name | runtime | vram | state | job |", "|---|---|---|---|---|---|"]
    for s in config.MODELS.values():
        rows.append(f"| `{s.key}` | `{s.name}` | {s.runtime} | {s.vram} | {_model_state(s, ps_keys, tag_keys, lms)} "
                    f"| {s.job} |")
    return "\n".join(rows)


def status_markdown(note: str = "") -> str:
    """Markdown for the Status tab from MANAGER.status() (GETs + nvidia-smi only; never loads a model)."""
    try:
        st = MANAGER.status()
    except Exception as e:  # noqa: BLE001
        state._log_exc("status")
        st = {"ollama_ps": [{"error": str(e)}], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
              "active_tab": MANAGER.active_tab, "active_key": MANAGER.active_key(), "tab_overrides": {}}
    lines: list[str] = []
    if note:
        lines.append(f"**Last action:** {note}")
    active = st.get("active_tab") or None
    key = st.get("active_key") or MANAGER.active_key()
    model = f"{key} = {config.spec(key).name}" if key else "none"
    override = (st.get("tab_overrides") or {}).get(active or "")
    lines.append(f"**Active tab:** {active or 'none (nothing selected yet)'} (model {model}"
                 + (f", override from the Q8 toggle" if override else "") + ")"
                 + (f"; last model tab: {MANAGER.last_model_tab}" if MANAGER.last_model_tab and
                    MANAGER.last_model_tab != active else ""))
    hb = getattr(MANAGER, "_heartbeat", None)
    alive = bool(hb is not None and hb.is_alive())
    lines.append(f"**Heartbeat:** {'alive' if alive else 'not running'} (re-warms only the active tab's model "
                 f"every 4 min; Status never becomes the active tab, Eval clears it); "
                 f"last warm call in telemetry: {_last_warm_from_telemetry()}")
    lines.append(f"**nvidia-smi (used, total, util):** {st.get('gpu') or 'n/a'}")
    lines.append(f"**Time:** {time.strftime('%H:%M:%S')}")

    lines.append("**Ollama /api/ps:**")
    ps = st.get("ollama_ps") or []
    if not ps:
        lines.append("- (nothing loaded)")
    for e in ps:
        if not isinstance(e, dict):
            continue
        if "error" in e:
            lines.append(f"- error: {e['error']}")
            continue
        name = e.get("name") or e.get("model") or "?"
        size = e.get("size") or 0
        vram = e.get("size_vram") or 0
        pct = f"{100.0 * vram / size:.0f}% on GPU" if size else "GPU share n/a"
        ctx = e.get("context_length") or (e.get("details") or {}).get("context_length") or "?"
        expires = str(e.get("expires_at") or "")[:19].replace("T", " ")
        lines.append(f"- `{name}`: {_fmt_gb(vram)} of {_fmt_gb(size)} ({pct}), context {ctx}"
                     + (f", expires {expires}" if expires else ""))

    lines.append("**LM Studio /api/v0/models:**")
    lm = st.get("lms_models") or []
    if not lm:
        lines.append("- (no models reported)")
    for m in lm:
        if not isinstance(m, dict):
            continue
        if "error" in m:
            lines.append(f"- error: {m['error']}")
            continue
        lines.append(f"- `{m.get('id', '?')}` ({m.get('type', '?')}): {m.get('state', '?')}")
    v1 = st.get("lms_v1_ids") or []
    lines.append(f"**LM Studio /v1/models:** {len(v1)} ids" + (f": {', '.join(f'`{i}`' for i in v1[:12])}" if v1 else ""))
    tags = [e for e in (st.get("ollama_tags") or []) if isinstance(e, dict) and "error" not in e]
    lines.append(f"**Ollama /api/tags:** {len(tags)} models on disk")

    if state.PROFILE is not None:
        stale = state._stale_indexes()
        idx = ", ".join(f"`{k}` {'STALE or missing' if k in stale else 'fresh'} ({state.INDEX_USERS.get(k, '?')})"
                        for k in index.INDEX_KEYS)
        n, dsha, fresh = state._digest_state()
        lines.append(f"**Profile:** {state.PROFILE.name or '?'} from `{state.PROFILE.path}` "
                     f"(sha {state.PROFILE.sha[:8]}); indexes: {idx}"
                     + ("; rebuild needed" if stale else "")
                     + f"; sources (profile + transcript + reflections): {sources_state()}")
        lines.append(f"**Digest:** {n} chars, built by `{config.spec('qwen3_long').name}` for sha "
                     f"{(dsha or 'none')[:8]} ({'fresh' if fresh else 'STALE or missing: Rebuild digest (force)'})")
    elif state.PROFILE_ERROR:
        lines.append(f"**Profile:** not loaded ({state.PROFILE_ERROR})")
    try:
        lines.append(reflections_note())
    except Exception as e:  # noqa: BLE001
        lines.append(f"**Reflections:** unreadable ({type(e).__name__})")
    lines.append("**Models and jobs (registry):**")
    lines.append(models_table_markdown(st))
    return "\n".join(lines)


def status_tiles_html(st: dict) -> str:
    """The Status tab's four tiles from a MANAGER.status() dict: GPU memory (with a meter), heartbeat, LM Studio and
    Ollama. A <dl> of <div data-state><dt>label</dt><dd>value</dd><dd>note</dd></div> groups, styled by
    static/tabs/status.css; every value is escaped. /status keeps returning its markdown unchanged."""
    from twin.ui import frame   # frame imports this module
    esc = html.escape

    def tile(label: str, value: str, note: str, state_: str = "", extra: str = "") -> str:
        attr = f' data-state="{state_}"' if state_ else ""
        return f"<div{attr}><dt>{esc(label)}</dt><dd>{esc(value)}{extra}</dd><dd>{esc(note)}</dd></div>"

    used, total, util = frame._gpu_mib(st.get("gpu") or "")
    total = total or frame.GPU_TOTAL_MIB
    if used is None:
        gpu = tile("GPU memory", "n/a", "nvidia-smi gave no reading")
    else:
        pct = max(0.0, min(100.0, 100.0 * used / total))
        meter = f'<span data-meter aria-hidden="true"><span style="width: {pct:.0f}%"></span></span>'
        gpu = tile("GPU memory", f"{used / 1024:.1f} of {total / 1024:.0f} GB",
                   f"{util}% utilisation" if util is not None else f"{used} MiB used", extra=meter)
    hb = frame.heartbeat_state(st)
    active = st.get("active_tab") or "none"
    key = st.get("active_key")
    heartbeat = tile("Heartbeat", hb, f"active tab {active}" + (f", {key}" if key else ""),
                     {"ready": "ok", "loading": "warn", "busy": "warn"}.get(hb, ""))
    lms, oll = frame._loaded_lists(st)
    oll = [o.replace("`", "") for o in oll]
    lm_studio = tile("LM Studio", f"{len(lms)} loaded" if lms else "nothing loaded", ", ".join(lms) or "idle",
                     "ok" if lms else "")
    ollama = tile("Ollama", f"{len(oll)} loaded" if oll else "nothing loaded", ", ".join(oll) or "idle",
                  "ok" if oll else "")
    return f"<dl>{gpu}{heartbeat}{lm_studio}{ollama}</dl>"


def status_tiles_handler() -> str:
    """Private 5 s tick for the tiles (GETs + nvidia-smi only); never raises."""
    try:
        return status_tiles_html(MANAGER.status())
    except Exception:  # noqa: BLE001
        state._log_exc("status tiles")
        return ""


def status_refresh():
    """(status markdown, telemetry rows)."""
    try:
        rows = telemetry.as_rows(state.TELEMETRY_ROWS)
    except Exception:  # noqa: BLE001
        state._log_exc("telemetry.as_rows")
        rows = []
    return status_markdown(), rows


def free_gpu_handler():
    """Stop every Ollama model and unload LM Studio; clear the active tab so the heartbeat does not undo it."""
    try:
        MANAGER.set_active_tab("")
        done = MANAGER.free_all()
        note = "Free GPU: " + ("; ".join(done) if done else "nothing to do") + " (active tab cleared: select a tab to re-warm)"
    except Exception as e:  # noqa: BLE001
        state._log_exc("free_all")
        note = state._err_md(e)
    return status_markdown(note)


def warm_handler(tab):
    """Warm the model of the chosen tab ("active" = the active tab, else the last tab that had a model); the
    active tab is left unchanged. Skips (no model call) when TWIN_NO_WARM=1."""
    tab = (tab or "").strip().lower()
    if tab in ("", "active"):
        tab = MANAGER.active_tab if MANAGER.active_key() else (MANAGER.last_model_tab or "")
    key = MANAGER.tab_key(tab)
    if not key:
        return status_markdown(f"Warm: no model for tab {tab or 'none'!r}; select Ask/Decide/Act/See first "
                               f"or pick a tab in the dropdown.")
    if state.no_warm():
        return status_markdown(f"Warm: {NO_WARM_NOTE} ({key} for tab {tab} not loaded)")
    t0 = time.perf_counter()
    try:
        MANAGER.warm(key)
        note = f"Warm: {key} ({config.spec(key).name}) for tab {tab} ready in {time.perf_counter() - t0:.1f} s"
    except Exception as e:  # noqa: BLE001
        state._log_exc(f"warm {key}")
        note = state._err_md(e)
    return status_markdown(note)


def rebuild_index_handler():
    """Rebuild the three indexes, chunks.json, the reflections draft and the digest for the profile on disk
    (``index.build_all(profile, True, with_reflections=True)``); reset caches. Returns (status markdown, header
    markdown) so the stale warnings clear without a page reload; the note ends with the refreshed redaction
    report summary. ``RedactionRequired`` / ``LeakError`` show their message. Skips (no model call) when
    TWIN_NO_WARM=1.

    Unchanged since before personas (twin.personas): still resolves the transcript the default way (real
    transcript, else Mara's example). For a persona with no transcript of its own, use Switch persona instead,
    which passes that persona's own no_transcript/reflections_path to build_all."""
    if state.no_warm():
        return status_markdown(f"Rebuild index + digest: {NO_WARM_NOTE}"), state.header_markdown()
    t0 = time.perf_counter()
    try:
        prof = profile_mod.load_profile()
        index.build_all(prof, True, with_reflections=True)
        state.load_app_profile()
        resets = state._reset_pipeline_caches()
        note = (f"Rebuilt nomic, gemma and lms_nomic indexes, chunks.json, reflections draft and digest for "
                f"`{prof.path}` in {time.perf_counter() - t0:.0f} s; caches reset: {', '.join(resets) or 'none'} "
                f"(decide/see re-read the profile by sha).")
    except (index.RedactionRequired, index.LeakError) as e:
        state._log_exc("build_all")
        note = f"Rebuild stopped ({type(e).__name__}): {str(e)[:500]}"
    except Exception as e:  # noqa: BLE001
        state._log_exc("build_all")
        note = state._err_md(e)
    try:
        note += f" Redaction report: {redaction_report_summary()}"
    except Exception as e:  # noqa: BLE001
        note += f" Redaction report: unreadable ({type(e).__name__})"
    return status_markdown(note), state.header_markdown()


def rebuild_digest_handler():
    """Force a fresh digest with qwen3:8b (40960 ctx) even when the sha already matches; reset caches.
    Skips (no model call) when TWIN_NO_WARM=1."""
    if state.no_warm():
        return status_markdown(f"Rebuild digest: {NO_WARM_NOTE}"), state.header_markdown()
    t0 = time.perf_counter()
    try:
        prof = profile_mod.load_profile()
        text = index.rebuild_digest(prof, force=True)
        state.load_app_profile()
        resets = state._reset_pipeline_caches()
        note = (f"Rebuilt the digest with `{config.spec('qwen3_long').name}` for sha {prof.sha[:8]}: {len(text)} chars "
                f"in {time.perf_counter() - t0:.0f} s; caches reset: {', '.join(resets) or 'none'}.")
    except Exception as e:  # noqa: BLE001
        state._log_exc("rebuild_digest")
        note = state._err_md(e)
    return status_markdown(note), state.header_markdown()


def persona_choices() -> list[tuple[str, str]]:
    """(label, slug) pairs for the Persona dropdown; file reads only, seeds the registry on first call."""
    try:
        return personas.choices()
    except Exception:  # noqa: BLE001
        state._log_exc("persona_choices")
        return []


def persona_switch_handler(slug):
    """Copy the chosen persona's profile into data/twin_profile.md and rebuild for IT (twin.personas.switch);
    reset caches. Returns (status markdown, header markdown, dropdown update) so the choice snaps back to
    whatever is actually active if the switch failed. The header text updates live; the masthead monogram next
    to it is set once at boot (twin.ui.frame.build_app), so it keeps showing the persona active when the app
    started until the app is restarted. Skips (no model call) when TWIN_NO_WARM=1."""
    if state.no_warm():
        note = f"Switch persona: {NO_WARM_NOTE}"
        return status_markdown(note), state.header_markdown(), gr.update(choices=persona_choices(), value=personas.active_slug())
    t0 = time.perf_counter()
    try:
        entry = personas.switch(slug)
        state.load_app_profile()
        resets = state._reset_pipeline_caches()
        note = (f"Switched persona to **{entry.name}** (`{entry.slug}`): rebuilt nomic, gemma and lms_nomic "
                f"indexes, chunks.json and digest from `{entry.profile_path.name}` in "
                f"{time.perf_counter() - t0:.0f} s; caches reset: {', '.join(resets) or 'none'}. The masthead "
                "monogram was set at boot and needs an app restart to change; the header text above it is "
                "already current.")
    except (personas.PersonaError, index.RedactionRequired, index.LeakError) as e:
        state._log_exc("persona_switch")
        note = f"Switch persona stopped ({type(e).__name__}): {str(e)[:500]}"
    except Exception as e:  # noqa: BLE001
        state._log_exc("persona_switch")
        note = state._err_md(e)
    return status_markdown(note), state.header_markdown(), gr.update(choices=persona_choices(), value=personas.active_slug())


def persona_import_handler(file):
    """Validate and register an uploaded .md as a new persona (twin.personas.import_md); never switches to it
    or builds anything. Returns (status markdown, dropdown update) so the new persona appears as a choice
    without changing which one is active. No model call, so this is not gated by TWIN_NO_WARM."""
    if file is None:
        return status_markdown("Import persona: no file selected."), gr.update(choices=persona_choices())
    path = Path(getattr(file, "name", file))
    try:
        entry = personas.import_md(path.read_bytes(), path.name)
        note = f"Imported persona **{entry.name}** (`{entry.slug}`) from `{path.name}`; not switched to yet."
    except personas.PersonaError as e:
        note = f"Import persona stopped: {e}"
    except Exception as e:  # noqa: BLE001
        state._log_exc("persona_import")
        note = state._err_md(e)
    return status_markdown(note), gr.update(choices=persona_choices())


def build(ctx) -> dict:
    """Render the Status tab and wire /status, /free_gpu, /warm, /rebuild_index, /rebuild_digest, /audit_tail,
    /redaction_report and the private 5 s tick on the frame's timer (``ctx.timer``); rebuilds also refresh
    ``ctx.header_md``. The safeguards block (audit tail, redaction report) sits first so it is visible without
    scrolling past the model table.

    Layout (docs/PLAN_FINISH.md P4; styles in static/tabs/status.css): the four tiles (#status-tiles: GPU memory,
    heartbeat, LM Studio, Ollama; a second private, GET-only tick redraws them), the safeguards row (#status-safeguards, two
    columns that stack when narrow) with the audit tail (.twin-table) and the redaction report, each with its refresh
    button at natural width; the status readout on one sheet (#status-md, .twin-card) ending in the models table; the
    control row with Free GPU first and the only filled button (#status-controls); the two rebuilds on their own row
    at the right (#status-maintenance, .twin-caution: they load models and rewrite data files); the telemetry table.
    Labels, values, api_names, queues and event wiring are unchanged (the DEMO CONTRACT)."""
    with gr.Tab("Status", id="status", elem_id="tab-status") as tab:
        tiles = gr.HTML(status_tiles_handler(), elem_id="status-tiles")
        with gr.Row(elem_id="status-safeguards", elem_classes=["twin-split"]):
            with gr.Column(scale=3, min_width=360, elem_id="status-audit"):
                audit_counts_md = gr.Markdown(audit_counts_markdown(), line_breaks=True, elem_id="status-audit-counts")
                audit_df = gr.Dataframe(value=audit_rows(), headers=list(AUDIT_HEADERS),
                                        label=f"Audit tail (last {AUDIT_ROWS} requests, newest first)",
                                        interactive=False, wrap=True, max_height=260,
                                        elem_id="status-audit-tail", elem_classes=["twin-table"])
                with gr.Row(elem_classes=["twin-actions"]):
                    audit_refresh_btn = gr.Button("Refresh audit tail", scale=0, elem_id="status-audit-refresh")
            with gr.Column(scale=2, min_width=300, elem_id="status-redaction"):
                redaction_md = gr.Markdown(redaction_report_markdown(), line_breaks=True,
                                           elem_id="status-redaction-report")
                with gr.Row(elem_classes=["twin-actions"]):
                    redaction_btn = gr.Button("Refresh redaction report", scale=0, elem_id="status-redaction-refresh")
        status_md = gr.Markdown(status_markdown(), line_breaks=True, elem_id="status-md", elem_classes=["twin-card"])
        with gr.Row(elem_id="status-controls", elem_classes=["twin-actions"]):
            free_btn = gr.Button("Free GPU", variant="primary", scale=0, elem_id="status-free-gpu")
            warm_tab_dd = gr.Dropdown(choices=state.WARM_CHOICES, value="active", label="Tab to warm", scale=0,
                                      min_width=160, elem_id="status-warm-tab")
            warm_btn = gr.Button("Warm current tab", scale=0, elem_id="status-warm")
            status_refresh_btn = gr.Button("Refresh", scale=0, elem_id="status-refresh", elem_classes=["twin-quiet"])
        with gr.Row(elem_id="status-maintenance", elem_classes=["twin-actions"]):
            rebuild_btn = gr.Button("Rebuild index + digest", scale=0, elem_id="status-rebuild-index",
                                    elem_classes=["twin-caution"])
            rebuild_digest_btn = gr.Button("Rebuild digest (force, qwen3:8b)", scale=0, elem_id="status-rebuild-digest",
                                           elem_classes=["twin-caution"])
        with gr.Row(elem_id="status-persona", elem_classes=["twin-actions"]):
            persona_dd = gr.Dropdown(choices=persona_choices(), value=personas.active_slug(), label="Persona",
                                     scale=0, min_width=200, elem_id="status-persona-dd")
            persona_switch_btn = gr.Button("Switch persona", scale=0, elem_id="status-persona-switch",
                                           elem_classes=["twin-caution"])
            persona_file = gr.File(label="Import persona (.md)", file_types=[".md"], scale=0,
                                   min_width=220, elem_id="status-persona-file")
            persona_import_btn = gr.Button("Import persona", scale=0, elem_id="status-persona-import")
        telemetry_df = gr.Dataframe(value=telemetry.as_rows(state.TELEMETRY_ROWS), headers=state.TELEMETRY_HEADERS,
                                    label=f"Telemetry (last {state.TELEMETRY_ROWS} calls)", interactive=False,
                                    elem_id="status-telemetry", elem_classes=["twin-table"])

    status_refresh_btn.click(status_refresh, inputs=None, outputs=[status_md, telemetry_df], api_name="status")
    free_btn.click(free_gpu_handler, inputs=None, outputs=[status_md], api_name="free_gpu", concurrency_id="gpu")
    warm_btn.click(warm_handler, inputs=[warm_tab_dd], outputs=[status_md], api_name="warm",
                   concurrency_id="gpu")
    rebuild_btn.click(rebuild_index_handler, inputs=None, outputs=[status_md, ctx.header_md],
                      api_name="rebuild_index", concurrency_id="gpu")
    rebuild_digest_btn.click(rebuild_digest_handler, inputs=None, outputs=[status_md, ctx.header_md],
                             api_name="rebuild_digest", concurrency_id="gpu")
    persona_switch_btn.click(persona_switch_handler, inputs=[persona_dd],
                             outputs=[status_md, ctx.header_md, persona_dd], api_name="persona_switch",
                             concurrency_id="gpu")
    persona_import_btn.click(persona_import_handler, inputs=[persona_file], outputs=[status_md, persona_dd],
                             api_name="persona_import")
    audit_refresh_btn.click(audit_tail_handler, inputs=None, outputs=[audit_df, audit_counts_md],
                            api_name="audit_tail")
    redaction_btn.click(redaction_report_handler, inputs=None, outputs=[redaction_md], api_name="redaction_report")
    ctx.timer.tick(status_refresh, inputs=None, outputs=[status_md, telemetry_df], api_name=False)
    ctx.timer.tick(status_tiles_handler, inputs=None, outputs=[tiles], api_name=False, show_progress="hidden")
    return {"tab": tab, "md": status_md, "tiles": tiles, "free_btn": free_btn, "warm_dd": warm_tab_dd, "warm_btn": warm_btn,
            "refresh_btn": status_refresh_btn, "rebuild_btn": rebuild_btn, "rebuild_digest_btn": rebuild_digest_btn,
            "telemetry": telemetry_df, "audit_counts": audit_counts_md, "audit": audit_df,
            "audit_btn": audit_refresh_btn, "redaction": redaction_md, "redaction_btn": redaction_btn,
            "persona_dd": persona_dd, "persona_switch_btn": persona_switch_btn, "persona_file": persona_file,
            "persona_import_btn": persona_import_btn}
