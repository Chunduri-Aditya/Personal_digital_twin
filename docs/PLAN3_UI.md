# Digital Twin phase 3: implement the Claude Design UI in Gradio 6

Written 2026-09-14 for execution in a fresh Claude Code session. Phase 1 (working app) is in `docs/PLAN.md`, `docs/CONTRACTS.md`, `docs/EVIDENCE.md`; phase 2 (interview, conditions, items) is in `docs/PLAN2.md`. This phase can run before or after phase 2: it restyles what exists and leaves placeholders for the Items and Onboarding tabs if phase 2 has not landed.

## 0. Kickoff (paste this single line into the new session)

```
ultracode: read docs\PLAN3_UI.md in full, then execute sections 5 and 6 exactly; don't ask for confirmation between phases and don't stop until every stage has passing evidence or is blocked on something only I can supply, and list any blocked items at the end.
```

## 1. Inputs and what the research established

- The design comes from Claude Design using `docs/claude_design_prompt.md`. Expected files, saved by the user: `docs/design/tokens.md` (the token sheet), `docs/design/screens/` (exported standalone HTML per screen, or the Claude Code handoff bundle unzipped there), optional PNG exports. If none exist at build time, the build uses the default token set in section 3 and records that in `docs/PLAN3_inputs.md`. Never block on the design files.
- Claude Design (Anthropic Labs, research preview since April 2026; Pro, Max, Team, Enterprise): brief plus uploaded screenshots or a codebase, refinement by chat, inline comments and adjustment knobs, export as standalone HTML, PDF, PPTX, or a handoff bundle to Claude Code. Its HTML is a mockup, not our app: only tokens, layout proportions and states are carried over.
- Gradio 6.27 (installed): `demo.launch(theme=, css=, css_paths=, js=, head=)` (these moved off `gr.Blocks`); themes `gr.themes.Base/Soft/Origin/...` with `primary_hue/secondary_hue/neutral_hue`, `spacing_size/radius_size/text_size`, `font=gr.themes.GoogleFont(...)`, and `theme.set(**vars)` over about 200 variables (`*_dark` suffix for dark mode); custom CSS must target `elem_id`/`elem_classes` because internal class names change between versions; components available: `Sidebar`, `Navbar`, `Walkthrough`/`Step`, `Chatbot(avatar_images=, placeholder=, examples=, layout=)`, `BarPlot`, `LinePlot`, `Label`, `Progress`, `Accordion`, `Group`, `Row(equal_height=)`, `Column(scale=, min_width=)`. Multipage `Blocks.route` cannot wire events across pages, so the six tabs stay `gr.Tabs` (the `?tab=` deep link and pre-warm depend on `Tab.select`).
- Verified phase-1 facts still hold: Python `C:\Users\Adity\anaconda3\python.exe` with `PYTHONUTF8=1`; both servers on 127.0.0.1; `scripts/screenshot_tabs.ps1` captures each tab with headless Chrome via `?tab=`; opening a tab fires its pre-warm (model load), which is why this phase adds a `TWIN_NO_WARM=1` switch for design work.

## 2. Design principles to enforce (from the brief)

Calm editorial console; light-first with a complete dark variant; one warm accent; persona header with an initial-letter avatar; the model-on-GPU status always visible; monospace only for ids, traces and tables; no illustrations, gradients or glass; medium density; max width 1440 px; Ask usable at 400 px. States designed explicitly: empty, streaming, loading a model (cold start about 6 s), inline error text, "ceiling pending". Copy stays as it is today.

## 3. Design

### 3.1 Tokens and theme (`twin/ui/theme.py`, `static/twin.css`)

`TwinTheme(gr.themes.Base)` built from `docs/design/tokens.md` when present. When it is absent, the Tokens agent does not fall back to a stock palette: it invokes the `frontend-design` skill, writes the two-pass design plan (palette of 4 to 6 named hex values grounded in "a private console for one person's twin", one or two Google Fonts with a stated reason, type scale, radius rule, three principles) into `docs/design/tokens.default.md`, checks it against the skill's anti-default list (no cream plus terracotta, no near-black plus acid accent, no monospace data labels, no identical rounded cards, no ALL-CAPS eyebrows) and only then builds the theme. One accent, saturation under 80 percent, one grey family, one radius rule, tinted shadows, tabular numerals for tables, monospace only inside trace panels. `theme.set()` covers body and block backgrounds, borders, shadows (two levels), button fills (primary solid amber, secondary outlined), input fills, table header, and every `_dark` counterpart. `static/twin.css` (loaded via `css_paths`) holds only rules keyed on our own `elem_id`/`elem_classes`: `#twin-header`, `#status-strip`, `.verdict-card`, `.confidence-meter`, `.chip`, `.trace`, `.badge-ok/.badge-warn/.badge-err`, `.quote-card`, `.model-table`, plus the 400 px media query for Ask. No selectors on Gradio internal classes. A `tokens_to_theme()` helper parses the token table so a re-export from Claude Design updates the theme without code changes.

### 3.2 Layout (`twin/ui/*.py`, `app.py` becomes the assembler)

