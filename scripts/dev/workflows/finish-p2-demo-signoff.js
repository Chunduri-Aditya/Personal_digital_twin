export const meta = {
  name: 'finish-p2-demo-signoff',
  description: 'PLAN_FINISH P2: reconcile the demo deliverables (latency markers, beat ids, Act and reply-trim wording, notes_for_session_c), adversarial sign-off S1 on Opus 5, one final fix and S1 again on no-go',
  whenToUse: 'docs/PLAN_FINISH.md phase P2, after P1 is done',
  phases: [
    { title: 'Reconcile', detail: 'fill latency markers from rehearsal.md, align beat ids and outcome wording, apply notes_for_session_c (effort low)' },
    { title: 'Sign-off', detail: 'S1 go/no-go across DEMO.md, beats.json, the two scripts and the two docs, plus the pre-show checklist (Opus 5, adversarial)' },
    { title: 'Final fix', detail: 'only on no-go: one fix (effort low); no second S1 (complete, not perfect)' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const LAUNCH_STATE = (args && args.launchState) || 'NOT PROVIDED: run the docs/PLAN_FINISH.md P0 checks yourself before acting, and treat anything you cannot verify as unknown.'
const PYTEST = (args && args.pytestCount) || 551
const P1_OUTCOME = (args && args.p1Outcome) || 'NOT PROVIDED: read the P1 row and notes in the docs/PLAN_FINISH.md Progress log and scripts/dev/finish/state.json.'
const B5_LIVE = !(args && args.b5Live === false)
const B5_TEXT = B5_LIVE
  ? 'a live beat (b5_live true: the kept request B5.2 drafted in 4 of 4 rehearsal attempts after the approved act.py fix)'
  : 'trace-only (b5_live false): the presenter shows the trace and the recorded draft, never promises a live draft'

const FACTS = `FACTS (${RUN_DATE}, docs/PLAN_FINISH.md phase P2, PLAN_DEMO Session C)
- Source of truth: docs/PLAN_FINISH.md (the P2 spec, the rules and the DEMO CONTRACT) and docs/PLAN_DEMO.md (facts 1-8, caveats (a)-(c), the beat sheet, the deliverables, the Verification section and the Checkpoint section). CLAUDE.md is in your context.
- State at launch (from the P0 preflight): ${LAUNCH_STATE}
- P1 outcome: ${P1_OUTCOME}
- pytest: ${PYTEST} passed, 0 failed (TWIN_NO_WARM=1, PYTHONUTF8=1). The pinned snapshot is scripts/dev/demo/post_fix_snapshot.json.
- Act beat B5: ${B5_TEXT}.
- Evidence: scripts/dev/demo/rehearsal.md (section 4 measured waits for runs 1-7; section 17 "Runs after fixes", with 17.7 the measured waits for runs 8-11), the run files scripts/dev/demo/run<N>_<step>.txt and rehearsal_run<N>.log, scripts/dev/demo/model_smoke.md, scripts/dev/demo/resume/fix_r2.md and any fix_p1_r*.md, scripts/dev/demo/resume/p1_handoff_results.json (notes_for_session_c from P1's first attempt), docs/EVIDENCE2.md, data/items/scores.json, data/eval_results.json.
- Known facts every document must respect: politics deflection is NOT enforced in code (no politics beat, no deflection claim; the check-profile lint text at twin/profile.py:304-305 is stale and must never be repeated); boundary deflection is prompt-only, the cached probe evidence is 3 of 3 under the interview condition with a qwen2.5 judge, and live P-02 held in 1 of 2 rehearsal runs; See turns and Act polish write no audit line; consent is display-only; the engagement protocol has never run with a real person (caveat c).
- Advisors run on Opus 5 (Fable 5.1 is over the account's monthly spend limit).
- Standing rules: 127.0.0.1 only; curl.exe in PowerShell; never run python - with a here-string (the tool's stdin is the null device); helper scripts go under scripts/dev/finish/; never touch the .ollama junction or OLLAMA_* variables; never print ANTHROPIC_API_KEY. Nobody in this workflow starts the app, calls a model or touches the GPU (the main loop runs Verification 2 afterwards).`

const OPUS_NOTE = 'MODEL NOTE: this check runs on Opus 5, the same model that wrote the material (Fable 5.1 is over the account monthly spend limit). Compensate: assume the authors made mistakes and hunt for them; a statement is not evidence until you open the file that shows it. A null or empty verdict is never acceptable: if you cannot finish a check, say so in checks_run and treat it as a must_fix. COMPLETE, NOT PERFECT (the user\'s instruction, 2026-09-14): there is one review and at most one fix, never a re-review. Raise must_fix only for real blockers (the presenter would fail, a client would hear a false claim, a command fails as written, a docs/PLAN_DEMO.md Verification step would fail, data safety); put everything else briefly into should_fix.'

const ISSUE = {
  type: 'object',
  properties: { file: { type: 'string' }, quote: { type: 'string' }, problem: { type: 'string' }, source: { type: 'string' } },
  required: ['file', 'quote', 'problem', 'source'],
}
const CHECK_ITEM = {
  type: 'object',
  properties: { when: { type: 'string' }, step: { type: 'string' }, pass_condition: { type: 'string' } },
  required: ['when', 'step', 'pass_condition'],
}
const S1_SCHEMA = {
  type: 'object',
  properties: {
    go: { type: 'boolean' },
    must_fix: { type: 'array', items: ISSUE },
    should_fix: { type: 'array', items: ISSUE },
    checklist: { type: 'array', items: CHECK_ITEM },
    checks_run: { type: 'array', items: { type: 'string' } },
  },
  required: ['go', 'must_fix', 'should_fix', 'checklist', 'checks_run'],
}
const RECONCILE = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    markers_left: { type: 'integer' },
    beat_id_changes: { type: 'array', items: { type: 'string' } },
    numbers_checked: { type: 'array', items: { type: 'string' } },
    notes_for_s1: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'markers_left', 'beat_id_changes', 'numbers_checked', 'notes_for_s1'],
}
const FIXED = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    dry_run: { type: 'string' },
    fix_log: { type: 'string' },
    unresolved_must_fix: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'fix_log', 'unresolved_must_fix'],
}

