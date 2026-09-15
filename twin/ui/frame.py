"""Frame of the digital-twin UI: masthead (monogram + header), gpu note, status strip (gr.Sidebar), tab shell and
hooks (styles: static/tabs/frame.css). Eight tabs in order: Onboarding, Ask, Decide, Act, See, Items, Eval, Status.

UI wiring only: every model call lives in ``twin.pipelines.*`` and the GPU sequencing in ``twin.gpu``.
Run from the project root (plan section 4)::

    $env:PYTHONUTF8=1; $env:GRADIO_ANALYTICS_ENABLED="False"; python app.py --port 7861

Endpoints (``api_name``) so ``gradio_client`` can drive the app, ``Client("http://127.0.0.1:7861")``:

    /ask                 message: str, history: list[message], use_q8: bool, temperature: float, use_checker: bool
                         -> chatbot: list[message], trace_md: str, checker_md: str, hint_md: str, textbox: str ("")
                         (streams: tokens land in the last assistant message; a ``message`` on the wire is
                         {"role": "user"|"assistant", "content": [{"type": "text", "text": "..."}]})
    /ask_clear           -> chatbot [], trace_md "", checker_md "", hint_md "", textbox ""
    /decide_b1           situation: str -> result_md: str, result_json: dict   (+ session gr.State = result dict)
    /decide_b2           situation: str, option_a: str, option_b: str -> result_md: str, result_json: dict (+ state)
    /say_it              (session gr.State from the last /decide_b1 or /decide_b2) -> text: str
    /act                 request: str -> answer: str, trace_md: str
    /polish              text: str -> text: str
    /see                 image: PIL image / file -> description: str, reaction: str, trace_md: str
    /eval_show           -> summary_df (evals.SUMMARY_HEADERS), retrieval_df (evals.RETRIEVAL_HEADERS)   (cached, no model)
    /eval_voice_rerun    use_claude: bool -> summary_df, retrieval_df, note_md: str   (~6 min, reports progress;
                         the Claude ceiling judge runs only when the box is ticked AND ANTHROPIC_API_KEY is set)
    /eval_retrieval_rerun-> summary_df, retrieval_df, note_md: str
    /eval_live           candidate: str (evals.CANDIDATES key), qid: str (Q-NN) -> result: dict   (~20 s; includes
                         the qwen2.5 consistency checker verdict under "checker")
    /status              -> status_md: str, telemetry_df (TELEMETRY_HEADERS, last 30 calls)   (GETs only)
    /free_gpu            -> status_md: str   (also clears the active tab so the heartbeat does not undo it)
    /warm                tab: str ("active" | "ask" | "decide" | "act" | "see") -> status_md: str
                         ("active" = the active tab, or the last tab that had a model when Status/Eval is open;
                         "skipped: TWIN_NO_WARM=1" when the switch is set)
    /rebuild_index       -> status_md: str, header_md: str   (twin.index.build_all for the ACTIVE persona, caches reset)
    /rebuild_digest      -> status_md: str, header_md: str   (twin.index.rebuild_digest(profile, force=True): qwen3:8b)
    /persona_switch      slug: str -> status_md: str, header_md: str, persona_dd: Dropdown update
                         (twin.personas.switch: copies data/personas/<slug>.md into data/twin_profile.md and
                         rebuilds for it; the masthead monogram is set once at boot and needs an app restart)
    /persona_import      file: file -> status_md: str, persona_dd: Dropdown update
                         (twin.personas.import_md: registers a new persona from an uploaded .md; never switches
                         or builds)

The 5 s timer tick (Status tab + status strip, GETs only), the tab-select pre-warm hooks, the page-load hook and
the Ask Enter-key submit are private (``api_name=False``). Items and Onboarding are placeholders until the
pipelines workflow (``READY = False``: one card, no endpoints).
Booting the app loads no model: the heartbeat re-warms only the ACTIVE tab's model. The page-load hook marks
"ask" (the tab shown first) active without loading anything, unless a tab is already active (a second window never
hijacks a demo in progress); a tab's model is warmed when the user selects that tab. Selecting Status does not
change the active tab (it is a monitoring tab meant to stay open in a second window); selecting Eval clears it so
the bake-off is not interrupted by re-warms. The Ask Q8 toggle switches the heartbeat target to stheno_q8.
Switches (read at call time): ``TWIN_NO_WARM=1`` turns every warm path into bookkeeping (tab select, heartbeat,
/warm, /rebuild_*); ``TWIN_THEME=light|dark`` forces the theme when the page has no ``__theme`` query parameter
(without it the token sheet's ``default_theme`` does).
"""
from __future__ import annotations

