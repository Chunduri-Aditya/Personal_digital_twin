export const meta = {
  name: 'finish-p3-ui-frame',
  description: 'PLAN_FINISH P3 (PLAN_UNIFIED workflow C, part 1): restyle the UI frame (frame.py layout, theme.py, twin.css, tabs/frame.css) with frontend-design and the redesign audit, adversarial visual review on port 7871, fixer only on must_fix; no GPU',
  whenToUse: 'docs/PLAN_FINISH.md phase P3, after P2 is done',
  phases: [
    { title: 'Restyle', detail: 'frame restyle agent: frontend-design, redesign-existing-projects audit, frame_contract for the P4 lanes' },
    { title: 'Review', detail: 'visual reviewer on 7871: rubric, web-design-guidelines, view_api, contrast, /api/ps untouched (Opus 5, adversarial)' },
    { title: 'Fix', detail: 'fixer only on must_fix (effort low); no re-review (complete, not perfect)' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const LAUNCH_STATE = (args && args.launchState) || 'NOT PROVIDED: run the docs/PLAN_FINISH.md P0 checks yourself before acting, and treat anything you cannot verify as unknown.'
const PYTEST = (args && args.pytestCount) || 551
const BEFORE = (args && args.beforeShots) || 'scripts/dev/shots/before_c'
const SNAPSHOT = (args && args.viewApiSnapshot) || 'scripts/dev/finish/view_api_pre_c.json'
const BACKUP = (args && args.backup) || 'scripts/dev/finish/backup_pre_c'
const MAX_FIX_ROUNDS = 1 // complete, not perfect (user, 2026-09-14)

const FACTS = `FACTS (${RUN_DATE}, docs/PLAN_FINISH.md phase P3 = docs/PLAN_UNIFIED.md workflow C, part 1)
- Read docs/PLAN_FINISH.md (the P3 spec, "Rules for every workflow" and the DEMO CONTRACT) and docs/PLAN_UNIFIED.md sections 3.8, 5 (stage 6), 6 (workflow C) and 10. Design references: docs/PLAN3_UI.md sections 2-3, docs/claude_design_prompt.md (the brief), docs/design/tokens.default.md (the token sheet in use; docs/design/tokens.md is absent). CLAUDE.md is in your context.
- State at launch: ${LAUNCH_STATE}
- pytest before this phase: ${PYTEST} passed ($env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider).
- The demo was signed off on the current UI (docs/DEMO.md); phase P6 re-checks it on the restyled UI, so the DEMO CONTRACT binds every change here.
- Before screenshots of the current UI (light, 1440 px, all 8 tabs): ${BEFORE}/light_1440_<tab>.png. view_api snapshot of the current app: ${SNAPSHOT}. Pre-restyle copies of twin/ui/, static/, app.py and tests/: ${BACKUP}/ (the only rollback; this is not a git repo).
- Tooling (no GPU):
  * powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7871 -OutDir <dir> [-Themes light,dark] [-Widths 1440] [-Tabs ask,status] [-Narrow] [-Measure] [-ViewApi] [-NoShots]. It boots python app.py with TWIN_NO_WARM=1 on the port, writes <theme>_<width>_<tab>.png, -Narrow adds Ask at a true 400 px per theme, -Measure checks the Ask document scrollWidth at a true 400 px (both through scripts/dev/finish/cdp_shot.py, which emulates the viewport over the DevTools protocol, because a Chrome --headless=new window can't be narrower than 500 px and screenshot_tabs.ps1 -Width 400 only crops a 500 px layout; measure_ask_400_<theme>.json lists any overflowing elements), -ViewApi runs scripts/dev/finish/view_api_check.py (names = baseline + six new names; parameters and return counts = the snapshot), saves /api/ps and /api/v0/models before and after, ALWAYS stops the app it started, and writes <dir>\\ui_check.json. Use it for every boot: the PowerShell tool ends processes a command started when that command returns, so an app started in one tool call is gone by the next.
  * python -m twin.ui.theme prints the body-text contrast table and exits 1 when a pair is under 4.5:1; twin.ui.theme.check_contrast() must return [].
  * Open every PNG you cite with the Read tool.
- Rules: no model call and no GPU (UI ports 7871-7879 only, never 7861-7870; never /warm, a rebuild or a model endpoint); not a git repo, so edit only the files you own; never run python - with a here-string (write a .py under scripts/dev/finish/ and run it); 127.0.0.1 only; curl.exe; never print ANTHROPIC_API_KEY.`

const DEMO_CONTRACT = `DEMO CONTRACT (docs/PLAN_FINISH.md; binding for P3-P5)
- API: the api_names and each endpoint's parameters (names, order, defaults) and return count stay equal to scripts/dev/view_api_baseline.json plus the six new names (twin/ui/frame.py NEW_API_NAMES) and to the pre-restyle snapshot. ui_check.ps1 -ViewApi checks both.
- Endpoint and hook output strings stay exactly as they are: everything the docs/demo/beats.json "expect" checks look for, and everything docs/DEMO.md "Point at" quotes (the verdict and cited decisions, footers, trace lines, gpu notes such as "Pre-warmed qwen3_8k", "Last action"). Restyle through classes, CSS and wrappers only, never by changing what an endpoint or a hook returns.
- Every bold label quoted in docs/DEMO.md sections 3-4 stays (tab, button and field labels). The deep links ?tab=<id>, __theme=light|dark and nomotion=1 keep working. The elem_ids twin-header, twin-tabs and tab-<id> stay (gpu-note and status-strip too: CSS and tests use them).
- Any unavoidable change goes into demo_impact[] with the DEMO.md line it affects.`

const RUBRIC = `RUBRIC (docs/PLAN_UNIFIED.md 3.8): tokens only (every colour, radius, shadow and font comes from a --twin-* property); one primary action per area; the status strip visible on desktop; every state styled (empty, streaming, loading a model, inline error, ceiling pending); dark mode complete; Ask at 400 px with document scrollWidth <= 400; body-text contrast >= 4.5:1 by the WCAG function over the token sheet; copy unchanged; api_names unchanged; no internal selectors in static/ (no svelte-, .block, .gradio-container, .prose, .wrap or .gr-; body.dark is the one Gradio hook allowed).`

const OPUS_NOTE = 'MODEL NOTE: this review runs on Opus 5, the same model that wrote the material (Fable 5.1 is over the account monthly spend limit). Compensate: assume the author made mistakes and hunt for them; a statement is not evidence until you open the file or the screenshot that shows it. A null or empty verdict is never acceptable: if you cannot finish a check, say so in checks_run and treat it as a must_fix. COMPLETE, NOT PERFECT (the user\'s instruction, 2026-09-14): there is one review and at most one fix, never a re-review. Raise must_fix only for real blockers: a failed mechanical check (boot, view_api, scrollWidth, /api/ps, contrast, internal selectors, pytest), a DEMO CONTRACT break, or something a client would see as broken (clipped, overlapping, unreadable, a light island in dark mode). Guideline and taste findings go briefly into should_fix.'

const CONTRACT_SCHEMA = {
  type: 'object',
  properties: {
    css_variables: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, purpose: { type: 'string' } }, required: ['name', 'purpose'] } },
    classes: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, purpose: { type: 'string' }, example: { type: 'string' } }, required: ['name', 'purpose', 'example'] } },
    rules: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['css_variables', 'classes', 'rules'],
}
const IMPACT = { type: 'object', properties: { change: { type: 'string' }, demo_md_line: { type: 'string' } }, required: ['change', 'demo_md_line'] }
const RESTYLE_SCHEMA = {
  type: 'object',
  properties: {
    files_written: { type: 'array', items: { type: 'string' } },
    frame_contract: CONTRACT_SCHEMA,
    demo_impact: { type: 'array', items: IMPACT },
    design_notes: { type: 'string' },
    checks: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['files_written', 'frame_contract', 'demo_impact', 'design_notes', 'checks', 'open_issues'],
}
const ISSUE = {
  type: 'object',
  properties: { file: { type: 'string' }, quote: { type: 'string' }, problem: { type: 'string' }, source: { type: 'string' }, fix: { type: 'string' } },
  required: ['file', 'problem', 'source'],
}
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    go: { type: 'boolean' },
    must_fix: { type: 'array', items: ISSUE },
    should_fix: { type: 'array', items: ISSUE },
    checks_run: { type: 'array', items: { type: 'string' } },
    view_api_equal: { type: 'boolean' },
    contrast_failures: { type: 'array', items: { type: 'string' } },
    scroll_width_400: { type: 'integer' },
    api_ps_before: { type: 'string' },
    api_ps_after: { type: 'string' },
    lms_loaded_before: { type: 'string' },
    lms_loaded_after: { type: 'string' },
    pytest_summary: { type: 'string' },
    web_design_guidelines: { type: 'string' },
  },
  required: ['go', 'must_fix', 'should_fix', 'checks_run', 'view_api_equal', 'contrast_failures', 'scroll_width_400', 'api_ps_before', 'api_ps_after', 'pytest_summary', 'web_design_guidelines'],
}
const FIX_SCHEMA = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    files_written: { type: 'array', items: { type: 'string' } },
    frame_contract: CONTRACT_SCHEMA,
    demo_impact: { type: 'array', items: IMPACT },
    checks: { type: 'array', items: { type: 'string' } },
    unresolved_must_fix: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'files_written', 'demo_impact', 'checks', 'unresolved_must_fix'],
}