function reconcilePrompt() {
  return `You are the Reconcile agent for docs/PLAN_FINISH.md phase P2 (PLAN_DEMO Session C). You make the demo documents agree with each other and with the evidence. Never start the app, call a model or touch the GPU.

${FACTS}

YOUR FILES (edit only these): docs/ARCHITECTURE.md, docs/CLIENT_TALKING_POINTS.md, and section 6 ("Numbers to quote") of docs/DEMO.md. Everything else is read-only. If DEMO.md outside section 6, docs/demo/beats.json, rehearsal.md or a script needs a change, put it in notes_for_s1 with the exact quote, the file and the fix. Never touch DEMO.md section 11 (the main loop appends the checklist there).

TASKS
1. Latency markers. Replace every literal "[latency: from rehearsal]" in docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md with measured values from scripts/dev/demo/rehearsal.md: section 4 (runs 1-7: Decide verdict, Say it, See, the interview and persona turns, prep) and section 17.7 (runs 8-11, after the fixes: the Ask B4 turns, Act B5, prep). Use the post-fix values for steps whose code changed (Ask replies, Act) and for prep. Name the runs and give the range, for example "8.6-12.0 s on screen in rehearsal runs 1-2 (scripts/dev/demo/rehearsal.md section 4)". Say on-screen or machine time exactly as rehearsal.md does. Never state an estimate as measured: the queued-click cost during a pre-warm and the ~80 s Decide retry path were never measured in rehearsal, so label them. In the client doc use plain wording but keep the numbers and name rehearsal.md. When done, grep both files: zero markers may remain (report the count in markers_left).
2. Beat ids. Read docs/demo/beats.json, the DEMO.md beat table and the 5-minute cut first; they are the source of truth. Every beat id cited in the two docs must exist in beats.json and match its role: B4.3 (P-02) is optional, out of the live flow and out of the cut (reference only; boundary claims point at B7.1, the Eval Boundary probes line); B5.1 is optional and not in the live table; B5 is ${B5_TEXT}; the cut is exactly the steps with in_cut true. CLIENT_TALKING_POINTS.md uses only top-level ids (B1..B8, BX); fix any "Seen live" that names a beat outside the live flow.
3. Outcome wording from P1. Act: after the approved fix in twin/pipelines/act.py, the kept request drafted in 4 of 4 rehearsal attempts (runs 8-11); before the fix 0 of 6 attempts drafted (5 of 6 looped to the 5-step limit with "I ran out of steps", and run 3's B5.1 answered in prose restating the lookup instruction). Drafts vary and can drift from the profile (run 8's draft doesn't match D-02; run 10's draft ran 5 sentences where 1-4 were asked; no draft addressed the mentor by role): state those caveats wherever drafting is claimed. Reply cut: a reply that reaches VOICE_TOKENS 300 is now trimmed to its last full sentence in the final text, the streamed tokens stay raw, and the trace voice line notes the trim; B4.1 in run 8 ended at a full sentence. Correct the today/roadmap labels against the client doc's own definitions. Update the pinned test count to ${PYTEST} with scripts/dev/demo/post_fix_snapshot.json and the new tests. Re-derive every twin/pipelines/act.py and twin/pipelines/ask.py line citation by opening the files now.
4. Apply every notes_for_session_c item (from scripts/dev/demo/resume/p1_handoff_results.json and the P1 outcome above) and every "recheck in P2" item from P1's final claims check, after confirming each against its source. A note that no longer applies goes to skipped, with the reason.
5. docs/DEMO.md section 6: align its numbers with the two docs and the sources (docs/EVIDENCE2.md, data/items/scores.json, data/eval_results.json, rehearsal.md). Keep the historical table labelled as history.
6. Traceability: every number you add or touch must appear in docs/EVIDENCE2.md, the source JSON, rehearsal.md or a run file. List each in numbers_checked as "value -> path:line".
RULES: keep the numbered H2 section order of both docs (ARCHITECTURE 12, CLIENT 10); keep caveats (a)-(c) next to their numbers; never claim politics deflection; re-read every Mermaid fence you touch; keep the two docs consistent with each other and with DEMO.md.

Return applied ("file: what changed"), skipped (with reasons), markers_left, beat_id_changes, numbers_checked and notes_for_s1.`
}

