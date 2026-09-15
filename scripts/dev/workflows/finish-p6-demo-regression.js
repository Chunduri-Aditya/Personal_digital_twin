export const meta = {
  name: 'finish-p6-demo-regression',
  description: 'PLAN_FINISH P6: demo regression on the restyled UI (gpu or docs mode), fix DEMO.md/beats.json/rehearsal.md to match, presenter-lens sign-off S1 on Opus 5, one more fix on no-go (no second S1)',
  whenToUse: 'docs/PLAN_FINISH.md phase P6, after P5 is done',
  phases: [
    { title: 'Regress', detail: 'gpu mode: the only GPU agent (cold prep, warm, full run, cut from cold, shots); docs mode: P5 Live run counts, shots on 7871' },
    { title: 'Fix', detail: 'DEMO.md, beats.json, rehearsal.md "After restyle", UI claims in the two docs (effort low)' },
    { title: 'Sign-off', detail: 'S1 presenter lens on the restyled UI (Opus 5, adversarial)' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const LAUNCH_STATE = (args && args.launchState) || 'NOT PROVIDED: run the docs/PLAN_FINISH.md P0 checks yourself before acting, and treat anything you cannot verify as unknown.'
const PYTEST = (args && args.pytestCount) || 551
const NEXT_RUN = (args && args.nextRun) || 13
const MODE = (args && args.mode === 'gpu') ? 'gpu' : 'docs'
const P5_LIVE = (args && args.p5Live) || 'NOT PROVIDED: read the P5 row of the docs/PLAN_FINISH.md Progress log and docs/EVIDENCE2.md stage 7.'
const DEMO_IMPACT = (args && args.demoImpact) || []
const DEMO_IMPACT_PATHS = (args && Array.isArray(args.demoImpactPaths)) ? args.demoImpactPaths : []
const SCORES_SHA = (args && args.scoresSha) || '24D60CA6E76C16B3E04C5148028D9ABEA78D602D13FB7408F11C2565E6885DEF'

const FACTS = `FACTS (${RUN_DATE}, docs/PLAN_FINISH.md phase P6: demo regression on the restyled UI, mode ${MODE})
- Read docs/PLAN_FINISH.md (the P6 spec, the rules, the DEMO CONTRACT) and docs/PLAN_DEMO.md (facts 1-8, the Verification section). The demo: docs/DEMO.md, docs/demo/beats.json, scripts/demo_prep.ps1, scripts/demo_rehearse.py, evidence in scripts/dev/demo/ (rehearsal.md sections 4 and 17; the run files). CLAUDE.md is in your context.
- State at launch: ${LAUNCH_STATE}
- pytest: ${PYTEST} passed ($env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider).
- The demo was signed off in P2 on the pre-restyle UI (old screenshots: scripts/dev/demo/shots/). P3-P4 restyled the UI; P5 integrated it and ran stage 7 live: ${P5_LIVE}
- demo_impact reported by the restyle and integration phases: ${DEMO_IMPACT.length ? JSON.stringify(DEMO_IMPACT) : (DEMO_IMPACT_PATHS.length ? 'read every demo_impact entry in ' + DEMO_IMPACT_PATHS.join(', ') + ' (P3 frame, P4 lanes, P5 fix); each names the DEMO.md line it affects' : 'none reported')}
- Mode: ${MODE === 'gpu' ? 'gpu (something in twin/, app.py or static/ is newer than scripts/dev/finish/p5_live_snapshot.json, so the demo must be re-rehearsed live)' : 'docs (nothing in twin/, app.py or static/ changed after scripts/dev/finish/p5_live_snapshot.json, so P5 Live\'s run files count as the rehearsal on the restyled UI)'}.
- data/items/scores.json SHA-256 must stay ${SCORES_SHA}; data/ must keep exactly the files in scripts/dev/demo/data_files_before.txt; data/act_answer.txt must be absent afterwards.
- Standing rules: 127.0.0.1 only; curl.exe; never run python - with a here-string (helper scripts under scripts/dev/finish/, run as files); never touch the .ollama junction or OLLAMA_* variables; never print ANTHROPIC_API_KEY; no politics question; forbidden live controls stay forbidden; stop a PID only after confirming it is a python process that owns the listener on the recorded port. The PowerShell tool ends processes a command started when that command returns, so every app boot and its checks run inside one command (scripts/dev/finish/ui_check.ps1 for TWIN_NO_WARM UI checks; a driver modelled on scripts/dev/demo/resume/live_r2.ps1, run in the background, for GPU work).`

const OPUS_NOTE = 'MODEL NOTE: this check runs on Opus 5, the same model that wrote the material (Fable 5.1 is over the account monthly spend limit). Compensate: assume the authors made mistakes and hunt for them; a statement is not evidence until you open the file, the run output or the screenshot that shows it. A null or empty verdict is never acceptable: if you cannot finish a check, say so in checks_run and treat it as a must_fix. COMPLETE, NOT PERFECT (the user\'s instruction, 2026-09-14): there is one review and at most one fix, never a re-review. Raise must_fix only for real blockers (the presenter would fail on the restyled UI, a client would hear a false claim, a command fails as written, data safety or cleanup); put everything else briefly into should_fix.'

const ISSUE = {
  type: 'object',
  properties: { file: { type: 'string' }, quote: { type: 'string' }, problem: { type: 'string' }, source: { type: 'string' } },
  required: ['file', 'quote', 'problem', 'source'],
}
const REGRESS_SCHEMA = {
  type: 'object',
  properties: {
    mode: { type: 'string' },
    runs_used: { type: 'array', items: { type: 'integer' } },
    prep_lines: { type: 'array', items: { type: 'string' } },
    run_summary: { type: 'string' },
    act_drafts: { type: 'string' },
    cut_run_summary: { type: 'string' },
    screenshots: { type: 'array', items: { type: 'string' } },
    ui_differences: { type: 'array', items: { type: 'object', properties: { where: { type: 'string' }, demo_md_line: { type: 'string' }, change: { type: 'string' } }, required: ['where', 'demo_md_line', 'change'] } },
    expect_failures: { type: 'array', items: { type: 'string' } },
    wait_changes: { type: 'array', items: { type: 'object', properties: { beat: { type: 'string' }, demo_md: { type: 'string' }, measured: { type: 'string' } }, required: ['beat', 'demo_md', 'measured'] } },
    api_ps_empty_after: { type: 'boolean' },
    gpu_mib_after: { type: 'number' },
    app_pid_stopped: { type: 'boolean' },
    scores_sha_after: { type: 'string' },
    data_files_match: { type: 'boolean' },
    driver_log: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['mode', 'runs_used', 'run_summary', 'screenshots', 'ui_differences', 'expect_failures', 'wait_changes', 'api_ps_empty_after', 'app_pid_stopped', 'scores_sha_after', 'data_files_match', 'notes'],
}
const FIX_SCHEMA = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    dry_run: { type: 'string' },
    fix_log: { type: 'string' },
    unresolved_must_fix: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'dry_run', 'fix_log', 'unresolved_must_fix'],
}
const S1_SCHEMA = {
  type: 'object',
  properties: {
    go: { type: 'boolean' },
    must_fix: { type: 'array', items: ISSUE },
    should_fix: { type: 'array', items: ISSUE },
    broken_beats: { type: 'array', items: { type: 'object', properties: { beat: { type: 'string' }, lane: { type: 'string' }, reason: { type: 'string' } }, required: ['beat', 'lane', 'reason'] } },
    checks_run: { type: 'array', items: { type: 'string' } },
  },
  required: ['go', 'must_fix', 'should_fix', 'broken_beats', 'checks_run'],
}

function regressPrompt() {
  const gpu = `GPU MODE. You are the ONLY agent in this workflow allowed to start the app without TWIN_NO_WARM, load a model or touch the GPU.
FIRST: /api/ps is {"models":[]}, nvidia-smi memory.used <= 200 MiB and no listener on 7861-7870; if not, stop and report it in notes with api_ps_empty_after false (never free a GPU someone else may be using).
Write ONE driver, scripts\\dev\\finish\\live_p6.ps1, modelled on scripts\\dev\\demo\\resume\\live_r2.ps1 (read it first), and run it with run_in_background=true, polling its log with Read (each tool call is capped at 10 minutes). Inside the driver, in order:
1. Cold prep: scripts\\demo_prep.ps1, every line PASS; then scripts\\demo_prep.ps1 -WarmOnly, every line PASS.
2. Full rehearsal: python scripts\\demo_rehearse.py --run ${NEXT_RUN}.
3. Screenshots of all 8 tabs through the running app: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\screenshot_tabs.ps1 -Port 7861 -VirtualTimeMs 40000 -OutDir scripts\\dev\\demo\\shots_restyled (each deep link fires its tab's pre-warm, hence the 40 s budget).
4. The 5-minute-cut model steps from cold, as run 7 did (read scripts/dev/demo/rehearsal.md section 3 "Runs 3-7" for run 7's exact preparation and --only list): free the GPU first (python scripts\\dev\\live_drive.py free_gpu, then confirm /api/ps is empty), then python scripts\\demo_rehearse.py --run ${NEXT_RUN + 1} --only <run 7's list>.
5. finally: stop only the PID this prep wrote to app.pid after confirming it is python and owns the listener on app.port; scripts\\free_gpu.ps1; /api/ps {"models":[]}; nvidia-smi <= 200 MiB; the data\\ list equals data_files_before.txt; data\\act_answer.txt absent; the scores SHA unchanged. Write these to scripts\\dev\\finish\\cleanup_p6.txt.`
  const docs = `DOCS MODE. No GPU, no model call. P5 Live's rehearsal run files count as the rehearsal on the restyled UI (find the run number in the P5 facts above or docs/EVIDENCE2.md row 7.2; files scripts/dev/demo/rehearsal_run<N>.log, run<N>_summary.json, run<N>_<step>.txt).
Screenshots: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7871 -OutDir scripts\\dev\\demo\\shots_restyled -Themes light (all 8 tabs, TWIN_NO_WARM=1, the app is always stopped afterwards). Then confirm with read-only checks that /api/ps is {"models":[]}, nvidia-smi <= 200 MiB, no listener on 7861-7870, the scores SHA is unchanged, the data/ list equals the baseline and data/act_answer.txt is absent. runs_used lists P5's run number.`
  return `You are the REGRESS agent of docs/PLAN_FINISH.md phase P6.

${FACTS}

${MODE === 'gpu' ? gpu : docs}

IN BOTH MODES, afterwards:
- Open EVERY PNG in scripts/dev/demo/shots_restyled with Read, and the matching old shots in scripts/dev/demo/shots/.
- Walk docs/DEMO.md sections 2-5, 8 and 11 against the new screenshots and the code (twin/ui/*.py): the sidebar and status strip, every bold label, every "Exact input" and "Point at" cell. List each difference the presenter would notice in ui_differences, with the DEMO.md line.
- Check every docs/demo/beats.json expect string against the rehearsal run files; list failures in expect_failures.
- Compare the measured waits in the run files with the waits in docs/DEMO.md and rehearsal.md sections 4 and 17.7; list real differences in wait_changes (no noise-level changes).
- In gpu mode, count the Act drafts in run${NEXT_RUN}_B5.2.txt honestly (a draft is real message text, never "I ran out of steps").
Never edit docs/DEMO.md, beats.json, rehearsal.md or app code (the Fix agent owns the docs). Return every field truthfully, including failed attempts.`
}

function fixPrompt(round, regress, verdict) {
  return `You are the FIX agent of docs/PLAN_FINISH.md phase P6, round ${round}. Never start the app, call a model or touch the GPU.

${FACTS}

YOUR FILES: docs/DEMO.md, docs/demo/beats.json, a section "18. After restyle" appended to scripts/dev/demo/rehearsal.md (update it in later rounds; never change earlier sections' recorded measurements), and the UI claims in docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md (only sentences about what the screen looks like, labels, the sidebar and status strip). Never app code, data/, tests or scripts.

DO
- DEMO.md: section 2 (the sidebar and the status strip as they look now), section 3 labels, the "Exact input" and "Point at" cells of every changed beat, section 5 (the cut), section 8 (recovery rows that describe the screen), section 11 (the checklist items that name on-screen things), and waits only where the new run really differs. Keep every exact input identical to beats.json.
- beats.json: change an expect string only when the output legitimately changed and the run files prove it; then run $env:PYTHONUTF8='1'; python scripts/demo_rehearse.py --dry-run and the --include-optional variant, and paste both results into dry_run.
- rehearsal.md section 18 "After restyle": mode, runs used, the per-step table and total time (gpu mode) or the P5 run reference (docs mode), the Act draft count, the screenshots folder, the UI differences and how DEMO.md now reflects them, and data safety and cleanup.
- Write a log of every change (file, old text, new text, source) to scripts/dev/finish/p6_fix_r${round}.md and put its path in fix_log.

REGRESS RESULT (JSON):
${JSON.stringify(regress, null, 1)}
${verdict ? '\nS1 VERDICT TO FIX (JSON):\n' + JSON.stringify({ must_fix: verdict.must_fix, should_fix: verdict.should_fix || [], broken_beats: verdict.broken_beats || [] }, null, 1) : ''}

Return applied, skipped (with reasons), dry_run, fix_log, and unresolved_must_fix: each S1 must_fix you could not fully resolve, with the reason (an empty list when all are resolved or there was no S1 verdict).`
}

function s1Prompt(round, regress, fixes) {
  return `You are S1, the sign-off reviewer (presenter lens) for the demo on the restyled UI, docs/PLAN_FINISH.md phase P6, round ${round}. Read-only: edit nothing, never start the app, call a model or send HTTP to ports 7861-7880. Allowed: python -m py_compile scripts/demo_rehearse.py; python scripts/demo_rehearse.py --dry-run and --dry-run --include-optional (PYTHONUTF8=1); the PowerShell parser check of scripts/demo_prep.ps1; read-only GETs to /api/ps and /api/v0/models; nvidia-smi; Get-FileHash; Get-NetTCPConnection; Grep and Read on anything.

${FACTS}

REGRESS RESULT (JSON):
${JSON.stringify(regress, null, 1)}

FIX ROUNDS (JSON):
${JSON.stringify(fixes, null, 1)}

Pretend you are the presenter at T-10 on this laptop with only docs/DEMO.md open and the restyled UI in the browser.
1. Open EVERY PNG in scripts/dev/demo/shots_restyled with Read. Every bold label, tab name, button, field, the sidebar and status strip description, and every "Point at" in DEMO.md sections 2-5 matches what the screenshots and twin/ui/*.py show now.
2. Exact inputs are identical in DEMO.md and beats.json; both dry-runs pass; every expect string is met in the rehearsal run files for this phase (runs_used).
3. Waits and times in DEMO.md match the run files and rehearsal.md (sections 4, 17.7 and 18); the 10-minute flow and the 5-minute cut still fit.
4. Section 11's checklist is still right for the restyled UI; section 3 names every forbidden control with its current label; the recovery playbook rows describe the current screen.
5. Honesty stays intact: Mara disclosed as synthetic, caveats (a)-(c), no politics beat or deflection claim, the Act and reply-trim outcomes, the P-02 limit.
6. Data safety and cleanup, checked directly now: /api/ps is {"models":[]}, nvidia-smi <= 200 MiB, no listener on 7861-7870, data/items/scores.json SHA-256 is ${SCORES_SHA}, data/ equals scripts/dev/demo/data_files_before.txt, data/act_answer.txt is absent.
must_fix = the presenter would fail or mislead the audience, the docs contradict the restyled screen or the evidence, or a data-safety or cleanup check fails. When a UI change itself broke a beat (not just the docs), add it to broken_beats with the restyle lane that owns the tab (frame, ask, decide, act_see, evals_status or onboarding_items) and why. Wording taste is never must_fix. For each issue: file, quote, problem, source. go is true only when must_fix is empty. List the checks you ran.`
}

// ------------------------------------------------------------------ Regress
phase('Regress')
const regress = await agent(regressPrompt(), { label: `Regress (${MODE} mode${MODE === 'gpu' ? ', GPU' : ''})`, phase: 'Regress', schema: REGRESS_SCHEMA })
if (!regress) return { status: 'blocked', stage: 'Regress', reason: 'regress agent returned null; check listeners on 7861-7870, /api/ps and nvidia-smi before anything else' }
log(`Regress: runs ${regress.runs_used.join(',')}, ${regress.screenshots.length} shots, ${regress.ui_differences.length} UI differences, ${regress.expect_failures.length} expect failures, ${regress.wait_changes.length} wait changes, cleanup api_ps_empty=${regress.api_ps_empty_after} pid_stopped=${regress.app_pid_stopped}, scores ${regress.scores_sha_after === SCORES_SHA ? 'unchanged' : 'CHANGED'}`)
if (!regress.api_ps_empty_after || !regress.app_pid_stopped || regress.scores_sha_after !== SCORES_SHA || !regress.data_files_match) {
  return { status: 'blocked', stage: 'Regress', reason: 'cleanup or data safety not confirmed', regress }
}

// ------------------------------------------------------------------ Fix, S1, (Fix, S1)
const fixes = []
phase('Fix')
const fx1 = await agent(fixPrompt(1, regress, null), { label: 'Fix r1 (docs to the restyled UI)', phase: 'Fix', effort: 'low', schema: FIX_SCHEMA })
if (!fx1) return { status: 'blocked', stage: 'Fix', round: 1, reason: 'fix agent returned null', regress }
fixes.push({ round: 1, ...fx1 })
log(`Fix r1: ${fx1.applied.length} applied, ${fx1.skipped.length} skipped; dry-run: ${fx1.dry_run.slice(0, 120)}`)

phase('Sign-off')
let s1 = await agent(OPUS_NOTE + '\n\n' + s1Prompt(1, regress, fixes), { label: 'S1 presenter r1 (Opus)', phase: 'Sign-off', schema: S1_SCHEMA })
if (!s1) return { status: 'blocked', stage: 'Sign-off', round: 1, reason: 'S1 returned null (never read as no findings)', regress, fixes }
const rounds = [{ round: 1, go: s1.go, must_fix: s1.must_fix.length, broken_beats: s1.broken_beats.length }]
log(`S1 r1: go=${s1.go}, ${s1.must_fix.length} must_fix, ${s1.broken_beats.length} broken beats`)

// Complete, not perfect (user, 2026-09-14): one S1 and at most one more fix, no second S1.
let unresolved = []
if (!s1.go || s1.must_fix.length > 0) {
  phase('Fix')
  const fx2 = await agent(fixPrompt(2, regress, s1), { label: 'Fix r2 (S1 must_fix)', phase: 'Fix', effort: 'low', schema: FIX_SCHEMA })
  if (!fx2) return { status: 'blocked', stage: 'Fix', round: 2, reason: 'fix agent returned null', regress, fixes, s1 }
  fixes.push({ round: 2, ...fx2 })
  unresolved = fx2.unresolved_must_fix || []
  log(`Fix r2: ${fx2.applied.length} applied, ${fx2.skipped.length} skipped, ${unresolved.length} must_fix unresolved`)
}

return {
  status: unresolved.length === 0 ? 'done' : 'open',
  unresolved_must_fix: unresolved,
  mode: MODE,
  regress,
  fixes,
  rounds,
  final: { go: s1.go, must_fix: s1.must_fix, should_fix: s1.should_fix || [], broken_beats: s1.broken_beats, checks_run: s1.checks_run },
}