import json
import re
import time
import types

import gradio as gr

from twin import config
from twin.gpu import MANAGER, TAB_MODEL
from twin.ui import act, ask, decide, evals, items, onboarding, see, state, status

TAB_IDS = ("onboarding", "ask", "decide", "act", "see", "items", "eval", "status")
TAB_LABELS = {"onboarding": "Onboarding", "ask": "Ask", "decide": "Decide", "act": "Act", "see": "See",
              "items": "Items", "eval": "Eval", "status": "Status"}
TAB_MODULES = {"onboarding": onboarding, "ask": ask, "decide": decide, "act": act, "see": see, "items": items,
               "eval": evals, "status": status}
# Tabs whose select hook runs on the gpu queue (pre-warm), exactly as the monolith wired them.
GPU_SELECT_TABS = ("ask", "decide", "act", "see", "eval")
# Endpoints the pipelines workflow (docs/PLAN_UNIFIED.md workflow B) adds on top of the phase-1 baseline
# (scripts/dev/view_api_baseline.json); tests/test_ui_build.py allows exactly baseline + these.
NEW_API_NAMES = frozenset({"items_save", "items_run", "items_score", "onboarding_check", "audit_tail",
                           "redaction_report", "persona_switch", "persona_import"})
# Phase-1 endpoints that gain the condition dropdown as their LAST input (plan 3.4); positional calls still work.
CONDITION_ENDPOINTS = frozenset({"ask", "decide_b1", "decide_b2", "eval_live"})
GPU_TOTAL_MIB = 8192
HEARTBEAT_STATES = ("idle", "loading", "ready", "busy")


# ---- status strip (GETs only) ----------------------------------------------------------
def _gpu_mib(line: str) -> tuple[int | None, int | None, int | None]:
    """(used MiB, total MiB, util %) from an nvidia-smi line like '1234 MiB, 8192 MiB, 3 %'."""
    nums = [int(x) for x in re.findall(r"\d+", line or "")]
    used = nums[0] if len(nums) > 0 else None
    total = nums[1] if len(nums) > 1 else None
    util = nums[2] if len(nums) > 2 else None
    return used, total, util


def _key_loaded(st: dict, key: str | None) -> bool:
    """Whether the registry model ``key`` shows as loaded in the status dict (Ollama /api/ps or LM Studio)."""
    if not key:
        return False
    try:
        s = config.spec(key)
    except KeyError:
        return False
    if s.runtime == "ollama":
        for e in st.get("ollama_ps") or []:
            if isinstance(e, dict) and "error" not in e:
                m = config.by_name(e.get("name") or e.get("model") or "")
                if m is not None and m.key == key:
                    return True
        return False
    if s.runtime == "lms":
        for m in st.get("lms_models") or []:
            if isinstance(m, dict) and m.get("id") == s.name and m.get("state") == "loaded":
                return True
    return False


def heartbeat_state(st: dict) -> str:
    """idle | loading | ready | busy from a MANAGER.status() dict: busy while a session/warm holds the GPU
    (loading until its model shows as loaded), ready when the active tab's model is loaded, else idle."""
    busy = bool(st.get("busy"))
    key = st.get("busy_key") if busy else st.get("active_key")
    loaded = _key_loaded(st, key)
    if busy:
        return "busy" if loaded else "loading"
    return "ready" if loaded else "idle"


