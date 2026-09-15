"""Shared UI state and helpers (moved verbatim from the phase-1 ``app.py`` monolith).

``PROFILE`` / ``PROFILE_ERROR`` are rebound by ``load_app_profile()``, so other modules must read them through
this module (``state.PROFILE``) and never ``from .state import PROFILE``. ``no_warm()`` and ``theme_pref()``
delegate to ``twin.config`` and are read at call time.
"""
from __future__ import annotations

import html
import re
import sys
import traceback
from pathlib import Path

import gradio as gr

from twin import clients, config, index
from twin import profile as profile_mod
from twin.pipelines import act, ask, digest, evals

# Which tab searches which index (for the stale-index warnings).
INDEX_USERS = {"nomic": "Ask, See, Eval", "gemma": "Eval retrieval bake-off", "lms_nomic": "Act, Decide"}

TELEMETRY_HEADERS = ["time", "tab", "model", "load_ms", "prompt_tokens", "eval_tokens", "tok_s", "wall_ms", "ok"]
TELEMETRY_ROWS = 30
WARM_CHOICES = ["active", "ask", "decide", "act", "see"]
_PROGRESS_RE = re.compile(r"^\[(\d+)/(\d+)\]")


# ---- switches (read at call time) --------------------------------------------------------
def no_warm() -> bool:
    """TWIN_NO_WARM=1: no tab pre-warm, no heartbeat thread, /warm and /rebuild_* skip (twin.config.no_warm)."""
    return config.no_warm()


def theme_pref() -> str:
    """'light' | 'dark' | '' from TWIN_THEME (twin.config.theme_pref)."""
    return config.theme_pref()


# ---- logging / errors --------------------------------------------------------------
def _log_exc(where: str) -> None:
    """Print the current exception with its traceback to stderr, prefixed with where it happened."""
    print(f"[app] {where} failed:\n{traceback.format_exc()}", file=sys.stderr, flush=True)


def _err_text(e: BaseException) -> str:
    """Plain one-line error text for text boxes."""
    return f"Error: {type(e).__name__}: {e}"


def _err_md(e: BaseException) -> str:
    """Markdown error line for Markdown components."""
    return f"**Error:** `{type(e).__name__}: {str(e)[:500]}`"


# ---- profile (header + eval question list) --------------------------------------------
PROFILE: profile_mod.Profile | None = None
PROFILE_ERROR = ""


def load_app_profile() -> None:
    """(Re)load the profile used by the header and the Eval question list; never raises."""
    global PROFILE, PROFILE_ERROR
    try:
        PROFILE = profile_mod.load_profile()
        PROFILE_ERROR = ""
    except Exception as e:  # noqa: BLE001
        _log_exc("load_profile")
        PROFILE = None
        PROFILE_ERROR = f"{type(e).__name__}: {e}"


def _stale_indexes() -> list[str]:
    """Index keys (index.INDEX_KEYS order) that are missing or built for another profile sha."""
    if PROFILE is None:
        return []
    out = []
    for key in index.INDEX_KEYS:
        try:
            stale = index.is_stale(key, PROFILE)
        except Exception:  # noqa: BLE001
            stale = True
        if stale:
            out.append(key)
    return out


def _digest_state() -> tuple[int, str | None, bool]:
    """(digest chars, digest sha, fresh) for the profile on disk."""
    try:
        text = digest.load_digest()
        sha = digest.digest_sha()
    except Exception:  # noqa: BLE001
        return 0, None, False
    fresh = bool(PROFILE is not None and sha and sha == PROFILE.sha)
    return len(text), sha, fresh


def _profile_warnings() -> list[str]:
    """Header warnings: example profile in use, stale indexes (each named with the tabs that use it), stale
    digest, profile parse failure."""
    warns: list[str] = []
    if not config.PROFILE_PATH.exists():
        loaded = Path(PROFILE.path).name if PROFILE is not None and PROFILE.path else profile_mod.resolve_profile_path().name
        warns.append(f"`{config.PROFILE_PATH.name}` is missing: using the example profile "
                     f"`{loaded}`. Create the real one with `docs/opus_interview_prompt.md`.")
    for key in _stale_indexes():
        warns.append(f"The `{key}` index (used by {INDEX_USERS.get(key, '?')}) is missing or stale for this "
                     "profile: open **Status** and click **Rebuild index + digest** "
                     "(or run `python -m twin.index --build all --digest`).")
    if PROFILE is not None:
        n, _sha, fresh = _digest_state()
        if not fresh:
            warns.append("The digest (`data/digest.md`, built by qwen3:8b) is "
                         f"{'missing' if not n else 'stale'} for this profile: Status -> **Rebuild digest (force)**.")
    if PROFILE_ERROR:
        warns.append(f"Profile could not be loaded: `{PROFILE_ERROR}`")
    return warns