const OWNERSHIP = `YOUR FILES (edit only these):
- twin/ui/frame.py: layout, wrappers, elem_classes and elem_ids only. Frozen: make_tab_select and its return strings, the heartbeat hooks, _on_page_load, default_tab, the text strip_markdown produces, the timer and every event's wiring (api_name, concurrency_id, inputs, outputs), NEW_API_NAMES and CONDITION_ENDPOINTS, and what _TAB_JS_TEMPLATE / tab_js / TAB_JS do (?tab=, __theme, nomotion=1 and measure=1 must behave exactly as now).
- twin/ui/theme.py, static/twin.css, static/tabs/frame.css (new), tests/test_theme.py.
- docs/design/tokens.default.md, but only together with static/twin.css: tests/test_theme.py::test_twin_css_defaults_match_the_default_sheet pins the two files to each other, and every body-text pair must stay >= 4.5:1 in both modes.
NOT YOURS: twin/ui/<tab>.py, twin/ui/state.py (header_markdown's text), app.py, tests/test_ui_build.py and static/tabs/<tab>.css for any tab (phase P4's lanes own those). If the frame needs a change there, put it in open_issues.`

function restylePrompt() {
  return `You are the FRAME RESTYLE agent (docs/PLAN_UNIFIED.md workflow C, part 1). You own the app's frame: the look every tab inherits.

${FACTS}

${DEMO_CONTRACT}

${RUBRIC}

${OWNERSHIP}

PROCESS
1. Invoke the Skill tool with skill "frontend-design" and follow it. Then invoke the Skill tool with skill "redesign-existing-projects" and run its audit on the frame: header, gpu note, status strip sidebar, tab strip, page ground and width, typography, focus and hover states, dark mode and the 400 px layout. Record the audit findings and what you changed for each in design_notes.
2. Read every PNG in ${BEFORE}, docs/DEMO.md sections 2-4 (what the presenter points at in the frame), twin/ui/frame.py, twin/ui/state.py (header_markdown), twin/ui/theme.py, static/twin.css, docs/design/tokens.default.md, tests/test_theme.py and tests/test_ui_build.py.
3. Restyle the frame for "a private console for one person's digital twin": calm, light-first with a complete dark variant, one accent, and the status strip always visible on desktop. It must stay quiet and legible on a projector during a live demo.
4. Define frame_contract, the base the five P4 tab lanes build on. It lists the shared --twin-* custom properties and the shared component classes in static/twin.css (for example cards, result panels, section headings, action rows, pills and badges, trace panels, tables, empty, loading and error states), each with its purpose and a markup example using gradio elem_classes. It also states the scoping rule for tab partials (every selector in static/tabs/<tab>.css starts with #tab-<id>) and what a lane must never do. The lanes cannot edit frame.py, twin.css or theme.py, so the contract must be complete enough to restyle a tab with elem_classes and its own partial alone.
5. Verify, and iterate until all of it passes:
   - $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider: full suite green, count >= ${PYTEST}.
   - python -m twin.ui.theme exits 0.
   - Select-String over static\\*.css and static\\tabs\\*.css for svelte-, .block, .gradio-container, .prose, .wrap and .gr-: no hits.
   - powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7871 -OutDir scripts\\dev\\shots\\after_c_frame -Themes light,dark -Narrow -Measure -ViewApi: exit 0. Read every PNG it wrote and compare with the before shots.
Return files_written, frame_contract, demo_impact, design_notes, checks (the pytest summary line, the contrast table, the grep result, the ui_check.json fails list and scrollWidth values) and open_issues.`
}