def _loaded_lists(st: dict) -> tuple[list[str], list[str]]:
    """(LM Studio loaded ids, Ollama loaded models with GPU percent and context) for the strip."""
    lms = [str(m.get("id") or "?") for m in (st.get("lms_models") or [])
           if isinstance(m, dict) and "error" not in m and m.get("state") == "loaded"]
    oll: list[str] = []
    for e in st.get("ollama_ps") or []:
        if not isinstance(e, dict) or "error" in e:
            continue
        name = e.get("name") or e.get("model") or "?"
        size = e.get("size") or 0
        vram = e.get("size_vram") or 0
        pct = f"{100.0 * vram / size:.0f}% GPU" if size else "GPU share n/a"
        ctx = e.get("context_length") or (e.get("details") or {}).get("context_length") or "?"
        oll.append(f"`{name}` ({pct}, ctx {ctx})")
    return lms, oll


def strip_markdown() -> str:
    """Status strip text from MANAGER.status() (GETs + nvidia-smi only; never loads a model)."""
    try:
        st = MANAGER.status()
    except Exception as e:  # noqa: BLE001
        state._log_exc("strip status")
        st = {"gpu": "", "ollama_ps": [{"error": str(e)}], "lms_models": [], "active_tab": MANAGER.active_tab,
              "active_key": MANAGER.active_key(), "busy": getattr(MANAGER, "busy", False),
              "busy_key": getattr(MANAGER, "busy_key", None)}
    used, total, util = _gpu_mib(st.get("gpu") or "")
    if used is None:
        gpu = "n/a"
    else:
        gpu = f"{used} of {total or GPU_TOTAL_MIB} MiB" + (f", {util}% util" if util is not None else "")
    lms, oll = _loaded_lists(st)
    active = st.get("active_tab") or "none"
    key = st.get("active_key")
    hb = heartbeat_state(st)
    lines = [
        f"**GPU:** {gpu}",
        f"**LM Studio:** {', '.join(f'`{m}`' for m in lms) if lms else 'nothing loaded'}",
        f"**Ollama:** {', '.join(oll) if oll else 'nothing loaded'}",
        f"**Active tab:** {active}" + (f" ({key})" if key else ""),
        f"**Heartbeat:** {hb}" + (" (TWIN_NO_WARM=1)" if state.no_warm() else ""),
        f"_{time.strftime('%H:%M:%S')}_",
    ]
    return "\n".join(lines)


# ---- tab pre-warm -------------------------------------------------------------------
def make_tab_select(tab: str):
    """Handler for gr.Tab.select: mark the tab active and pre-warm its model; never raises.
    Status only reports (it must not steal the active tab from a demo window); Eval clears it.
    With TWIN_NO_WARM=1 only the bookkeeping happens."""
    def handler():
        if tab == "status":
            return (f"Status open; active tab stays {MANAGER.active_tab or 'none'} "
                    f"(heartbeat target {MANAGER.active_key() or 'none'}).")
        MANAGER.set_active_tab(tab)
        if state.no_warm():
            return f"Active tab: {tab}. Pre-warm skipped (TWIN_NO_WARM=1)."
        key = MANAGER.tab_key(tab)
        if not key:
            return f"Active tab: {tab}. No model to pre-warm (heartbeat paused)."
        t0 = time.perf_counter()
        try:
            MANAGER.warm(key)
            return (f"Active tab: {tab}. Pre-warmed {key} ({config.spec(key).name}) "
                    f"in {time.perf_counter() - t0:.1f} s.")
        except Exception as e:  # noqa: BLE001
            state._log_exc(f"pre-warm {key}")
            return f"Active tab: {tab}. Pre-warm of {key} failed: {type(e).__name__}: {str(e)[:300]}"
    return handler


def default_tab() -> str:
    """'onboarding' when that tab is functional and the real profile is missing, else 'ask'."""
    return "onboarding" if (onboarding.READY and not config.PROFILE_PATH.exists()) else "ask"