function s1Prompt(round, extra) {
  return `You are S1, the sign-off reviewer for docs/PLAN_FINISH.md phase P2 (PLAN_DEMO Session C), round ${round}. Your verdict decides whether the demo is signed off. Read-only: edit nothing; never start the app, call a model, or send HTTP to ports 11434, 1234 or 7861-7880. Allowed commands: python -m py_compile scripts/demo_rehearse.py; python scripts/demo_rehearse.py --dry-run and python scripts/demo_rehearse.py --dry-run --include-optional (with $env:PYTHONUTF8='1'); a PowerShell parse check of scripts/demo_prep.ps1 ($e=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path scripts\\demo_prep.ps1), [ref]$null, [ref]$e); $e); Get-FileHash; Grep and Read on anything.

${FACTS}

SCOPE (read each in full): docs/DEMO.md, docs/demo/beats.json, scripts/demo_prep.ps1, scripts/demo_rehearse.py, docs/ARCHITECTURE.md, docs/CLIENT_TALKING_POINTS.md, and the evidence they rest on (scripts/dev/demo/rehearsal.md, the run files, model_smoke.md, post_fix_snapshot.json, docs/EVIDENCE2.md, data/items/scores.json, data/eval_results.json).

PROCEDURE
1. Consistency across the set: beat ids, times, waits, the 5-minute cut, forbidden controls, on-screen labels, numbers, the Act and reply-trim outcomes, the P-02 limit, the test count and today/roadmap labels agree in every document and match beats.json and the evidence.
2. Latency: no "[latency: from rehearsal]" marker remains anywhere in the scope; every latency number matches rehearsal.md with its run and range; estimates are labelled as estimates.
3. Honesty: caveats (a)-(c) wherever their numbers appear; Mara disclosed as synthetic; no politics deflection claim and no politics beat; no claim of real-person validation, production readiness or replacing the expert; boundary evidence scoped to the interview condition and the qwen2.5 judge, with the live 1-of-2 result.
4. Runnability: DEMO.md commands run as written in Windows PowerShell 5.1; exact inputs are identical to beats.json; both dry-runs pass; demo_prep.ps1 parses; the 10-minute flow and the 5-minute cut fit using measured waits; every GPU beat has a fallback; each recovery playbook row matches what the tooling actually prints.
5. The app fixes: DEMO.md section 9 names each fix, its tests, the approval (the approving review text is on disk) and the live result; spot-check post_fix_snapshot.json code_last_write_utc for twin/pipelines/act.py and twin/pipelines/ask.py against the files.
6. The two docs: verify at least 25 claims in ARCHITECTURE.md and 20 in CLIENT_TALKING_POINTS.md against code or evidence, favouring the sentences Reconcile changed (listed below) and every number.
must_fix = something that would make the presenter fail, mislead a client, contradict the evidence or the code, or fail a docs/PLAN_DEMO.md Verification step (a leftover marker, a number that differs from its source, a missing caveat, a beat id that doesn't match beats.json, a command that fails as written). Everything else is should_fix; wording taste is never must_fix.
CHECKLIST: return the pre-show checklist the presenter follows, in order (when = "day before", "T-10", "T-5", "T-0" or "after the show"): each item names the exact command or the thing to look at, and its pass condition, taken from DEMO.md and the tooling as they are now. The main loop appends it to DEMO.md section 11.
For each issue: file, quote (exact text), problem, source (path:line and what it shows). go is true only when must_fix is empty. List the checks you ran.
${extra}`
}

