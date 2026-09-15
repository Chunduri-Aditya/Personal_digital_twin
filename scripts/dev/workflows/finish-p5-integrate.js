export const meta = {
  name: 'finish-p5-integrate',
  description: 'PLAN_FINISH P5 (PLAN_UNIFIED workflow D): assemble stage 6 evidence and docs on the restyled UI, stage 7 live sanity as the only GPU agent, three adversarial critics, one fix with a boot check (no critic re-run)',
  whenToUse: 'docs/PLAN_FINISH.md phase P5, after P4 is done',
  phases: [
    { title: 'Assemble', detail: 'full screenshot set on 7877, stage 6 rows in EVIDENCE2, README/CLAUDE/CONTRACTS/ARCHITECTURE UI lines (effort low, no GPU)' },
    { title: 'Live', detail: 'the ONLY GPU agent on 7861: prep, rehearsal run, See, three-condition Ask, pre-warm, status strip, items with restore, stage 7 rows' },
    { title: 'Critics', detail: 'feature completeness, UI completeness, correctness (Opus 5, adversarial, read-only)' },
    { title: 'Fix', detail: 'must_fix plus frame_requests (effort low), pytest, boot check on 7878; no critic re-run (complete, not perfect)' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const LAUNCH_STATE = (args && args.launchState) || 'NOT PROVIDED: run the docs/PLAN_FINISH.md P0 checks yourself before acting, and treat anything you cannot verify as unknown.'
const PYTEST = (args && args.pytestCount) || 551
const NEXT_RUN = (args && args.nextRun) || 12
const SCORES_SHA = (args && args.scoresSha) || '24D60CA6E76C16B3E04C5148028D9ABEA78D602D13FB7408F11C2565E6885DEF'
const C_RESULTS = (args && args.cResults) || 'scripts/dev/finish/c_results.json'
const FRAME_REQUESTS = (args && args.frameRequests) || []
const DEMO_IMPACT = (args && args.demoImpact) || []
const FRAME_REQUEST_COUNT = (args && typeof args.frameRequestCount === 'number') ? args.frameRequestCount : FRAME_REQUESTS.length

const FACTS = `FACTS (${RUN_DATE}, docs/PLAN_FINISH.md phase P5 = docs/PLAN_UNIFIED.md workflow D)
- Read docs/PLAN_FINISH.md (the P5 spec, "Rules for every workflow", the DEMO CONTRACT) and docs/PLAN_UNIFIED.md sections 3.8, 5 (stages 6 and 7), 6 (workflow D) and 10. docs/EVIDENCE2.md holds the stage table (| Stage | Check | Command / action | Actual output (excerpt) | Time | Result |) with stages 0-5; stage 6 and 7 rows go into the same table after the last existing row. CLAUDE.md is in your context.
- State at launch: ${LAUNCH_STATE}
- pytest before this phase: ${PYTEST} passed ($env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider).
- Phases P3 and P4 restyled the UI (workflow C). Their results: ${C_RESULTS} (per-lane checks, reviewer verdicts, demo_impact, frame_requests). Screenshots: scripts/dev/shots/before_c (before), after_c_frame (frame), lane_<key>/ (each lane). Pre-restyle copies: scripts/dev/finish/backup_pre_c/. view_api snapshot before the restyle: scripts/dev/finish/view_api_pre_c.json.
- The demo (docs/DEMO.md, docs/demo/beats.json) was signed off on the pre-restyle UI; phase P6 re-checks it on the restyled UI.
- data/items/scores.json SHA-256 must stay ${SCORES_SHA}. Items "Run twin" and "Score" rewrite data/items/twin_answers.json and scores.json.
- Tooling: scripts\\dev\\finish\\ui_check.ps1 -Port <7871-7879> -OutDir <dir> [-Themes light,dark] [-Tabs ...] [-Narrow] [-Measure] [-ViewApi] boots the app with TWIN_NO_WARM=1, screenshots, measures the Ask scrollWidth at 400 px, checks view_api (baseline + six new names; parameters and returns = the pre-restyle snapshot), saves /api/ps and /api/v0/models before and after, and ALWAYS stops the app it started (the PowerShell tool ends processes a command started when that command returns). python scripts/dev/finish/p0_check.py <snapshot.json> compares code write times, the scores SHA and the data/ list with a snapshot; python scripts/dev/finish/write_snapshot.py <out.json> --reason <text> --pytest <summary> writes one. scripts/dev/live_drive.py drives the endpoints (--port); scripts/demo_prep.ps1 [-WarmOnly]; scripts/demo_rehearse.py --run N; scripts/free_gpu.ps1; scripts/dev/demo/resume/live_r2.ps1 is the tested pattern for a GPU driver that cleans up after itself.
- Standing rules: 127.0.0.1 only; curl.exe; never run python - with a here-string (write a .py under scripts/dev/finish/ and run it); never touch the .ollama junction or OLLAMA_* variables; never print ANTHROPIC_API_KEY; no politics question in any live check; the forbidden live controls in docs/DEMO.md section 3 stay forbidden except where this phase names one (the items check); stop a PID only after confirming it is a python process that owns the listener on the recorded port.`

const DEMO_CONTRACT = `DEMO CONTRACT (docs/PLAN_FINISH.md; binding for P3-P5)
- API: the api_names and each endpoint's parameters and return count stay equal to scripts/dev/view_api_baseline.json plus the six new names and to scripts/dev/finish/view_api_pre_c.json.
- Endpoint and hook output strings stay exactly as they are: the docs/demo/beats.json "expect" strings and every docs/DEMO.md "Point at" quote (verdict and cited decisions, footers, trace lines, gpu notes, "Last action").
- Every bold label quoted in docs/DEMO.md sections 3-4 stays; ?tab=, __theme and nomotion=1 keep working; the elem_ids twin-header, twin-tabs and tab-<id> stay.
- Unavoidable changes go into demo_impact[] with the DEMO.md line they affect.`

const OPUS_NOTE = 'MODEL NOTE: this check runs on Opus 5, the same model that wrote the material (Fable 5.1 is over the account monthly spend limit). Compensate: assume the authors made mistakes and hunt for them; a statement is not evidence until you open the file, the log or the screenshot that shows it. A null or empty verdict is never acceptable: if you cannot finish a check, say so in checks_run and treat it as a must_fix. COMPLETE, NOT PERFECT (the user\'s instruction, 2026-09-14): the critics run once and the fixer once, never a second round. Raise must_fix only for real blockers: failing tests, a broken DEMO CONTRACT or API, a GPU or data-safety problem, a stage 6-7 evidence row with no real output, or something a client would see as broken. Everything else goes briefly into should_fix.'

const ISSUE = {
  type: 'object',
  properties: { file: { type: 'string' }, quote: { type: 'string' }, problem: { type: 'string' }, source: { type: 'string' }, fix: { type: 'string' } },
  required: ['file', 'problem', 'source'],
}
const VERDICT = {
  type: 'object',
  properties: {
    go: { type: 'boolean' },
    must_fix: { type: 'array', items: ISSUE },
    should_fix: { type: 'array', items: ISSUE },
    checks_run: { type: 'array', items: { type: 'string' } },
  },
  required: ['go', 'must_fix', 'should_fix', 'checks_run'],
}
const ASSEMBLE_SCHEMA = {
  type: 'object',
  properties: {
    files_written: { type: 'array', items: { type: 'string' } },
    evidence_rows: { type: 'array', items: { type: 'string' } },
    screenshots: { type: 'array', items: { type: 'string' } },
    checks: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['files_written', 'evidence_rows', 'screenshots', 'checks', 'open_issues'],
}
const LIVE_SCHEMA = {
  type: 'object',
  properties: {
    checks: { type: 'array', items: { type: 'object', properties: { stage: { type: 'string' }, check: { type: 'string' }, result: { type: 'string', enum: ['pass', 'fail', 'blocked'] }, output_excerpt: { type: 'string' } }, required: ['stage', 'check', 'result', 'output_excerpt'] } },
    runs_used: { type: 'array', items: { type: 'integer' } },
    act_drafts: { type: 'string' },
    evidence_rows: { type: 'array', items: { type: 'string' } },
    gpu_freed: { type: 'boolean' },
    app_pid_stopped: { type: 'boolean' },
    api_ps_after: { type: 'string' },
    gpu_mib_after: { type: 'number' },
    scores_sha_after: { type: 'string' },
    items_restored: { type: 'boolean' },
    data_files_match: { type: 'boolean' },
    live_snapshot: { type: 'string' },
    driver_log: { type: 'string' },
    code_issues: { type: 'array', items: { type: 'string' } },
    blocked: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['checks', 'runs_used', 'act_drafts', 'evidence_rows', 'gpu_freed', 'app_pid_stopped', 'api_ps_after', 'scores_sha_after', 'items_restored', 'data_files_match', 'live_snapshot', 'driver_log', 'code_issues', 'blocked', 'notes'],
}
const FIX_SCHEMA = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    files_written: { type: 'array', items: { type: 'string' } },
    pytest_summary: { type: 'string' },
    boot_check: { type: 'string' },
    demo_impact: { type: 'array', items: { type: 'object', properties: { change: { type: 'string' }, demo_md_line: { type: 'string' } }, required: ['change', 'demo_md_line'] } },
    open_issues: { type: 'array', items: { type: 'string' } },
    unresolved_must_fix: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'files_written', 'pytest_summary', 'boot_check', 'demo_impact', 'open_issues', 'unresolved_must_fix'],
}

function assemblePrompt() {
  return `You are the ASSEMBLE agent of workflow D (docs/PLAN_FINISH.md phase P5). No GPU: port 7877 with TWIN_NO_WARM=1 only (through ui_check.ps1).

${FACTS}

${DEMO_CONTRACT}

YOUR FILES: docs/EVIDENCE2.md (append stage 6 rows to the stage table and a short "Workflow C notes" section after the existing notes; never edit existing rows), README.md (the UI, styling and run sections), CLAUDE.md (only a short UI line under Open items: the restyled UI files and scripts/dev/finish/ui_check.ps1; keep every other line), docs/CONTRACTS.md (only the "twin/ui package" section and its subsections), docs/ARCHITECTURE.md (only the lines that describe the UI: theme, static CSS, tab modules, screenshots), and screenshots under scripts/dev/shots/stage6_final/. Nothing else.

TASKS
1. Screenshots: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7877 -OutDir scripts\\dev\\shots\\stage6_final -Themes light,dark -Narrow -Measure -ViewApi (exit 0). Read every PNG it wrote (8 light and 8 dark at 1440, Ask at 400 in both themes) and note anything broken in open_issues.
2. Checks with pasted output: python -m twin.ui.theme (the contrast table, exit 0); Select-String over static\\*.css and static\\tabs\\*.css for svelte-, .block, .gradio-container, .prose, .wrap and .gr-; a scratch scoping check that every selector in static/tabs/<tab>.css starts with #tab-<id> or body.dark #tab-<id> (frame.css is the frame's own partial); the full pytest suite.
3. Stage 6 rows in docs/EVIDENCE2.md, built from ${C_RESULTS} and your own check outputs, one row per check with an actual output excerpt and the time: 6.1 token sheet contrast; 6.2 light and dark shots of all eight tabs at 1440 plus Ask at 400 (file names and sizes); 6.3 one row per restyle lane (frame, ask, decide, act_see, evals_status, onboarding_items) with its reviewer verdict, rounds and key checks; 6.4 no internal selectors and scoped tab partials; 6.5 view_api equals the baseline plus the six new names, with parameters and returns equal to the pre-restyle snapshot; 6.6 Ask scrollWidth at 400 px in both themes; 6.7 /api/ps untouched during the UI work; 6.8 web-design-guidelines per lane (ran, or its online fetch failed); 6.9 pytest after the restyle. A row without pasted output is not evidence.
4. Docs: README.md (how the UI is styled: the token sheet, twin/ui/theme.py, static/twin.css plus static/tabs/*.css, the frame contract, TWIN_THEME, ui_check.ps1 and screenshot_tabs.ps1); CLAUDE.md (the one short line); docs/CONTRACTS.md twin/ui section (the frame contract classes and variables, the partial scoping rule, new elem_ids and classes per tab, any private events the lanes added, verified against the code); docs/ARCHITECTURE.md UI lines. Every statement must match the code; open the files.
Return files_written, evidence_rows (stage and check of each row you added), screenshots (names), checks (the outputs) and open_issues.`
}

function livePrompt(assemble) {
  const cut = NEXT_RUN
  return `You are the LIVE agent of workflow D (docs/PLAN_FINISH.md phase P5): the ONLY agent in this workflow allowed to start the app without TWIN_NO_WARM, load models or touch the GPU. Nobody else runs while you do.

${FACTS}

${DEMO_CONTRACT}

ASSEMBLE RESULT (for context):
${JSON.stringify(assemble, null, 1)}

FIRST: /api/ps must be {"models":[]}, nvidia-smi memory.used <= 200 MiB, and no listener on ports 7861-7870. If not, stop and return blocked (never free a GPU someone else may be using).

DRIVER. The PowerShell tool ends the processes a command started when that command returns. So write ONE driver, scripts\\dev\\finish\\live_p5.ps1, modelled on scripts\\dev\\demo\\resume\\live_r2.ps1 (read it first: Run-Step with redirected logs and timing JSON under scripts\\dev\\evidence\\ or scripts\\dev\\demo\\, refusing to overwrite, and a try/finally that stops only the PID this prep wrote to app.pid after confirming it is python, then runs free_gpu.ps1 and the data checks). Run it with run_in_background=true and poll its log with Read; each tool call is capped at 10 minutes and the driver may take 30-60 minutes. Any helper Python goes under scripts\\dev\\finish\\ and runs as a file.

SEQUENCE inside the driver, in order:
1. Items backup: copy data\\items\\twin_answers.json and data\\items\\scores.json to scripts\\dev\\finish\\items_backup\\ and record both SHA-256 values.
2. Cold prep: scripts\\demo_prep.ps1 (every line PASS), then scripts\\demo_prep.ps1 -WarmOnly (every line PASS).
3. Full rehearsal: python scripts\\demo_rehearse.py --run ${cut}. Count Act drafts from run${cut}_B5.2.txt: a draft is real message text in the === answer === block, never "I ran out of steps".
4. Live checks through the restyled UI on port 7861 (evidence files scripts\\dev\\evidence\\stage7_*):
   a. See: python scripts\\dev\\live_drive.py see scripts\\dev\\test_photo.jpg (stage7_see.txt).
   b. Three-condition Ask: python scripts\\dev\\live_drive.py ask "What did you learn from quitting the agency job?" --condition demographic, then persona, then interview (stage7_ask_<condition>.txt). The traces must show "condition: demographic (chunks: 0, digest: no)", "condition: persona (chunks: 0, digest: yes)" and, for interview, five chunk ids.
   c. Pre-warm on tab select: python scripts\\dev\\live_drive.py free_gpu, then powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\screenshot_tabs.ps1 -Port 7861 -Tabs act -VirtualTimeMs 40000 -OutDir scripts\\dev\\evidence\\stage7_shots, then save /api/ps (stage7_prewarm_api_ps.json): hermes3:8b is loaded and the screenshot's gpu note reads "Pre-warmed hermes3".
   d. Status strip vs the servers: with that model loaded, take -Tabs status -VirtualTimeMs 20000 into stage7_shots and, within a few seconds, save /api/ps (stage7_strip_api_ps.json), lms ps (& "$env:LOCALAPPDATA\\Programs\\LM Studio\\resources\\app\\.webpack\\lms.exe" ps -> stage7_strip_lms_ps.txt) and /api/v0/models (stage7_strip_lms_models.json).
5. Items through the UI: a gradio_client script scripts\\dev\\finish\\items_run_ui.py calls /items_run with "interview" (record elapsed time and the returned note), then /items_score. Afterwards restore both items files from the backup and confirm data\\items\\scores.json SHA-256 equals ${SCORES_SHA}.
6. finally: stop the verified app PID; scripts\\free_gpu.ps1; /api/ps {"models":[]}; nvidia-smi <= 200 MiB; the data\\ file list equals scripts\\dev\\demo\\data_files_before.txt; data\\act_answer.txt absent; scores SHA unchanged. Write these into scripts\\dev\\finish\\cleanup_p5.txt.

AFTER THE DRIVER
- Read every log and evidence file, and open the stage7 screenshots with Read. Compare the status strip in the screenshot with the saved bodies (Ollama and LM Studio lines). From data\\telemetry.jsonl, say whether the items run called models or reused cached answers.
- Append stage 7 rows to the docs/EVIDENCE2.md stage table after the stage 6 rows, each with pasted output and the time: 7.1 cold prep and -WarmOnly; 7.2 rehearsal run ${cut} (steps ok, expect_ok, total time) with the Act draft count; 7.3 See; 7.4 three-condition Ask; 7.5 pre-warm on tab select; 7.6 status strip vs ollama /api/ps and lms ps; 7.7 items run through the UI, the restore and the SHA; 7.8 GPU freed and data safety. Also add a short "Workflow D live notes" section.
- Run the full pytest suite ($env:TWIN_NO_WARM='1'), then python scripts\\dev\\finish\\write_snapshot.py scripts\\dev\\finish\\p5_live_snapshot.json --reason "P5 live (stage 7) after run ${cut}" --pytest "<the summary line>".
- Never change app code. A check that fails for a code reason goes into code_issues with its evidence (P5's Fix handles it); a failure only the user can fix goes into blocked.
Return checks, runs_used, act_drafts, evidence_rows, gpu_freed, app_pid_stopped, api_ps_after, gpu_mib_after, scores_sha_after, items_restored, data_files_match, live_snapshot, driver_log, code_issues, blocked and notes.`
}

const CRITICS = [
  {
    key: 'feature',
    prompt: (ctx) => `You are CRITIC 1 (feature completeness) of workflow D (phase P5). Read-only: edit nothing, start nothing, call no model.

${FACTS}

${ctx}

Check docs/EVIDENCE2.md against docs/PLAN_UNIFIED.md section 5: every check in stages 0-7 has a row with an actual pasted output excerpt, a time and a result; stages 6 and 7 are complete (6: contrast, both themes at 1440 plus Ask at 400, rubric per tab, no internal selectors, view_api baseline plus six, scrollWidth, /api/ps untouched; 7: one Ask, one B1, one Act, one See, one items run through the UI, status strip vs ollama ps and lms ps with saved bodies, pre-warm on tab select, GPU freed, and the items restore with the scores SHA). Open the evidence files the rows cite (scripts/dev/evidence/stage7_*, scripts/dev/shots/stage6_final, scripts/dev/finish/cleanup_p5.txt, the run files) and confirm the pasted excerpts are really in them. A row without output, a cited file that doesn't exist, an excerpt that doesn't match its file, or a stage 7 check that didn't run is a must_fix. The "Still open" section must list what only the user can supply (real profile and transcript, day-0 and day-14 item answers, ANTHROPIC_API_KEY, Claude Design exports, the politics decision). Return go, must_fix, should_fix and checks_run.`,
  },
  {
    key: 'ui',
    prompt: (ctx) => `You are CRITIC 2 (UI completeness) of workflow D (phase P5). Read-only except scratch files under scripts\\dev\\finish\\: edit no project file, start no app, call no model.

${FACTS}

${DEMO_CONTRACT}

${ctx}

1. Invoke the Skill tool with skill "web-design-guidelines" and review static/twin.css, static/tabs/*.css and twin/ui/*.py with it (record if its online fetch fails).
2. Open EVERY PNG in scripts/dev/shots/stage6_final with Read (8 light, 8 dark at 1440, Ask at 400 in both themes) and judge each tab against the rubric in docs/PLAN_UNIFIED.md 3.8: tokens only, one primary action per area, the status strip visible, every state styled, dark mode complete with no light islands, nothing clipped or overflowing, copy unchanged, forbidden live controls not styled as calls to action. Compare with scripts/dev/shots/before_c.
3. Confirm from ${C_RESULTS} that each lane's reviewer really opened its screenshots (their checks name files you can open) and that any web-design-guidelines fetch failure was recorded. List pending frame_requests that still matter.
4. The Ask scrollWidth at 400 px (ui_check.json in stage6_final) is <= 400 in both themes.
A visual defect a client would notice in the demo, a missing rubric item, or an unopened screenshot claimed as checked is a must_fix. Return go, must_fix, should_fix and checks_run.`,
  },
  {
    key: 'correctness',
    prompt: (ctx) => `You are CRITIC 3 (correctness) of workflow D (phase P5). You edit no project file. Allowed: the full pytest suite; powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7879 -OutDir scripts\\dev\\shots\\critic_p5 -NoShots -ViewApi (TWIN_NO_WARM=1, no model); read-only GETs to /api/ps and /api/v0/models; Get-FileHash; scratch scripts under scripts\\dev\\finish\\.

${FACTS}

${DEMO_CONTRACT}

${ctx}

Check:
1. Tests: the full suite is green; paste the summary line. New UI tests test something real (no fake that accepts anything).
2. API: the view_api check passes (names, parameters, returns); concurrency_id "gpu" on every model endpoint and api_name=False on the private events (read twin/ui/*.py and tests/test_ui_build.py); any private event a lane added calls no model and is not on the gpu queue.
3. GPU gating: TWIN_NO_WARM still gates tab-select warm, the heartbeat, /warm and the rebuilds (read twin/ui/frame.py, twin/ui/status.py, twin/gpu.py against scripts/dev/finish/backup_pre_c); /api/ps is {"models":[]} and nvidia-smi <= 200 MiB now.
4. Data safety: data/items/scores.json SHA-256 equals ${SCORES_SHA}; data/items/twin_answers.json equals its backup in scripts/dev/finish/items_backup/; python scripts/dev/finish/p0_check.py scripts/dev/finish/p5_live_snapshot.json shows data_files_match true and act_answer_absent true.
5. DEMO CONTRACT: for every twin/ui/*.py compare with scripts/dev/finish/backup_pre_c (scratch difflib script): no label, placeholder, default, choices, api_name, concurrency_id, event input/output or handler return changed; every bold label in docs/DEMO.md sections 3-4 and every beats.json expect string still has a source in the code; the deep links and elem_ids still work (TAB_JS and the elem_ids in frame.py).
6. Politics: no politics question appears in any stage 7 evidence file.
Return go, must_fix, should_fix and checks_run.`,
  },
]

function fixPrompt(verdicts, live) {
  return `You are the FIXER of workflow D (docs/PLAN_FINISH.md phase P5). Nobody else is running now. No GPU and no model call.

${FACTS}

${DEMO_CONTRACT}

Apply every must_fix from the critics below and every frame_request from the P4 lanes that still applies (re-open each file first; skip any request that would break the DEMO CONTRACT, with the reason). You may edit twin/ui/*.py, static/**, tests/test_ui_*.py, tests/test_theme.py, docs/EVIDENCE2.md (only to correct or complete stage 6-7 rows with real output; never invent output), README.md, CLAUDE.md, docs/CONTRACTS.md and docs/ARCHITECTURE.md. A must_fix that names a pipeline bug (twin/pipelines/) may be fixed only with a regression test that fails before the fix; otherwise record it in open_issues. Never data/, never docs/DEMO.md or docs/demo/beats.json (P6 owns them). Record every change that affects what the presenter sees in demo_impact with the DEMO.md line.

CRITIC VERDICTS (JSON):
${JSON.stringify(verdicts, null, 1)}

FRAME REQUESTS FROM P4: ${FRAME_REQUESTS.length ? '\n' + JSON.stringify(FRAME_REQUESTS, null, 1) : `read every entry of "frame_requests" and each lane's open_issues in ${C_RESULTS}, plus the frame-level should_fix in scripts/dev/finish/p3_results.json (final.should_fix: color-scheme on the root, the frame.css aria-label selectors, #gpu-note min-width, the empty avatar column).`}

LIVE CODE ISSUES (JSON):
${JSON.stringify((live && live.code_issues) || [], null, 1)}

Then: $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider (green; paste the summary into pytest_summary) and the boot check powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7878 -OutDir scripts\\dev\\shots\\fix_p5 -Themes light,dark -Narrow -Measure -ViewApi (exit 0; Read the PNGs of every tab you changed; paste the fails list and scrollWidth into boot_check). Return applied, skipped (with reasons), files_written, pytest_summary, boot_check, demo_impact, open_issues, and unresolved_must_fix: each must_fix you could not fully resolve, with the reason (an empty list when all are resolved).`
}

// ------------------------------------------------------------------ Assemble
phase('Assemble')
const assemble = await agent(assemblePrompt(), { label: 'Assemble (stage 6, docs)', phase: 'Assemble', effort: 'low', schema: ASSEMBLE_SCHEMA })
if (!assemble) return { status: 'blocked', stage: 'Assemble', reason: 'assemble agent returned null' }
log(`Assemble: ${assemble.evidence_rows.length} evidence rows, ${assemble.screenshots.length} screenshots, ${assemble.open_issues.length} open issues`)

// ------------------------------------------------------------------ Live (the only GPU agent, alone in its stage)
phase('Live')
const live = await agent(livePrompt(assemble), { label: 'Live stage 7 (GPU)', phase: 'Live', schema: LIVE_SCHEMA })
if (!live) return { status: 'blocked', stage: 'Live', reason: 'live agent returned null; check listeners on 7861-7870, /api/ps and nvidia-smi before anything else', assemble }
const liveFails = live.checks.filter(c => c.result !== 'pass')
log(`Live: ${live.checks.length} checks (${liveFails.length} not pass), runs ${live.runs_used.join(',')}, Act drafts ${live.act_drafts}, gpu_freed=${live.gpu_freed}, items_restored=${live.items_restored}, scores ${live.scores_sha_after === SCORES_SHA ? 'unchanged' : 'CHANGED'}`)
if (!live.gpu_freed || !live.app_pid_stopped || live.scores_sha_after !== SCORES_SHA || !live.items_restored) {
  return { status: 'blocked', stage: 'Live', reason: 'cleanup or data safety not confirmed (gpu_freed, app_pid_stopped, items_restored, scores SHA)', assemble, live }
}

// ------------------------------------------------------------------ Critics
const ctxFor = () => 'STAGE RESULTS SO FAR (JSON):\n' + JSON.stringify({ assemble, live: { checks: live.checks, runs_used: live.runs_used, act_drafts: live.act_drafts, evidence_rows: live.evidence_rows, code_issues: live.code_issues, blocked: live.blocked, notes: live.notes }, demo_impact_from_p3_p4: DEMO_IMPACT.length ? DEMO_IMPACT : 'read demo_impact in ' + C_RESULTS + ' and scripts/dev/finish/p3_results.json', frame_requests_from_p4: FRAME_REQUESTS.length ? FRAME_REQUESTS : 'read frame_requests in ' + C_RESULTS }, null, 1)
phase('Critics')
const runCritics = async (list, round, prior) => {
  const res = await parallel(list.map(c => () => agent(OPUS_NOTE + '\n\n' + c.prompt(ctxFor() + (prior && prior[c.key] ? '\n\nPREVIOUS ROUND must_fix for this lens (confirm each is really fixed and nothing new broke):\n' + JSON.stringify(prior[c.key], null, 1) : '')), { label: `Critic ${c.key} r${round} (Opus)`, phase: 'Critics', schema: VERDICT })))
  const missing = list.filter((c, i) => !res[i]).map(c => c.key)
  if (missing.length) throw new Error(`critic returned null: ${missing.join(', ')} (round ${round})`)
  const out = {}
  list.forEach((c, i) => { out[c.key] = res[i] })
  return out
}
let verdicts
try {
  verdicts = await runCritics(CRITICS, 1, null)
} catch (e) {
  return { status: 'blocked', stage: 'Critics', reason: String((e && e.message) || e), assemble, live }
}
const must = vs => Object.values(vs).reduce((n, v) => n + v.must_fix.length, 0)
log(`Critics r1: ${Object.entries(verdicts).map(([k, v]) => `${k} go=${v.go} must=${v.must_fix.length}`).join('; ')}`)

// ------------------------------------------------------------------ Fix (must_fix plus frame_requests), then critics with must_fix again
let fix = null
const needsFix = must(verdicts) > 0 || Object.values(verdicts).some(v => !v.go) || FRAME_REQUEST_COUNT > 0 || live.code_issues.length > 0
if (needsFix) {
  phase('Fix')
  fix = await agent(fixPrompt(verdicts, live), { label: 'Fix (must_fix + frame_requests)', phase: 'Fix', effort: 'low', schema: FIX_SCHEMA })
  if (!fix) return { status: 'blocked', stage: 'Fix', reason: 'fixer returned null', assemble, live, verdicts }
  log(`Fix: ${fix.applied.length} applied, ${fix.skipped.length} skipped, ${fix.unresolved_must_fix.length} must_fix unresolved; pytest ${fix.pytest_summary}`)
} else {
  log('No must_fix, frame_requests or code issues: Fix skipped')
}

// Complete, not perfect (user, 2026-09-14): the critics run once and the fixer once; no critic re-run. The main
// loop's mechanical checks (pytest, boot and view_api, evidence rows, GPU idle, scores SHA) are the gate.
const unresolved = fix ? fix.unresolved_must_fix : []
return {
  status: unresolved.length === 0 ? 'done' : 'open',
  unresolved_must_fix: unresolved,
  assemble,
  live,
  fix,
  critics: Object.fromEntries(Object.entries(verdicts).map(([k, v]) => [k, { go: v.go, must_fix: v.must_fix, should_fix: v.should_fix || [], checks_run: v.checks_run }])),
}