def _on_page_load(request: gr.Request | None = None):
    """Set the active tab on the first page load only (never loads a model) and honour ?tab=<id>."""
    tab = default_tab()
    try:
        wanted = (request.query_params.get("tab") if request is not None else None) or tab
        if wanted in TAB_IDS:
            tab = wanted
    except Exception:  # noqa: BLE001 - a bad query string must never break page load
        tab = default_tab()
    if MANAGER.active_tab is None and tab in TAB_MODEL:
        MANAGER.set_active_tab(tab)
    return gr.Tabs(selected=tab)


# ---- UI ----------------------------------------------------------------------------
def build_app() -> gr.Blocks:
    """Assemble the Blocks app: masthead (monogram + header), gpu note, status strip, one timer, the tabs and hooks."""
    state.load_app_profile()

    with gr.Blocks(title="Digital twin") as demo:
        with gr.Row(elem_id="twin-masthead"):  # layout only: the owner's monogram beside the persona header
            gr.HTML(avatar_html(getattr(state.PROFILE, "name", "")), elem_id="twin-avatar", scale=0, min_width=48)
            header_md = gr.Markdown(state.header_markdown(), line_breaks=True, elem_id="twin-header", min_width=0)
        gpu_note = gr.Markdown("GPU: idle. Select a tab to pre-warm its model.", elem_id="gpu-note")
        with gr.Sidebar(label="Status", open=True, elem_id="status-strip"):
            strip_md = gr.Markdown(strip_markdown(), line_breaks=True)
        timer = gr.Timer(5)
        ctx = types.SimpleNamespace(demo=demo, header_md=header_md, gpu_note=gpu_note, strip_md=strip_md, timer=timer)
        with gr.Tabs(selected=default_tab(), elem_id="twin-tabs") as tabs:
            parts = {tab_id: TAB_MODULES[tab_id].build(ctx) for tab_id in TAB_IDS}

        # ---- events: tab selects (private) ----
        for tab_id in GPU_SELECT_TABS:
            parts[tab_id]["tab"].select(make_tab_select(tab_id), inputs=None, outputs=gpu_note,
                                        api_name=False, concurrency_id="gpu")
        # Status: report only, no GPU queue slot (it must not wait behind a running turn to say so).
        parts["status"]["tab"].select(make_tab_select("status"), inputs=None, outputs=gpu_note, api_name=False)
        # Placeholder tabs get their (model-less) bookkeeping hook only once they are functional.
        for tab_id in ("onboarding", "items"):
            if getattr(TAB_MODULES[tab_id], "READY", False):
                parts[tab_id]["tab"].select(make_tab_select(tab_id), inputs=None, outputs=gpu_note,
                                            api_name=False)

        # ---- status strip: the same 5 s timer as the Status tab, GETs only ----
        timer.tick(strip_markdown, inputs=None, outputs=[strip_md], api_name=False)

        # Page load: the first tab shown is Ask and gr.Tab.select never fires for it, so mark it active here
        # (bookkeeping only, no model load) unless a tab is already active (a second window must not hijack).
        # A ?tab=<id> query parameter (one of TAB_IDS) opens that tab instead, e.g. a second window on
        # ?tab=status during a demo, or scripts/screenshot_tabs.ps1.
        demo.load(_on_page_load, inputs=None, outputs=[tabs], api_name=False)

    demo.twin_parts = parts   # type: ignore[attr-defined]  # per-tab component dicts for tests and tooling
    return demo