function reviewPrompt(round, restyle, fixes, prior) {
  return `You are the VISUAL REVIEWER of the frame restyle (docs/PLAN_UNIFIED.md workflow C, part 1), round ${round}. You edit no project file: you only write screenshots and check output under scripts\\dev\\shots\\review_c_frame_r${round}\\ and scratch scripts under scripts\\dev\\finish\\.

${FACTS}

${DEMO_CONTRACT}

${RUBRIC}

${OWNERSHIP.replace('YOUR FILES (edit only these):', 'THE RESTYLE AGENT\'S FILES (review these):')}

RESTYLE RESULT (JSON):
${JSON.stringify(restyle, null, 1)}
${fixes.length ? '\nFIX ROUNDS SO FAR (JSON):\n' + JSON.stringify(fixes, null, 1) : ''}
${prior ? '\nPREVIOUS ROUND must_fix (confirm each is really fixed and that nothing new broke):\n' + prior : ''}

CHECKS (each goes into checks_run with its actual output; a failed mechanical check or a visible breakage is a must_fix with a file:line or screenshot path, the problem and a concrete fix; guideline and taste findings are should_fix):
1. Invoke the Skill tool with skill "web-design-guidelines" and apply its rules to static/twin.css, static/tabs/frame.css and twin/ui/frame.py. The skill fetches Vercel's rules online; if the fetch fails, say so in web_design_guidelines and review against the rubric alone.
2. powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7871 -OutDir scripts\\dev\\shots\\review_c_frame_r${round} -Themes light,dark -Narrow -Measure -ViewApi. From its output and ui_check.json: HTTP 200; the view_api check passes; Ask scrollWidth <= 400 at 400 px in both themes; the /api/ps body before equals after and is {"models":[]}; the LM Studio loaded list before equals after. Paste the bodies into api_ps_before, api_ps_after, lms_loaded_before and lms_loaded_after.
3. Open EVERY PNG it wrote with Read (8 light, 8 dark, 2 at 400 px) and the matching before shots in ${BEFORE}. For each: the requested tab is the one shown; header, gpu note, tab strip and status strip are visible and legible; dark mode is really dark with no light islands; nothing is clipped or overflowing; one primary action per area; no tab's layout regressed (tabs are restyled in P4, but they must not break now).
4. python -m twin.ui.theme exits 0, and a scratch script printing twin.ui.theme.check_contrast() prints []. Put any failing pair in contrast_failures.
5. No internal selectors: Select-String over static\\*.css and static\\tabs\\*.css for svelte-, .block, .gradio-container, .prose, .wrap and .gr- (paste any hits).
6. Tokens only: look for raw hex, rgb()/rgba() or hard-coded font families in static/twin.css and static/tabs/frame.css outside the :root and body.dark token blocks; any colour, radius, shadow or font that does not come from a --twin-* property is a finding.
7. DEMO CONTRACT in code: compare twin/ui/frame.py with ${BACKUP}/twin/ui/frame.py (a scratch Python difflib script). Only layout, wrappers, elem_classes and elem_ids may differ; make_tab_select, the text strip_markdown returns, _on_page_load, default_tab, the timer and event wiring and _TAB_JS_TEMPLATE's behaviour must be unchanged. The elem_ids twin-header, gpu-note, status-strip, twin-tabs and tab-<id> must still exist. Every bold label quoted in docs/DEMO.md sections 3-4 must still appear in twin/ui/*.py.
8. Tests: $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider. Paste the summary line into pytest_summary; any failure is a must_fix. tests/test_theme.py must still check the css/token sync and the contrast.
9. Frame contract: is it complete, correct (every class and variable it names exists in static/twin.css) and usable by the P4 lanes with elem_classes and a tab partial alone? Missing or contradictory entries are must_fix.
go is true only when must_fix is empty. Wording taste is never must_fix.`
}