Split `app.py` into `twin/ui/frame.py` (header, status strip, sidebar, tab shell, page-load and `?tab=` handling, timer), one module per tab (`ask.py`, `decide.py`, `act.py`, `see.py`, `items.py`, `evals.py`, `status.py`, `onboarding.py`), and `twin/ui/state.py` for shared helpers; each module exposes `build(ctx) -> dict` of components and wires its own events with the same `api_name`s as today (`docs/EVIDENCE.md` lists them) so `scripts/dev/live_drive.py` keeps working. The frame renders: persona header (name, avatar initial, profile source and freshness, warning line); a `gr.Sidebar` (open by default on wide screens) holding the status strip (GPU MiB of 8192, LM Studio loaded model, Ollama loaded model with GPU percent and context, active tab, heartbeat dot with states idle/loading/ready/busy) refreshed by the existing 5 s timer with GETs only; the tab strip. Status strip states come from `MANAGER.status()` plus a new `MANAGER.busy` flag set inside `session()`.

Per tab, the components stay the same as phase 1 (and phase 2 where present); the changes are structure and styling: Decide gets a verdict card (`gr.HTML` built from the result dict: big verdict, confidence meter, reason list, decision chips, footer) with the markdown kept as fallback; Ask gets `avatar_images`, a placeholder with three example prompts, the badge as a styled `gr.HTML`, and the control row grouped; Act gets a step trace rendered as monospace cards; Eval and Status get `gr.BarPlot` (overall per candidate) and `gr.LinePlot` (tokens per second over the last 30 calls) next to the tables; Status shows the models-and-jobs table with state pills; Onboarding is a `gr.Walkthrough` with four `gr.Step`s driven by file checks (profile, transcript, index freshness, self answers), shown first when the real profile is missing. Items and Onboarding render a short placeholder card if phase 2 modules are absent (`importlib` check), never an import error.

### 3.3 Design-work switches

`TWIN_NO_WARM=1` disables tab pre-warm and the heartbeat (bookkeeping only) so UI agents can boot the app on spare ports (7871 to 7879) and screenshot every tab without touching the GPU; `TWIN_THEME=light|dark` forces the theme for screenshots (`__theme` query param also works). `scripts/screenshot_tabs.ps1` gains `-Port`, `-Theme` and `-Width` (1440 and 400) parameters and writes `scripts/dev/shots/<theme>_<width>_<tab>.png`.

### 3.3b Skills the agents must use (installed in `.claude/skills`, see CLAUDE.md)

- `frontend-design` (Anthropic): every agent that writes `theme.py`, `twin.css` or a tab restyle invokes it first and follows its two-pass process (design plan, anti-default check, then code). Its anti-default list is binding.
- `redesign-existing-projects`: the stage-1 restyle agents run its "Scan, Diagnose, Fix" audit on their tab before editing and apply its fix priority (fonts, palette, hover and active states, layout and spacing, components, loading/empty/error states, type polish). Marketing-page items (parallax, grain, hero imagery, scroll reveals) do not apply and are skipped.
- `web-design-guidelines` (Vercel): the stage-2 visual reviewers and the workflow-9 correctness critic invoke it (it fetches `command.md` from vercel-labs/web-interface-guidelines at review time) against `static/*.css`, `twin/ui/*.py` and the rendered HTML saved from the running app, and report findings in its `file:line` format. Rules that Gradio owns (its internal DOM) are reported as "framework-owned" rather than fixed.
- Optional, only if Node.js is present (`node --version` works): `npx impeccable detect http://127.0.0.1:7871/?tab=<tab>` for each tab as an extra stage-3 audit; findings become fixer input. Do not install Node inside a workflow; note "impeccable skipped: no Node" in `docs/EVIDENCE3.md` instead.

### 3.4 Review rubric (used by the visual reviewers)

For each tab, compare the screenshot with the design export (or the brief when no export exists): token usage (no hard-coded colors outside `theme.py`/`twin.css`), hierarchy (one primary button per screen area), status strip visible, states present (empty, loading, error text inline), dark mode complete (no white flashes, no unreadable text), 400 px Ask without horizontal scroll, contrast at least 4.5:1 for body text (checked with a small Python WCAG contrast function over the token sheet), copy unchanged, `api_name`s unchanged, no Gradio internal class selectors in `twin.css`.

## 4. Repo additions

```
twin/ui/__init__.py theme.py frame.py state.py ask.py decide.py act.py see.py items.py evals.py status.py onboarding.py
static/twin.css                 app.py (assembler only; keeps --port/--host, pick_port, TAB_JS, api_names)
docs/design/                    user-supplied exports;  docs/PLAN3_inputs.md;  docs/EVIDENCE3.md;  docs/design/tokens.default.md
scripts/screenshot_tabs.ps1     -Port -Theme -Width;  scripts/dev/shots/
tests/test_theme.py test_ui_build.py (build_app offline with patched status; every api_name present; no internal selectors; contrast check)
```

## 5. Build stages and verification (PowerShell 5.1)