# Client-side twin of the ?tab= deep link: click the tab button as soon as it exists, so the switch does not
# wait for the page-load event round trip (a real click also fires the tab's pre-warm exactly like a user).
# When TWIN_THEME is set and the page has no __theme query parameter, the 'dark' class on document.body is
# toggled to match (Gradio's own theme switch keys on that class).
# ?nomotion=1 (scripts/screenshot_tabs.ps1 only) disables CSS transitions so headless Chrome, whose virtual-time
# budget is spent before the app mounts, captures the sidebar and its content push in their final state.
_TAB_JS_TEMPLATE = """
() => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('nomotion') === '1') {
    const style = document.createElement('style');
    style.textContent = '*, *::before, *::after { transition: none !important; }';
    document.head.appendChild(style);
  }
  const forcedTheme = __THEME__;
  if (forcedTheme && !params.get('__theme')) {
    const applyTheme = () => document.body.classList.toggle('dark', forcedTheme === 'dark');
    applyTheme();
    setTimeout(applyTheme, 500);
    setTimeout(applyTheme, 2000);
  }
  // Narrow viewports: collapse the status-strip sidebar once it mounts, so the header, the tab strip and the
  // active panel fit inside the width (the sidebar is open by default on wide screens).
  let collapsed = false;
  const collapseSidebar = (left) => {
    if (collapsed || window.innerWidth > 600) return;
    const toggle = document.querySelector('#status-strip button');
    if (toggle) { toggle.click(); collapsed = true; return; }
    if (left > 0) setTimeout(() => collapseSidebar(left - 1), 200);
  };
  collapseSidebar(100);
  // ?measure=1 (visual reviewers, scripts/screenshot_tabs.ps1 -Measure): write the document's scroll width into
  // a fixed #twin-measure box and the title, so `chrome --headless=new --dump-dom` at 400 px can prove there is
  // no horizontal scroll (scrollWidth <= innerWidth) without DevTools.
  if (params.get('measure') === '1') {
    const report = () => {
      let el = document.getElementById('twin-measure');
      if (!el) {
        el = document.createElement('div');
        el.id = 'twin-measure';
        el.setAttribute('style', 'position:fixed;left:0;bottom:0;z-index:9999;font:12px monospace;'
          + 'background:#fff;color:#000;padding:2px 4px;');
        document.body.appendChild(el);
      }
      const text = 'scrollWidth=' + document.documentElement.scrollWidth + ' innerWidth=' + window.innerWidth;
      el.textContent = text;
      document.title = text;
    };
    [2000, 5000, 9000].forEach((ms) => setTimeout(report, ms));
  }
  const tab = params.get('tab');
  const labels = {__LABELS__};
  const label = labels[tab];
  if (!label) return;
  const tryClick = (left) => {
    const btn = Array.from(document.querySelectorAll('button[role="tab"]'))
      .find((b) => b.textContent.trim() === label);
    if (btn) { btn.click(); return; }
    if (left > 0) setTimeout(() => tryClick(left - 1), 200);
  };
  tryClick(100);
}
"""


def sheet_default_theme() -> str:
    """The token sheet's ``default_theme`` ('light' | 'dark'); '' when the sheet cannot be read."""
    try:
        from twin.ui import theme as theme_mod
        return theme_mod.parse_tokens(theme_mod.resolve_tokens_path().read_text(encoding="utf-8"))["default_theme"]
    except Exception:  # noqa: BLE001 - a missing sheet must never break page load
        return ""


def tab_js(theme: str | None = None) -> str:
    """The page-load JS with the tab labels and the forced theme ('' = none). Default: TWIN_THEME, else the token
    sheet's default_theme; a ``__theme`` query parameter still wins in the browser."""
    if theme is None:
        theme = config.theme_pref() or sheet_default_theme()
    theme = theme if theme in ("light", "dark") else ""
    labels = ", ".join(f"{k}: {json.dumps(v)}" for k, v in TAB_LABELS.items())
    return _TAB_JS_TEMPLATE.replace("__THEME__", json.dumps(theme)).replace("__LABELS__", labels)


TAB_JS = tab_js()


# ---- masthead monogram (a layout decoration: build_app places it beside the header; static/tabs/frame.css) ----------
def avatar_initial(name: str | None) -> str:
    """The owner's monogram letter: the first letter or digit of the profile name, upper-cased ('' when none)."""
    return next((ch.upper() for ch in (name or "") if ch.isalnum()), "")


def avatar_html(name: str | None) -> str:
    """The monogram as a decorative span (aria-hidden: the header's h2 already names the owner); '' without a name.
    The initial is a letter or digit, so it needs no HTML escaping."""
    initial = avatar_initial(name)
    return f'<span class="twin-avatar" aria-hidden="true">{initial}</span>' if initial else ""