function fixPrompt(round, verdict, contract) {
  return `You are the FIXER of the frame restyle (docs/PLAN_UNIFIED.md workflow C, part 1), round ${round}.

${FACTS}

${DEMO_CONTRACT}

${RUBRIC}

${OWNERSHIP}

Apply every must_fix below, and the should_fix items that are safe and local. Re-open the file or screenshot each item cites before changing anything. If a fix changes a shared class or variable, update frame_contract and return the whole updated contract.

CURRENT FRAME CONTRACT (JSON):
${JSON.stringify(contract, null, 1)}

REVIEW VERDICT (JSON):
${JSON.stringify({ must_fix: verdict.must_fix, should_fix: verdict.should_fix || [] }, null, 1)}

Then verify: the full pytest suite green; python -m twin.ui.theme exits 0; the internal-selector grep has no hits; powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7871 -OutDir scripts\\dev\\shots\\after_c_frame_fix_r${round} -Themes light,dark -Narrow -Measure -ViewApi exits 0, and you Read the PNGs for every item you fixed. Return applied, skipped (with reasons), files_written, frame_contract (when changed), demo_impact, checks, and unresolved_must_fix: each must_fix you could not fully resolve, with the reason (an empty list when all are resolved).`
}

phase('Restyle')
const restyle = await agent(restylePrompt(), { label: 'Frame restyle', phase: 'Restyle', schema: RESTYLE_SCHEMA })
if (!restyle) return { status: 'blocked', stage: 'Restyle', reason: 'restyle agent returned null' }
log(`Restyle: ${restyle.files_written.length} files, ${restyle.frame_contract.classes.length} contract classes, ${restyle.demo_impact.length} demo_impact, ${restyle.open_issues.length} open issues`)

