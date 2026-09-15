export const meta = {
  name: 'finish-p4-ui-tabs',
  description: 'PLAN_FINISH P4 (PLAN_UNIFIED workflow C, part 2): five tab restyle lanes on the P3 frame contract (restyle -> adversarial visual review -> fixer on must_fix; no re-review), each on its own UI port with TWIN_NO_WARM=1; no GPU',
  whenToUse: 'docs/PLAN_FINISH.md phase P4, after P3 is done',
  phases: [
    { title: 'Restyle', detail: 'ask 7872, decide 7873, act+see 7874, evals+status 7875, onboarding+items 7876 (pipelined)' },
    { title: 'Review', detail: 'adversarial visual reviewer per lane: rubric, web-design-guidelines, scoping, DEMO CONTRACT (Opus 5)' },
    { title: 'Fix', detail: 'fixer only on must_fix (effort low); no re-review (complete, not perfect)' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const LAUNCH_STATE = (args && args.launchState) || 'NOT PROVIDED: run the docs/PLAN_FINISH.md P0 checks yourself before acting, and treat anything you cannot verify as unknown.'
const PYTEST = (args && args.pytestCount) || 551
const BEFORE = (args && args.beforeShots) || 'scripts/dev/shots/before_c'
const FRAME_SHOTS = (args && args.frameShots) || 'scripts/dev/shots/after_c_frame'
const BACKUP = (args && args.backup) || 'scripts/dev/finish/backup_pre_c'
const FRAME_CONTRACT = (args && args.frameContract) || null
const FRAME_CONTRACT_PATH = (args && args.frameContractPath) || null
const ONLY = (args && Array.isArray(args.lanes) && args.lanes.length) ? args.lanes : null

const ALL_LANES = [
  {
    key: 'ask', port: 7872, tabs: ['ask'],
    files: ['twin/ui/ask.py', 'static/tabs/ask.css', 'tests/test_ui_ask.py (optional, new)'],
    narrow: true,
    targets: 'Ask: chat avatars and a calm empty-chat placeholder; the condition dropdown and the controls row with one primary Send action; the trace and checker panels as trace panels from the frame contract; the hint line; the streaming state and the gpu-note wait. EXTRA CHECK: at 400 px the Ask document scrollWidth is 400 or less in both themes (ui_check -Narrow -Measure).',
  },
  {
    key: 'decide', port: 7873, tabs: ['decide'],
    files: ['twin/ui/decide.py', 'static/tabs/decide.css', 'tests/test_ui_decide.py (optional, new)'],
    narrow: false,
    targets: 'Decide: the verdict card and confidence meter from the frame contract around the result markdown (the markdown text itself never changes), the "Say it in my voice" reply as a quote card, the B1 and B2 inputs with one primary action per area, and the raw result kept where it is now (DEMO.md tells the presenter never to expand it).',
  },
  {
    key: 'act_see', port: 7874, tabs: ['act', 'see'],
    files: ['twin/ui/act.py', 'twin/ui/see.py', 'static/tabs/act.css', 'static/tabs/see.css', 'tests/test_ui_act_see.py (optional, new)'],
    narrow: false,
    targets: 'Act: step-trace cards for the tool steps (search_profile, draft_message and the rest, as trace panels), the Answer area, Polish as a secondary action. See: the image upload area, the description, the reaction as a quote card, and the trace panel.',
  },
  {
    key: 'evals_status', port: 7875, tabs: ['eval', 'status'],
    files: ['twin/ui/evals.py', 'twin/ui/status.py', 'static/tabs/eval.css', 'static/tabs/status.css', 'tests/test_ui_evals_status.py (optional, new)'],
    narrow: false,
    targets: 'Eval: the voice and retrieval tables with tabular numerals, the boundary probes table (#eval-probes), the re-run buttons visually secondary and clearly set apart (they are forbidden live); an optional bar chart of overall score per candidate only if fed by a private event from cached data. Status: the models table with state pills, the telemetry table, the audit tail and the redaction report sections, Free GPU as the one primary action and Warm, Refresh and the Rebuild buttons visually secondary (Rebuild is forbidden live); an optional line chart of tokens per second only if fed by a private event from telemetry.',
  },
  {
    key: 'onboarding_items', port: 7876, tabs: ['onboarding', 'items'],
    files: ['twin/ui/onboarding.py', 'twin/ui/items.py', 'static/tabs/onboarding.css', 'static/tabs/items.css', 'tests/test_ui_onboarding_items.py (optional, new)'],
    narrow: false,
    targets: 'Onboarding: the four walkthrough steps with their status lines and copyable commands. Items: the form grouped by instrument (IPIP-50, GSS, games, gold) with clear group headings, the score table and the decision line, the "ceiling pending" state, and the Save answers, Run twin and Score controls, all forbidden live, kept visually calm (never a loud call to action in the demo view).',
  },
]
const LANES = ONLY ? ALL_LANES.filter(l => ONLY.includes(l.key)) : ALL_LANES

const FACTS = `FACTS (${RUN_DATE}, docs/PLAN_FINISH.md phase P4 = docs/PLAN_UNIFIED.md workflow C, part 2)
- Read docs/PLAN_FINISH.md (the P4 spec, "Rules for every workflow" and the DEMO CONTRACT) and docs/PLAN_UNIFIED.md sections 3.8, 5 (stage 6), 6 (workflow C) and 10. Design references: docs/PLAN3_UI.md sections 2-3 and docs/claude_design_prompt.md. CLAUDE.md is in your context.
- State at launch: ${LAUNCH_STATE}
- pytest before this phase: ${PYTEST} passed ($env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider).
- Phase P3 restyled the frame (twin/ui/frame.py layout, twin/ui/theme.py, static/twin.css, static/tabs/frame.css) and published the frame contract below. Frame screenshots in both themes: ${FRAME_SHOTS}/<theme>_1440_<tab>.png. Before any restyle: ${BEFORE}/light_1440_<tab>.png. Pre-restyle copies of twin/ui/, static/, app.py and tests/: ${BACKUP}/.
- The demo was signed off on the pre-restyle UI (docs/DEMO.md); phase P6 re-checks it on the restyled UI, so the DEMO CONTRACT binds every change here.
- Five lanes run in parallel, each on its own port: ask 7872, decide 7873, act_see 7874, evals_status 7875, onboarding_items 7876. Every lane boots the whole app, so another lane's half-written file can break your boot or the test run for a minute: if an error points at a file you don't own, wait 60 s and retry, and never edit that file.
- Tooling (no GPU):
  * powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port <your port> -OutDir <dir> -Themes light,dark -Tabs <your tabs> [-Narrow] [-Measure] -ViewApi. It boots python app.py with TWIN_NO_WARM=1, writes <theme>_<width>_<tab>.png, -Narrow adds Ask at a true 400 px per theme, -Measure checks the Ask document scrollWidth at a true 400 px (both through scripts/dev/finish/cdp_shot.py, which emulates the viewport over the DevTools protocol, because a Chrome --headless=new window can't be narrower than 500 px and screenshot_tabs.ps1 -Width 400 only crops a 500 px layout; measure_ask_400_<theme>.json lists any overflowing elements), -ViewApi runs scripts/dev/finish/view_api_check.py (names = baseline + six new names; parameters and return counts = the pre-restyle snapshot scripts/dev/finish/view_api_pre_c.json), saves /api/ps and /api/v0/models before and after, ALWAYS stops the app it started, and writes <dir>\\ui_check.json. Use it for every boot: the PowerShell tool ends processes a command started when that command returns.
  * Open every PNG you cite with the Read tool.
- Rules: no model call and no GPU (your UI port only, never 7861-7870; never /warm, a rebuild or a model endpoint); not a git repo, so edit only the files you own; never run python - with a here-string (write a .py under scripts/dev/finish/ and run it); 127.0.0.1 only; curl.exe; never print ANTHROPIC_API_KEY.`

const DEMO_CONTRACT = `DEMO CONTRACT (docs/PLAN_FINISH.md; binding for P3-P5)
- API: the api_names and each endpoint's parameters (names, order, defaults) and return count stay equal to scripts/dev/view_api_baseline.json plus the six new names and to the pre-restyle snapshot (ui_check.ps1 -ViewApi checks both).
- Endpoint and hook output strings stay exactly as they are: everything the docs/demo/beats.json "expect" checks look for, and everything docs/DEMO.md "Point at" quotes (the verdict and cited decisions, footers, trace lines, gpu notes, "Last action"). Restyle through classes, CSS and wrappers only, never by changing what an endpoint, a handler or a hook returns.
- Every bold label quoted in docs/DEMO.md sections 3-4 stays (tab, button and field labels, and the forbidden controls' labels). The deep links ?tab=<id>, __theme=light|dark and nomotion=1 keep working. The elem_ids twin-header, twin-tabs and tab-<id> stay, and every existing elem_id in your modules stays (tests and CSS use them).
- Any unavoidable change goes into demo_impact[] with the DEMO.md line it affects.`

const RUBRIC = `RUBRIC (docs/PLAN_UNIFIED.md 3.8): tokens only (every colour, radius, shadow and font comes from a --twin-* property); one primary action per area; the status strip visible on desktop; every state styled (empty, streaming, loading a model, inline error, ceiling pending); dark mode complete; Ask at 400 px with document scrollWidth <= 400; body-text contrast >= 4.5:1; copy unchanged; api_names unchanged; no internal selectors in static/ (no svelte-, .block, .gradio-container, .prose, .wrap or .gr-; body.dark is the one Gradio hook allowed); every selector in static/tabs/<tab>.css starts with #tab-<id> (optionally preceded by body.dark).`

const OPUS_NOTE = 'MODEL NOTE: this review runs on Opus 5, the same model that wrote the material (Fable 5.1 is over the account monthly spend limit). Compensate: assume the author made mistakes and hunt for them; a statement is not evidence until you open the file or the screenshot that shows it. A null or empty verdict is never acceptable: if you cannot finish a check, say so in checks_run and treat it as a must_fix. COMPLETE, NOT PERFECT (the user\'s instruction, 2026-09-14): there is one review and at most one fix, never a re-review. Raise must_fix only for real blockers: a failed mechanical check (boot, view_api, scrollWidth, /api/ps, internal selectors, scoping, pytest), a DEMO CONTRACT break, or something a client would see as broken (clipped, overlapping, unreadable, a light island in dark mode). Guideline and taste findings go briefly into should_fix.'

const IMPACT = { type: 'object', properties: { change: { type: 'string' }, demo_md_line: { type: 'string' } }, required: ['change', 'demo_md_line'] }
const REQUEST = { type: 'object', properties: { file: { type: 'string' }, change: { type: 'string' }, why: { type: 'string' } }, required: ['file', 'change', 'why'] }
const RESTYLE_SCHEMA = {
  type: 'object',
  properties: {
    files_written: { type: 'array', items: { type: 'string' } },
    checks: { type: 'array', items: { type: 'string' } },
    demo_impact: { type: 'array', items: IMPACT },
    frame_requests: { type: 'array', items: REQUEST },
    design_notes: { type: 'string' },
    open_issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['files_written', 'checks', 'demo_impact', 'frame_requests', 'design_notes', 'open_issues'],
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
    scoping_ok: { type: 'boolean' },
    scroll_width_400: { type: 'integer' },
    api_ps_before: { type: 'string' },
    api_ps_after: { type: 'string' },
    pytest_summary: { type: 'string' },
    web_design_guidelines: { type: 'string' },
    frame_requests: { type: 'array', items: REQUEST },
  },
  required: ['go', 'must_fix', 'should_fix', 'checks_run', 'view_api_equal', 'scoping_ok', 'api_ps_before', 'api_ps_after', 'pytest_summary', 'web_design_guidelines'],
}
const FIX_SCHEMA = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    files_written: { type: 'array', items: { type: 'string' } },
    checks: { type: 'array', items: { type: 'string' } },
    demo_impact: { type: 'array', items: IMPACT },
    frame_requests: { type: 'array', items: REQUEST },
    unresolved_must_fix: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'files_written', 'checks', 'demo_impact', 'frame_requests', 'unresolved_must_fix'],
}

function ownership(lane) {
  return `YOUR FILES (edit only these): ${lane.files.join(', ')}. Your UI port: ${lane.port}. Your tabs: ${lane.tabs.join(', ')} (panels #tab-${lane.tabs.join(', #tab-')}).
NOT YOURS: twin/ui/frame.py, twin/ui/theme.py, twin/ui/state.py, static/twin.css, static/tabs/frame.css, app.py, tests/test_ui_build.py, tests/test_ui_items.py, tests/test_theme.py, every file under twin/pipelines/, docs/, data/, and every other lane's files. If the frame or the shared CSS needs a change, put it in frame_requests (file, change, why); phase P5's Fix applies them.`
}

function uiCheckCmd(lane, outDir) {
  return `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port ${lane.port} -OutDir ${outDir} -Themes light,dark -Tabs ${lane.tabs.join(',')}${lane.narrow ? ' -Narrow -Measure' : ''} -ViewApi`
}

function contractText() {
  if (FRAME_CONTRACT) {
    return 'FRAME CONTRACT from P3 (build on it; you cannot edit frame.py, theme.py, static/twin.css or static/tabs/frame.css):\n' + JSON.stringify(FRAME_CONTRACT, null, 1)
  }
  if (FRAME_CONTRACT_PATH) {
    return `FRAME CONTRACT from P3: before you start, read the "frame_contract" object in ${FRAME_CONTRACT_PATH} in full (css_variables, classes with their markup examples, rules, and notes on where elem_classes land in Gradio 6.27) and follow it exactly. All five lanes build on this same contract. Also read that file's restyle.open_issues and final.should_fix for items that belong to your tabs. You cannot edit frame.py, theme.py, static/twin.css or static/tabs/frame.css.`
  }
  return 'FRAME CONTRACT: NOT PROVIDED in args. Read the shared classes and --twin-* properties from static/twin.css and static/tabs/frame.css yourself, and treat anything not defined there as unavailable.'
}

function restylePrompt(lane) {
  return `You are the RESTYLE agent for the ${lane.key} lane (docs/PLAN_UNIFIED.md workflow C, part 2). Four other lanes restyle other tabs in parallel right now.

${FACTS}

${DEMO_CONTRACT}

${RUBRIC}

${contractText()}

${ownership(lane)}

TARGETS: ${lane.targets}

PROCESS
1. Invoke the Skill tool with skill "frontend-design" and follow it. Then invoke the Skill tool with skill "redesign-existing-projects" and run its audit on your tabs. Record the audit findings and what you changed for each in design_notes.
2. Read your twin/ui modules; the pipeline functions they call, only to learn the output shapes (never edit them); the docs/DEMO.md rows for your tabs (the bold labels and "Point at" strings you must keep) and section 3 (never click live); the docs/demo/beats.json steps for your tabs (their expect strings); the before and frame screenshots for your tabs; static/twin.css and static/tabs/frame.css (the shared classes).
3. Restyle with elem_classes and elem_id additions, layout wrappers (gr.Row, gr.Column, gr.Group; an Accordion only if every quoted label and point-at stays visible without an extra click during the demo) and your partial(s) static/tabs/<tab>.css. Every selector in a partial starts with #tab-<id> (optionally preceded by body.dark). Colours, radii, shadows and fonts come only from --twin-* properties. Never change label text, placeholders, default values, choices, api_name, concurrency_id, the inputs or outputs of any event, or what a handler returns. A new visual component (for example a chart) is allowed only when a private event (api_name=False, never on the gpu queue, no model call) feeds it from data already on disk.
4. Style every state your tabs have (empty, streaming, waiting for a model, inline **Error:** text, ceiling pending) and make dark mode complete.
5. Optionally add your test file (offline build_app with the fakes pattern of tests/test_ui_build.py) asserting your new classes and ids and that labels and event wiring are unchanged.
6. Verify, iterating until everything passes:
   - $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider: your files green; failures in another lane's files are noted, then re-run.
   - Select-String over your partial(s) for svelte-, .block, .gradio-container, .prose, .wrap and .gr- (no hits), and a scratch scoping check that every selector starts with #tab-<id> or body.dark #tab-<id>.
   - ${uiCheckCmd(lane, 'scripts\\dev\\shots\\lane_' + lane.key)} exits 0. Read every PNG it wrote and compare with the before and frame shots.
Return files_written, checks (the pytest summary line, the grep and scoping results, the ui_check.json fails list${lane.narrow ? ', the scrollWidth values' : ''}, the api_ps bodies), demo_impact, frame_requests, design_notes and open_issues.`
}

function reviewPrompt(lane, round, restyle, fix, prior) {
  const out = `scripts\\dev\\shots\\lane_${lane.key}\\review_r${round}`
  return `You are the ADVERSARIAL VISUAL REVIEWER of the ${lane.key} lane (docs/PLAN_UNIFIED.md workflow C, part 2), round ${round}. You edit no project file: you only write screenshots and check output under ${out}\\ and scratch scripts under scripts\\dev\\finish\\.

${FACTS}

${DEMO_CONTRACT}

${RUBRIC}

${contractText()}

${ownership(lane).replace('YOUR FILES (edit only these):', 'THE LANE\'S FILES (review these):').replace('Your UI port:', 'The lane\'s UI port (use it):').replace('Your tabs:', 'The lane\'s tabs:')}

TARGETS: ${lane.targets}

RESTYLE RESULT (JSON):
${JSON.stringify(restyle, null, 1)}
${fix ? '\nFIX RESULT (JSON):\n' + JSON.stringify(fix, null, 1) : ''}
${prior ? '\nPREVIOUS ROUND must_fix (confirm each is really fixed and that nothing new broke):\n' + prior : ''}

CHECKS (each goes into checks_run with its actual output; a failed mechanical check or a visible breakage is a must_fix with a file:line or screenshot path, the problem and a concrete fix; guideline and taste findings are should_fix):
1. Invoke the Skill tool with skill "web-design-guidelines" and apply its rules to the lane's partial(s) and twin/ui modules. The skill fetches Vercel's rules online; if the fetch fails, say so in web_design_guidelines and review against the rubric alone.
2. ${uiCheckCmd(lane, out)}. From its output and ui_check.json: HTTP 200; the view_api check passes (set view_api_equal); ${lane.narrow ? 'Ask scrollWidth <= 400 at 400 px in both themes (set scroll_width_400 to the largest value); ' : ''}the /api/ps body before equals after and is {"models":[]}; the LM Studio loaded list is unchanged. Paste the /api/ps bodies into api_ps_before and api_ps_after.
3. Open EVERY PNG it wrote with Read, plus the before and frame shots of the same tabs. For each: the requested tab is shown; the frame (header, gpu note, tab strip, status strip) is intact; every label and point-at the demo uses is visible without extra clicks; dark mode is really dark with no light islands; nothing clipped or overflowing; one primary action per area; forbidden live controls are not styled as the call to action; the targets above are met or the gap is a finding.
4. Scoping and tokens: a scratch script lists every selector in the lane's partial(s) and fails any that doesn't start with #tab-<id> or body.dark #tab-<id> (set scoping_ok); Select-String for svelte-, .block, .gradio-container, .prose, .wrap and .gr-; flag raw hex, rgb()/rgba() or font families not taken from --twin-* properties.
5. DEMO CONTRACT in code: for each lane module, compare it with ${BACKUP}/<same path> in a scratch Python difflib script. Only elem_classes and elem_id additions, layout wrappers and private (api_name=False, model-free) events may differ. Any change to a label, placeholder, default value, choices, api_name, concurrency_id, event inputs or outputs, or a handler's return value is a must_fix. Every bold label quoted in docs/DEMO.md sections 3-4 for these tabs must still be in the code, and every existing elem_id must still exist.
6. States: find in the code and, where a screenshot can show it, confirm the empty, streaming, waiting-for-a-model, inline error and ceiling pending states the lane's tabs have are styled; missing ones are should_fix unless the demo shows them (then must_fix).
7. Tests: $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider. Paste the summary line into pytest_summary. A failure in a lane file or a test the lane broke is a must_fix; a failure clearly caused by another lane's file mid-flight is noted, and you re-run once after 60 s.
8. frame_requests: list anything the frame or shared CSS must change for this lane (P5's Fix applies them); a request is never a reason to edit frame files here.
go is true only when must_fix is empty. Wording taste is never must_fix.`
}

function fixPrompt(lane, verdict) {
  return `You are the FIXER of the ${lane.key} lane (docs/PLAN_UNIFIED.md workflow C, part 2). Other lanes may still be running.

${FACTS}

${DEMO_CONTRACT}

${RUBRIC}

${contractText()}

${ownership(lane)}

Apply every must_fix below, and the should_fix items that are safe and local. Re-open the file or screenshot each item cites before changing anything. Items that need a frame or shared-CSS change go to frame_requests, not into frame files.

REVIEW VERDICT (JSON):
${JSON.stringify({ must_fix: verdict.must_fix, should_fix: verdict.should_fix || [], frame_requests: verdict.frame_requests || [] }, null, 1)}

Then verify: the pytest suite (your files green); the grep and scoping checks; ${uiCheckCmd(lane, 'scripts\\dev\\shots\\lane_' + lane.key + '\\fix')} exits 0, and you Read the PNGs for every item you fixed. Return applied, skipped (with reasons), files_written, checks, demo_impact, frame_requests, and unresolved_must_fix: each must_fix you could not fully resolve, with the reason (an empty list when all are resolved).`
}

const summarize = v => v ? { go: v.go, must_fix: v.must_fix.length, should_fix: (v.should_fix || []).length, view_api_equal: v.view_api_equal, scoping_ok: v.scoping_ok, scroll_width_400: v.scroll_width_400, pytest: v.pytest_summary } : null

log(`P4 lanes: ${LANES.map(l => `${l.key}@${l.port}`).join(', ')}${FRAME_CONTRACT || FRAME_CONTRACT_PATH ? '' : ' (WARNING: no frameContract in args)'}`)
const results = await pipeline(
  LANES,
  (lane) => agent(restylePrompt(lane), { label: `${lane.key}: restyle`, phase: 'Restyle', schema: RESTYLE_SCHEMA }),
  async (restyle, lane) => {
    if (!restyle) return { status: 'blocked', stage: 'Restyle', reason: 'restyle agent returned null' }
    log(`${lane.key}: restyle done (${restyle.files_written.length} files, ${restyle.frame_requests.length} frame requests)`)
    const review = await agent(OPUS_NOTE + '\n\n' + reviewPrompt(lane, 1, restyle, null, ''), { label: `${lane.key}: review r1 (Opus)`, phase: 'Review', schema: REVIEW_SCHEMA })
    if (!review) return { status: 'blocked', stage: 'Review', reason: 'reviewer returned null (never read as no findings)', restyle }
    log(`${lane.key}: review r1 go=${review.go}, ${review.must_fix.length} must_fix`)
    return { restyle, review }
  },
  async (x, lane) => {
    if (!x || x.status === 'blocked') return x
    if (x.review.go && x.review.must_fix.length === 0) return { ...x, status: 'done', fix: null, final: x.review }
    const fix = await agent(fixPrompt(lane, x.review), { label: `${lane.key}: fix`, phase: 'Fix', effort: 'low', schema: FIX_SCHEMA })
    if (!fix) return { ...x, status: 'blocked', stage: 'Fix', reason: 'fixer returned null' }
    log(`${lane.key}: fix applied ${fix.applied.length}, skipped ${fix.skipped.length}`)
    // Complete, not perfect (user, 2026-09-14): no re-review; the main loop's mechanical checks are the gate.
    const unresolved = fix.unresolved_must_fix || []
    return { ...x, fix, status: unresolved.length === 0 ? 'done' : 'open', final: x.review, unresolved_must_fix: unresolved }
  },
)

const lanes = {}
const demoImpact = []
const frameRequests = []
LANES.forEach((lane, i) => {
  const r = results[i] || { status: 'blocked', reason: 'lane returned null' }
  lanes[lane.key] = {
    status: r.status, port: lane.port, tabs: lane.tabs, reason: r.reason || null,
    files_written: r.restyle ? r.restyle.files_written.concat(r.fix ? r.fix.files_written : []) : [],
    checks: r.restyle ? r.restyle.checks.concat(r.fix ? r.fix.checks : []) : [],
    design_notes: r.restyle ? r.restyle.design_notes : '',
    open_issues: r.restyle ? r.restyle.open_issues : [],
    review_r1: summarize(r.review), review_r2: summarize(r.review2),
    final_must_fix: r.final ? r.final.must_fix : null,
    unresolved_must_fix: r.unresolved_must_fix || [],
    final_should_fix: r.final ? (r.final.should_fix || []) : null,
    final_checks_run: r.final ? r.final.checks_run : null,
  }
  if (r.restyle) demoImpact.push(...r.restyle.demo_impact.map(d => ({ lane: lane.key, ...d })), ...((r.fix && r.fix.demo_impact) || []).map(d => ({ lane: lane.key, ...d })))
  if (r.restyle) frameRequests.push(...r.restyle.frame_requests.map(d => ({ lane: lane.key, ...d })), ...((r.fix && r.fix.frame_requests) || []).map(d => ({ lane: lane.key, ...d })), ...((r.final && r.final.frame_requests) || []).map(d => ({ lane: lane.key, ...d })))
})
const statuses = Object.values(lanes).map(l => l.status)
const status = statuses.every(s => s === 'done') ? 'done' : (statuses.some(s => s === 'blocked') ? 'blocked' : 'open')
log(`P4: ${Object.entries(lanes).map(([k, l]) => `${k}=${l.status}`).join(', ')}`)
return { status, lanes, demo_impact: demoImpact, frame_requests: frameRequests }