function finalFixPrompt(verdict) {
  return `You are the Final fix agent for docs/PLAN_FINISH.md phase P2. Never start the app, call a model or touch the GPU.

${FACTS}

Apply every must_fix below, and the should_fix items that are safe and local.
- Files you may edit: docs/DEMO.md (not section 11), docs/demo/beats.json, docs/ARCHITECTURE.md, docs/CLIENT_TALKING_POINTS.md, scripts/dev/demo/rehearsal.md (clarifications only; never change a recorded measurement), and scripts/demo_prep.ps1 or scripts/demo_rehearse.py only for an item that names them. Never app code (twin/, app.py, tests/, static/) or data/.
- Re-open the cited source for every change; if a claim can't be sourced, cut it or label it roadmap.
- Keep exact inputs identical between DEMO.md and beats.json. After touching beats.json or demo_rehearse.py run $env:PYTHONUTF8='1'; python scripts/demo_rehearse.py --dry-run and the --include-optional variant and paste the result into dry_run. After touching demo_prep.ps1 run the PowerShell parser check.
- Write a log at scripts/dev/finish/p2_final_fix.md listing each change (file, old text, new text, source) and put its path in fix_log.

S1 VERDICT (JSON):
${JSON.stringify({ must_fix: verdict.must_fix, should_fix: verdict.should_fix || [] }, null, 1)}

Return what you applied and what you skipped, with reasons, and unresolved_must_fix: each must_fix you could not fully resolve, with the reason (an empty list when all are resolved).`
}

phase('Reconcile')
const rec = await agent(reconcilePrompt(), { label: 'Reconcile', phase: 'Reconcile', effort: 'low', schema: RECONCILE })
if (!rec) return { status: 'blocked', stage: 'Reconcile', reason: 'Reconcile returned null' }
log(`Reconcile: ${rec.applied.length} applied, ${rec.skipped.length} skipped, markers_left=${rec.markers_left}, ${rec.notes_for_s1.length} notes for S1`)

const recSummary = 'RECONCILE RESULT (verify these changes landed and are correct; its notes_for_s1 name edits it could not make):\n' + JSON.stringify(rec, null, 1)

phase('Sign-off')
const rounds = []
let s1 = await agent(OPUS_NOTE + '\n\n' + s1Prompt(1, recSummary), { label: 'S1 sign-off r1 (Opus)', phase: 'Sign-off', schema: S1_SCHEMA })
if (!s1) return { status: 'blocked', stage: 'Sign-off', round: 1, reason: 'S1 returned null (never read as no findings)', reconcile: rec }
rounds.push({ round: 1, go: s1.go, must_fix: s1.must_fix.length, should_fix: (s1.should_fix || []).length })
log(`S1 r1: go=${s1.go}, ${s1.must_fix.length} must_fix, ${(s1.should_fix || []).length} should_fix, ${s1.checklist.length} checklist items`)

// Complete, not perfect (user, 2026-09-14): one S1 and at most one fix, no second S1. The main loop's Verification
// (markers, dry-run, number trace, prep) is the gate.
let fix = null
if (!s1.go || s1.must_fix.length > 0) {
  phase('Final fix')
  fix = await agent(finalFixPrompt(s1), { label: 'Final fix', phase: 'Final fix', effort: 'low', schema: FIXED })
  if (!fix) return { status: 'blocked', stage: 'Final fix', reason: 'Final fix returned null', reconcile: rec, rounds, s1 }
  log(`Final fix: ${fix.applied.length} applied, ${fix.skipped.length} skipped, ${fix.unresolved_must_fix.length} must_fix unresolved`)
}
const unresolved = fix ? fix.unresolved_must_fix : []

return {
  status: unresolved.length === 0 ? 'done' : 'open',
  unresolved_must_fix: unresolved,
  reconcile: rec,
  rounds,
  fix,
  final: { go: s1.go, must_fix: s1.must_fix, should_fix: s1.should_fix || [], checks_run: s1.checks_run },
  checklist: s1.checklist,
}