0. **Inputs and tokens**: read `docs/design/*` if present; write `docs/PLAN3_inputs.md` (what was found); write `docs/design/tokens.default.md`; `twin/ui/theme.py` builds from either; `python -c "from twin.ui.theme import build_theme; t=build_theme(); print(type(t).__name__)"` prints `TwinTheme`; the contrast test passes for body text on both backgrounds.
1. **Refactor without visual change**: `app.py` assembled from `twin/ui/*`; `python -m pytest tests -q` green (existing 215 plus new); boot on port 7871 with `TWIN_NO_WARM=1`: HTTP 200, `gradio_client` `view_api()` lists exactly the phase-1 api_names (plus phase-2 ones if present), `/api/ps` stays `{"models":[]}` after booting and after screenshotting all tabs (no warm because of the switch).
2. **Theme and frame**: light and dark screenshots of all tabs at 1440 (`scripts/dev/shots/`); header and sidebar status strip present on every tab; status strip shows the four states when driven by a patched `MANAGER.status()` in an offline test; no selector in `twin.css` matches `svelte-` or `.block` internal names (grep).
3. **Per-tab restyle**: every tab passes the section-3.4 rubric in the visual review; Ask at 400 px has no horizontal scroll (headless Chrome `--window-size=400,900` screenshot plus `document.documentElement.scrollWidth <= 400` via `js` check); Decide verdict card renders from a recorded result dict; Eval bar chart and Status line chart render from cached data with no model call.
4. **Live sanity (the only GPU stage)**: without `TWIN_NO_WARM`, run `scripts/dev/live_drive.py` for one Ask turn, one B1, one Act request and `/status`; the status strip shows the loaded model and GPU MiB matching `ollama ps` / `lms ps`; pre-warm on tab select still works (`/warm ask` loads Stheno); GPU freed at the end (`scripts/free_gpu.ps1`, `/api/ps` empty).
5. **Evidence**: `docs/EVIDENCE3.md` with one row per check above, the final screenshot set in light and dark, and `README.md` "Run" section updated (theme switches, screenshot script flags).

## 6. Execution: ultracode workflows

Same rules as before: agents inherit the session model; design, review and live agents keep the session effort; refactor and fix stages use `effort: 'low'`; only workflow 9 has a GPU agent and it runs alone; parallel agents own disjoint files (the tab split in workflow 7 exists precisely so workflow 8 can run tabs in parallel); `TWIN_NO_WARM=1` and distinct ports (7871 + index) for every agent that boots the app; read each result before launching the next; fix and resume with `resumeFromRunId`.

### Workflow 7: tokens, theme, refactor (5 agents)

```
phase Tokens     1 agent: docs/PLAN3_inputs.md, tokens.default.md (or parse docs/design/tokens.md), twin/ui/theme.py,
                 static/twin.css skeleton, tests/test_theme.py with the contrast check
phase Refactor   1 agent, effort low: split app.py into twin/ui/* with identical behaviour and api_names, TWIN_NO_WARM
                 and TWIN_THEME switches, screenshot script flags, tests/test_ui_build.py
phase Verify     parallel 2: api/behaviour reviewer (diff of api_names, event wiring, no model call on boot; boots on 7871
                 with TWIN_NO_WARM=1) and a CSS/theme reviewer (no internal selectors, dark variables complete)
phase Fix        1 agent, effort low, only if findings; reruns tests and the boot check
```

### Workflow 8: per-tab restyle (12 to 16 agents)

`pipeline()` over `[frame, ask, decide, act, see, evals, status, onboarding+items]` (each owns its `twin/ui/<name>.py` and its `elem_*` rules in a per-tab CSS partial `static/tabs/<name>.css` concatenated by `theme.py`): stage 1 restyle to the design; stage 2 visual reviewer boots the app on its own port with `TWIN_NO_WARM=1`, screenshots the tab in light and dark (and 400 px for Ask), scores the rubric, returns findings; stage 3 fixer when findings exist, re-screenshots.

### Workflow 9: integrate, live check, critics (5 agents)

```
phase Integrate  1 agent: assemble, full screenshot set into scripts/dev/shots/, README, docs/EVIDENCE3.md skeleton
phase Live       1 agent (GPU): stage 4 checks against the real servers, evidence into docs/EVIDENCE3.md
phase Critic     parallel 2: completeness (every screen and state in the brief exists; every stage has evidence) and
                 correctness (api_names, event wiring, no regression in tests, no internal selectors)
phase Fix        1 agent, effort low
```

After workflow 9: the final screenshot set is the deliverable to compare against the Claude Design canvas; if the user wants a second design round, the screenshots go back into Claude Design as the new "current state".

## 7. The user's tasks (the only blockers)

1. Run `docs/claude_design_prompt.md` in Claude Design with the six current screenshots attached; iterate until satisfied; export standalone HTML and the Claude Code handoff bundle into `docs/design/` and save the token table as `docs/design/tokens.md`. Optional: the build works on the default tokens without it.
2. Decide light-first or dark-first as the default theme if the design changes the brief's light-first choice (the build reads `TWIN_THEME` default from `tokens.md` `default_theme:` line; default light).