def _inline_html(text: str) -> str:
    """Escape `text` and render its **bold** and `code` spans as HTML (Markdown is not parsed inside an HTML block)."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", out)


def _reading(label: str, value: str, note: str = "", state_: str = "") -> str:
    """One label-over-value reading: <div class="twin-reading-<state>"><dt>label</dt><dd>value</dd><dd>note</dd></div>.
    A class, not a data attribute: Gradio's Markdown sanitizer keeps class and drops data-*."""
    attr = f' class="twin-reading-{state_}"' if state_ else ""
    tail = f"<dd>{html.escape(note)}</dd>" if note else ""
    return f"<div{attr}><dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>{tail}</div>"


def header_readings_html() -> str:
    """The masthead's three readings (profile size, index freshness, digest freshness) as a <dl>; '' without a profile."""
    if PROFILE is None:
        return ""
    stale = _stale_indexes()
    n, _sha, fresh = _digest_state()
    keys = list(index.INDEX_KEYS)
    return ('<dl class="twin-readings">'
            + _reading("Profile", f"{len(PROFILE.chunks)} chunks",
                       f"{len(PROFILE.decisions)} decisions, {len(PROFILE.eval)} eval questions")
            + _reading("Indexes", f"{len(stale)} of {len(keys)} stale" if stale else "fresh",
                       ", ".join(stale or keys), "warn" if stale else "ok")
            + _reading("Digest", "fresh" if fresh else ("stale" if n else "missing"),
                       f"{n:,} chars" if n else "not built", "ok" if fresh else "warn")
            + "</dl>")


def header_markdown() -> str:
    """The masthead text: the title line, the three readings, a closed disclosure with the profile file (and the
    consent date when the profile records one) and, when there are any, the warnings in a disclosure that starts open
    so a warning is never hidden. Blocks are separated by blank lines; the HTML blocks each sit on one line."""
    name = PROFILE.name if PROFILE is not None and PROFILE.name else "(no profile)"
    blocks = [f"## Digital twin: {name}"]
    readings = header_readings_html()
    if readings:
        blocks.append(readings)
    if PROFILE is not None:
        consent = getattr(PROFILE, "consent", "") or ""
        detail = f"Profile `{PROFILE.path}`, sha {PROFILE.sha[:8]}." + (f" Consent recorded: {consent}." if consent else "")
        summary = "Profile file and consent" if consent else "Profile file"
        blocks.append(f'<details class="twin-profile-details"><summary>{summary}</summary>'
                      f"<p>{_inline_html(detail)}</p></details>")
    warns = _profile_warnings()
    if warns:
        body = "".join(f"<p>{_inline_html('**Warning:** ' + w)}</p>" for w in warns)
        label = f"{len(warns)} warning" + ("" if len(warns) == 1 else "s")
        blocks.append(f'<details class="twin-warnings" open><summary>{label}</summary>{body}</details>')
    return "\n\n".join(blocks)


def _eval_qid_choices() -> list[tuple[str, str]]:
    """Dropdown choices (label, qid) from the profile's Eval section."""
    if PROFILE is None:
        return []
    return [(f"{q.qid}: {q.question[:70]}", q.qid) for q in PROFILE.eval]


def _candidate_choices() -> list[tuple[str, str]]:
    """Dropdown choices (label, key) for the bake-off candidates."""
    out = []
    for key in evals.CANDIDATES:
        try:
            out.append((f"{key} = {config.spec(key).name}", key))
        except KeyError:
            out.append((key, key))
    return out


# ---- small shared adapters -----------------------------------------------------------
def _trace_markdown(lines: list[str]) -> str:
    """Bullet list for the trace accordion."""
    return "\n".join(f"- {ln}" for ln in lines) if lines else "_(no trace yet)_"


def _clean_rows(rows: list[list]) -> list[list]:
    """None -> "" so the Dataframe shows blanks instead of NaN."""
    return [["" if v is None else v for v in row] for row in rows]


def _progress_callback(progress: gr.Progress):
    """Adapt the pipelines' str progress callback to gr.Progress ("[i/n] ..." lines become a fraction)."""
    def cb(text: str) -> None:
        m = _PROGRESS_RE.match(text or "")
        try:
            if m:
                progress((int(m.group(1)), int(m.group(2))), desc=text)
            else:
                progress(None, desc=text)
        except Exception:  # noqa: BLE001
            pass
        print(f"[eval] {text}", flush=True)
    return cb


def claude_judge_markdown() -> str:
    """One line saying whether the optional Claude ceiling judge can run (key presence only; never the key)."""
    if clients.anthropic_client.available():
        return f"Claude ceiling judge: **enabled** ({config.ANTHROPIC_MODEL}; ANTHROPIC_API_KEY is set)."
    return "Claude ceiling judge: **disabled** (ANTHROPIC_API_KEY not set or the `anthropic` package is missing)."


def _reset_pipeline_caches() -> list[str]:
    """Drop the pipelines' cached profiles after a rebuild (only the resets each module exposes)."""
    done = []
    for mod, fn_name in ((ask, "reset_profile_cache"), (act, "reload_profile")):
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            fn()
            done.append(f"{mod.__name__.rsplit('.', 1)[-1]}.{fn_name}()")
    return done