let contract = restyle.frame_contract
const demoImpact = [...restyle.demo_impact]
const reviews = []
const fixes = []

phase('Review')
let review = await agent(OPUS_NOTE + '\n\n' + reviewPrompt(1, restyle, fixes, ''), { label: 'Visual review r1 (Opus)', phase: 'Review', schema: REVIEW_SCHEMA })
if (!review) return { status: 'blocked', stage: 'Review', round: 1, reason: 'reviewer returned null (never read as no findings)', restyle }
reviews.push({ round: 1, go: review.go, must_fix: review.must_fix.length, should_fix: (review.should_fix || []).length, view_api_equal: review.view_api_equal, scroll_width_400: review.scroll_width_400 })
log(`Review r1: go=${review.go}, ${review.must_fix.length} must_fix, ${(review.should_fix || []).length} should_fix, view_api_equal=${review.view_api_equal}, scrollWidth=${review.scroll_width_400}`)

let round = 1
let unresolved = []
while ((!review.go || review.must_fix.length > 0) && round <= MAX_FIX_ROUNDS) {
  phase('Fix')
  const fx = await agent(fixPrompt(round, review, contract), { label: `Frame fix r${round}`, phase: 'Fix', effort: 'low', schema: FIX_SCHEMA })
  if (!fx) return { status: 'blocked', stage: 'Fix', round, reason: 'fixer returned null', restyle, reviews, fixes }
  fixes.push({ round, applied: fx.applied, skipped: fx.skipped, files_written: fx.files_written, checks: fx.checks })
  if (fx.frame_contract && fx.frame_contract.classes && fx.frame_contract.classes.length) contract = fx.frame_contract
  demoImpact.push(...(fx.demo_impact || []))
  unresolved = fx.unresolved_must_fix || []
  log(`Fix r${round}: ${fx.applied.length} applied, ${fx.skipped.length} skipped, ${unresolved.length} must_fix unresolved`)
  round++
}
// Complete, not perfect (user, 2026-09-14): one review, at most one fix, no re-review. The main loop's mechanical
// checks (pytest, ui_check -ViewApi -Measure, contrast, selector grep) are the gate.

return {
  status: unresolved.length === 0 ? 'done' : 'open',
  unresolved_must_fix: unresolved,
  restyle: { files_written: restyle.files_written, design_notes: restyle.design_notes, checks: restyle.checks, open_issues: restyle.open_issues },
  frame_contract: contract,
  demo_impact: demoImpact,
  reviews,
  fixes,
  final: review,
}
