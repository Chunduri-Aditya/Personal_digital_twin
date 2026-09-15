export const meta = {
  name: 'finish-p1-demo-ab',
  description: 'PLAN_FINISH P1: docs lane (claims re-check and revise) and demo lane (review, approved app fixes with tests, live re-rehearsal as the only GPU user) in parallel; advisors on Opus 5',
  whenToUse: 'docs/PLAN_FINISH.md phase P1, only when the Progress log shows P1 open or blocked',
  phases: [
    { title: 'Docs re-check', detail: 'A2 verifiers on ARCHITECTURE.md and CLIENT_TALKING_POINTS.md (Opus 5)' },
    { title: 'Docs revise', detail: 'apply must_fix, at most one more round' },
    { title: 'Demo review', detail: 'presenter lens and failure lens (Opus 5)' },
    { title: 'Demo fix', detail: 'decisions, app fixes with regression tests, live re-rehearsal, cleanup, post-fix snapshot' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const LAUNCH_STATE = (args && args.launchState) || 'NOT PROVIDED: run the docs/PLAN_FINISH.md P0 checks yourself before acting, and treat anything you cannot verify as unknown.'
const PYTEST = (args && args.pytestCount) || 543
const NEXT_RUN = (args && args.nextRun) || 8

const RESUME_FACTS = `RESUME FACTS (${RUN_DATE}, docs/PLAN_FINISH.md phase P1)
- Source of truth: docs/PLAN_FINISH.md (the P1 spec, rules and DEMO decisions) and docs/PLAN_DEMO.md (read it in full, especially "Facts that shape the plan" 1-8, the beat sheet, the deliverables, the Verification section and the Checkpoint section). CLAUDE.md is in your context.
- State at launch (from the PLAN_FINISH P0 preflight): ${LAUNCH_STATE}
- pytest before this phase: ${PYTEST} passed (TWIN_NO_WARM=1, PYTHONUTF8=1).
- History: Session A drafted docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md; the round-0 claims check found 5 must_fix in ARCHITECTURE and 7 in CLIENT_TALKING_POINTS; revise round 1 applied 40 changes (scripts/dev/demo/resume/session_a_claims_round0.json). Session B wrote docs/DEMO.md, docs/demo/beats.json, scripts/demo_prep.ps1 and scripts/demo_rehearse.py and rehearsed live on the local models (scripts/dev/demo/rehearsal.md; per-model smoke test 8/8 PASS in scripts/dev/demo/model_smoke.md; screenshots in scripts/dev/demo/shots/). An earlier P1 attempt (workflow demo-resume-ab) may already have applied fixes or written evidence (scripts/dev/demo/resume/fix_r*.md, rehearsal runs after 7); the launch state lists what exists. Verify existing work instead of redoing it.
- Rehearsal findings before any fix: all 15 main-flow steps ran ok in runs 1 and 2 (129.8 s and 122.2 s machine time); Decide 8.6-12.0 s with 1 attempt, citing D-01 and D-08; Act produced no draft in 0 of 6 attempts ("I ran out of steps": draft_message returns the same next_step asking for search_profile even after it ran, twin/pipelines/act.py:209-222, so hermes3 loops to max_steps 5); P-02 was deflected in run 1 but not in run 2 (scripts/dev/demo/run2_B4.3.txt); Ask replies are cut mid-sentence at VOICE_TOKENS = 300 (twin/pipelines/ask.py:56), including B4.1; headless screenshots of model tabs show the pre-warm still pending.
- Advisors run on Opus 5 (Fable 5.1 is over the account's monthly spend limit).
- Tooling: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo_prep.ps1 [-WarmOnly] [-Port 7861] prints PASS/FAIL per line and writes scripts/dev/demo/app.pid and app.port; python scripts/demo_rehearse.py --run N [--only ID,ID] [--include-optional] [--dry-run], or --check-profile, or --smoke [--models KEY,KEY]; python scripts/dev/live_drive.py <cmd> --port <port>. Each run writes scripts/dev/demo/rehearsal_run<N>.log, run<N>_summary.json and run<N>_<id>.txt. The next free run number is ${NEXT_RUN}; never reuse a number that already has a log.
- Lanes running in parallel: the docs lane edits only docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md and never touches the GPU. The demo lane edits docs/DEMO.md, docs/demo/beats.json, scripts/demo_prep.ps1, scripts/demo_rehearse.py and scripts/dev/demo/**, plus twin/ and tests/ only under the approved-app-fix rule; its Fix agent is the only GPU user. Phase P2 reconciles all five deliverables afterwards.
- Standing rules: 127.0.0.1 only; curl.exe in PowerShell; never run python - with a here-string (the tool's stdin is the null device); write helper scripts under scripts/dev/demo/resume/; before stopping any process, confirm it is a python process that owns the listener on the port in scripts/dev/demo/app.port (app.pid can be stale and Windows reuses PIDs); never touch the .ollama junction or OLLAMA_* variables; never print ANTHROPIC_API_KEY.`

const DECISIONS = `DECISIONS (approved defaults in docs/PLAN_FINISH.md):
1. Act never writes the draft. Treat it as a demo-blocking app bug and fix it under the exception rule: a reviewer approves it in writing (a must_fix whose problem text starts with "APPROVED APP FIX:"); the smallest change in twin/pipelines/act.py; a regression test in tests/ that fails before the fix and passes after; the full pytest green (${PYTEST} plus the new tests, 0 failed); a DEMO.md section 9 "Known issues" line naming the file, the change, the test and the reviewer approval. Then prove it live: re-rehearse the kept Act request (B5.2) at least 3 times. B5 stays a live beat only if at least 2 of 3 attempts produce a real draft; otherwise B5 becomes trace-only with honest framing.
2. P-02 held in 1 of 2 runs. No code change (enforcing boundaries in code is roadmap). Take P-02 out of the live flow and the 5-minute cut (make its beats.json step optional and not in_cut); the presenter shows the Eval probes table instead and states the limit plainly: prompt-level, held 1 of 2 in rehearsal, 3 of 3 in the cached interview-condition probe run (data/eval_results.json).
3. Ask replies are cut mid-sentence at VOICE_TOKENS = 300. A small, tested app fix is allowed under the same rule when a reviewer approves it. Prefer trimming a length-truncated reply to its last complete sentence, without breaking streaming or the Say it / See voice paths, over raising the cap. Otherwise change the demo input or talk track so a cut reply is not the first thing a client sees. Record whichever was done.`

const OPUS_NOTE = 'MODEL NOTE: this check runs on Opus 5, the same model that wrote the material (Fable 5.1 is over the account monthly spend limit). Compensate: assume the authors made mistakes and hunt for them; a statement is not evidence until you open the file that shows it.'

const ISSUE = {
  type: 'object',
  properties: { file: { type: 'string' }, quote: { type: 'string' }, problem: { type: 'string' }, source: { type: 'string' } },
  required: ['file', 'quote', 'problem', 'source'],
}
const VERDICT = {
  type: 'object',
  properties: {
    go: { type: 'boolean' },
    must_fix: { type: 'array', items: ISSUE },
    should_fix: { type: 'array', items: ISSUE },
    checks_run: { type: 'array', items: { type: 'string' } },
  },
  required: ['go', 'must_fix', 'checks_run'],
}
const REVISE = {
  type: 'object',
  properties: { applied: { type: 'array', items: { type: 'string' } }, skipped: { type: 'array', items: { type: 'string' } } },
  required: ['applied', 'skipped'],
}
const FIX = {
  type: 'object',
  properties: {
    applied: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    app_code_changed: { type: 'boolean' },
    app_changes: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, change: { type: 'string' }, test: { type: 'string' }, failed_before_fix: { type: 'boolean' } }, required: ['file', 'change', 'test'] } },
    pytest_summary: { type: 'string' },
    runs_used: { type: 'array', items: { type: 'integer' } },
    act_drafts: { type: 'string' },
    b5_live: { type: 'boolean' },
    api_ps_empty_after: { type: 'boolean' },
    app_pid_stopped: { type: 'boolean' },
    gpu_mib_after: { type: 'number' },
    post_fix_snapshot: { type: 'string' },
    fix_log: { type: 'string' },
    notes_for_session_c: { type: 'array', items: { type: 'string' } },
  },
  required: ['applied', 'skipped', 'app_code_changed', 'pytest_summary', 'runs_used', 'api_ps_empty_after', 'app_pid_stopped', 'post_fix_snapshot', 'fix_log', 'notes_for_session_c'],
}

async function advisor(prompt, label, phaseTitle) {
  const verdict = await agent(OPUS_NOTE + '\n\n' + prompt, { label: `${label} (Opus)`, phase: phaseTitle, schema: VERDICT })
  if (!verdict) throw new Error(`${label} returned null`)
  return { verdict, model: 'opus' }
}
const mustOf = vs => vs.reduce((n, v) => n + (v.verdict.must_fix || []).length, 0)
const shouldOf = vs => vs.reduce((n, v) => n + (v.verdict.should_fix || []).length, 0)
const compact = vs => vs.map(v => ({ lens: v.lens, model: v.model, go: v.verdict.go, must_fix: v.verdict.must_fix, should_fix: v.verdict.should_fix || [] }))

// ---------------- Docs lane (Session A remainder) ----------------
const DOCS = [
  { key: 'arch', file: 'docs/ARCHITECTURE.md', sections: 12 },
  { key: 'client', file: 'docs/CLIENT_TALKING_POINTS.md', sections: 10 },
]

function a2Prompt(doc, round, prior) {
  return `You are A2, the adversarial claims verifier for PLAN_DEMO Session A, round ${round}, checking ONE document: ${doc.file}. Read-only: edit nothing, start nothing, call no model, and send no HTTP to ports 11434, 1234 or 7861-7871.

${RESUME_FACTS}

PREVIOUS ROUNDS: scripts/dev/demo/resume/session_a_claims_round0.json holds the round-0 verdicts for both documents (a2_round0) and the round-1 revise log (revise_round1); later rounds may have run (see the launch state).
${prior ? 'Latest must_fix list for this document (confirm each is really fixed and that the fix broke nothing):\n' + prior : 'Confirm every earlier must_fix for this document is really fixed, and that the revisions introduced no new error.'}

STANCE: every claim is unproven until you open its primary source and see it. Don't trust the document's citations, the plan's rounded summary, or your memory.

PROCEDURE
1. Read ${doc.file} in full, plus docs/PLAN_DEMO.md facts 1-8, its caveats (a)-(c), and the Checkpoint section.
2. List every checkable claim: numbers, counts, model names, file paths and line refs, function and config names, keep-alive and context values, behaviours, capability statements, section order (${doc.sections} numbered H2 sections).
3. Verify each in its primary source: app.py, twin/**, scripts/**, docs/CONTRACTS.md, docs/EVIDENCE2.md or docs/EVIDENCE.md rows, data/items/scores.json, data/eval_results.json, data/probes.json, data/chunks.json, scripts/dev/demo/rehearsal.md and model_smoke.md.
4. must_fix when: a number differs from its source in any digit or is rounded without saying so; a claim is unsupported or contradicted by code; roadmap described as present, or a missing or wrong today/roadmap label (client doc); overstatement (boundary-probe evidence generalized beyond the interview condition and the qwen2.5 judge; anything implying real-person validation, production readiness or replacing the expert); caveat (a), (b) or (c) missing where its numbers appear; any claim that the twin deflects or avoids politics in conversation; a wait or wall-time number instead of the marker [latency: from rehearsal] (the marker is correct until phase P2 fills it); invented customers, pricing, ROI or market statistics; a missing or out-of-order section; a Mermaid fence that would not parse; a cited path or line that doesn't show the claim; a rehearsal result stated differently from scripts/dev/demo/rehearsal.md; a contradiction of these known facts: Act produced no draft in 0 of 6 rehearsal attempts before any fix, P-02 held in 1 of 2 live runs, Ask replies were cut at VOICE_TOKENS 300, politics deflection is not enforced, See turns and Act polish write no audit line, consent is display-only.
5. should_fix: unclear wording, weak but defensible claims, missing non-mandatory citations.
LANE B NOTE: the demo lane may be changing twin/pipelines/act.py (the Act draft loop), twin/pipelines/ask.py (the reply cut) and docs/DEMO.md while you check. For claims about those behaviours, report a mismatch as should_fix with "recheck in P2" rather than must_fix.
${doc.key === 'client' ? 'Also check the client doc never contradicts docs/ARCHITECTURE.md, uses only top-level beat ids (B1..B8, BX), and labels every capability today or roadmap.' : 'Also check the component map against the real module list (Glob twin/**/*.py) and docs/CONTRACTS.md.'}

For each item: file, quote (the exact sentence), problem, source (path:line and the value found, or "no source found"). go is true only when must_fix is empty. List the checks you ran.`
}

function revisePrompt(round, verdicts) {
  return `You are the Revise agent for PLAN_DEMO Session A, round ${round}. Edit only docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md. Never start the app or call a model.

${RESUME_FACTS}

Apply every must_fix item below. Apply a should_fix item when its fix is a cut, a roadmap relabel, a wording clarification, or copying an exact value you open and confirm in its source; leave "recheck in P2" items for phase P2.
- Never re-source by guessing: if you can't open the named source and see the value, cut the claim or relabel it roadmap.
- Keep the literal marker [latency: from rehearsal] for waits. Keep the numbered section order.
- Keep the two documents consistent with each other.
- Re-read every Mermaid fence you touch.

VERDICTS (JSON):
${JSON.stringify(verdicts, null, 1)}

Return what you applied and what you skipped, with reasons.`
}

async function docsLane() {
  const out = { rounds: [], revisions: [] }
  const check = async (round, prior) => {
    const res = await parallel(DOCS.map(d => () => advisor(a2Prompt(d, round, prior ? prior[d.key] : ''), `A2 ${d.key} r${round}`, 'Docs re-check')))
    const missing = DOCS.filter((d, i) => !res[i]).map(d => d.key)
    if (missing.length) throw new Error(`A2 failed for ${missing.join(', ')} in round ${round}`)
    return DOCS.map((d, i) => ({ lens: d.key, model: res[i].model, verdict: res[i].verdict }))
  }
  let vs = await check(1, null)
  out.rounds.push({ round: 1, must_fix: mustOf(vs), should_fix: shouldOf(vs) })
  log(`Docs re-check r1: ${mustOf(vs)} must_fix, ${shouldOf(vs)} should_fix`)
  let round = 1
  while (round < 3 && (mustOf(vs) > 0 || (round === 1 && shouldOf(vs) > 0))) {
    round++
    const rev = await agent(revisePrompt(round, compact(vs)), { label: `Docs revise r${round}`, phase: 'Docs revise', effort: 'low', schema: REVISE })
    if (!rev) throw new Error(`Docs revise r${round} returned null`)
    out.revisions.push({ round, applied: rev.applied.length, skipped: rev.skipped })
    const prior = {}
    vs.forEach(v => { prior[v.lens] = JSON.stringify(v.verdict.must_fix, null, 1) })
    vs = await check(round, prior)
    out.rounds.push({ round, must_fix: mustOf(vs), should_fix: shouldOf(vs) })
    log(`Docs re-check r${round}: ${mustOf(vs)} must_fix, ${shouldOf(vs)} should_fix`)
  }
  if (mustOf(vs) > 0) log(`Docs lane cap reached: ${mustOf(vs)} must_fix left for P2`)
  out.status = mustOf(vs) === 0 ? 'done' : 'open'
  out.final = compact(vs)
  return out
}

// ---------------- Demo lane (Session B remainder) ----------------
function reviewPresenter(round, extra) {
  return `You are the Review agent, presenter lens, for PLAN_DEMO Session B, round ${round}. Read-only: edit nothing, start nothing, call no model.

${RESUME_FACTS}

${DECISIONS}

Pretend you are the presenter at T-10 on this laptop with only docs/DEMO.md open. Walk every line:
- Can each command run exactly as written (Windows PowerShell 5.1, the paths, which window, the URL)? Is every exact input copy-pasteable and identical to docs/demo/beats.json?
- Do "point at" claims match what the rehearsal produced? Spot-check the run files and rehearsal.md (verdict, cited decisions, trace chunk ids, the Act trace) and a few screenshots in scripts/dev/demo/shots/ (open PNGs with Read: header, tab names, button labels).
- Does the main flow fit 10 minutes including talk time, and does the 5-minute cut fit, using measured waits? Are the waits in DEMO.md identical to rehearsal.md? Does the Appendix quote real output verbatim?
- Story for a business audience capturing expert judgment; Mara disclosed as synthetic; caveats (a)-(c) with the numbers; no politics beat; forbidden controls listed with exact on-screen labels and absent from the flow.
- The three DECISIONS: until DEMO.md, beats.json and (where approved) the app reflect each default, each is a must_fix. For the Act loop, read twin/pipelines/act.py and the B5 run files; if you confirm it is a demo-blocking app bug, write a must_fix whose problem text starts with "APPROVED APP FIX:" and names the file and the smallest change. Do the same for the reply cut only if you judge a small tested fix clearly worth it; otherwise ask for the input or talk-track change.
${extra ? 'LAST FIX (verify every change landed, the regression tests exist and pass, the live re-rehearsal evidence supports the DEMO.md claims, and nothing else broke):\n' + extra : ''}
must_fix = the presenter would fail, mislead the audience, or contradict the evidence. For each item: file, quote, problem, source (path:line or run file). go is true only when must_fix is empty. List the checks you ran.`
}

function reviewFailure(round, extra) {
  return `You are the Review agent, failure lens, for PLAN_DEMO Session B, round ${round}. Read-only: edit nothing and call no model. Allowed read-only checks: Get-Process -Id <pid from scripts/dev/demo/app.pid>, Get-NetTCPConnection -State Listen, curl.exe -s http://127.0.0.1:11434/api/ps, curl.exe -s http://127.0.0.1:1234/api/v0/models, nvidia-smi, Get-FileHash, Get-ChildItem data -Recurse -File, and (only after a fix round) $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider.

${RESUME_FACTS}

${DECISIONS}

For each failure mode, check docs/DEMO.md gives a concrete recovery, the tooling handles or detects it, and the evidence in scripts/dev/demo/ supports the timing claims: LM Studio down at T-10 or mid-demo (Stheno for Say it and Ask, and the Act embeddings); a Decide length retry (about 80 s) against the 60 s budget; a click during a queued pre-warm (for example B1 during the Act pre-warm, about 35 s); keep-alive expiry (big Ollama models 10 min, small 30 min, LM Studio JIT 10 min; T-5 to B2; long Q&A; the heartbeat holding nothing while Onboarding is active); the example-profile header warning and any stale-index warnings; port busy (7861-7870) and a leftover app or a stale app.pid; a model hang -> Status Free GPU -> a replay step; P-02 slipping (out of the live flow per DECISIONS); Act looping to the step limit or not calling search_profile; OLLAMA_MAX_LOADED_MODELS=1 eviction on interview turns; each prep FAIL line; the app window closed mid-demo.
The three DECISIONS are must_fix until reflected. For the Act loop, read twin/pipelines/act.py around 200-400 and the B5 run files; if you confirm it is a demo-blocking app bug, write a must_fix whose problem text starts with "APPROVED APP FIX:" and names the file and the smallest change.
Verify cleanup and data safety directly: no app process is listening on 7861-7870, /api/ps is {"models":[]}, nvidia-smi <= 200 MiB, the data/items/scores.json SHA-256 is unchanged, data/act_answer.txt is absent, data/ holds exactly the files in scripts/dev/demo/data_files_before.txt. After a fix round also verify app changes are minimal, each has a regression test that failed before the fix (evidence in the fix log), pytest is green with the new count, and scripts/dev/demo/post_fix_snapshot.json matches the files on disk.
${extra ? 'LAST FIX (verify each change landed and broke nothing):\n' + extra : ''}
must_fix = a likely failure with no recovery, a recovery that wouldn't work, a failed cleanup or data-safety check, or an unapproved or untested app change. For each item: file, quote, problem, source. go is true only when must_fix is empty. List the checks you ran.`
}

function fixPrompt(round, verdicts) {
  return `You are the Fix agent for PLAN_DEMO Session B, round ${round}. While you run, you are the ONLY agent allowed to start the app, touch the GPU or call a model (the docs lane never does).

${RESUME_FACTS}

${DECISIONS}

WHAT TO DO
1. Start a fix log at scripts/dev/demo/resume/fix_p1_r${round}.md (keep any earlier fix logs) and paste every command you run with its key output.
2. Apply every must_fix below, and should_fix items that are safe and local, to docs/DEMO.md, docs/demo/beats.json, scripts/demo_prep.ps1, scripts/demo_rehearse.py and scripts/dev/demo/rehearsal.md. Never edit docs/ARCHITECTURE.md or docs/CLIENT_TALKING_POINTS.md: put anything they need into notes_for_session_c.
3. App code only for items whose problem text starts with "APPROVED APP FIX:". For each: write the regression test first in tests/ (match the existing test style and mocking), run just that test and confirm it FAILS on the current code, make the smallest change, run it again and confirm it PASSES, then run the full suite with $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider (it must show ${PYTEST} plus the new tests passed and 0 failed). Add a DEMO.md section 9 "Known issues" line naming the file, the change, the test and the reviewer approval. Never change data/ artifacts, prompts that the evaluation evidence depends on (unless the item says so), or unrelated code. If a fix from an earlier attempt already exists on disk, verify its test and evidence instead of rewriting it.
4. P-02 decision: make its beats.json step optional and not in_cut; rewrite the DEMO.md beat table, 5-minute cut, talk track, fallbacks and Q&A so no deflection is promised live and the limit is stated plainly (Eval probes table instead). Keep python scripts/demo_rehearse.py --dry-run passing.
5. Live re-rehearsal whenever a GPU step, its tooling or the app code changed (always the case when an app fix landed): static checks (python -m py_compile scripts/demo_rehearse.py; --dry-run) -> demo_prep.ps1 (cold; every line PASS) -> demo_prep.ps1 -WarmOnly -> a full main-flow run: python scripts/demo_rehearse.py --run <next free number, starting at ${NEXT_RUN}> (detached with Start-Process -PassThru and redirected output, polled with short Start-Sleep plus Get-Content -Tail calls; each tool command is capped at 10 minutes) -> then the kept Act request at least 3 more times, each as its own run with --only <B5 warm step id>,<B5 request step id> -> if the reply-cut fix landed, check B4.1 in the full run -> stop the app: confirm the PID in scripts/dev/demo/app.pid is a python process listening on the port in app.port, then Stop-Process only that PID -> powershell -NoProfile -ExecutionPolicy Bypass -File scripts/free_gpu.ps1 -> confirm /api/ps is {"models":[]} and nvidia-smi <= 200 MiB (leave the LM Studio server running). Count drafts honestly: a draft is a real message text in the answer, not "I ran out of steps". Set b5_live true only if at least 2 of the 3 extra attempts drafted; otherwise make B5 trace-only in DEMO.md and beats.json.
6. Update scripts/dev/demo/rehearsal.md with a "Runs after fixes" section (per-step table, measured waits, Act draft count with quotes, B4.1 ending) and refresh the DEMO.md waits and Appendix for every changed step from the new run files. Confirm the scores.json hash, data/act_answer.txt absence and the data/ file list after the runs.
7. If nothing GPU-related changed this round, don't start the app; still confirm the cleanup state with read-only checks.
8. Last, write scripts/dev/demo/post_fix_snapshot.json (UTF-8 without BOM, via a small Python helper under scripts/dev/demo/resume/): {taken_at, pytest: {passed, failed, summary}, scores_json_sha256, data_files_match_baseline, act_answer_absent, code_last_write_utc: {relative path: UTC ISO time} for every file under twin/, tests/ and static/ (skip __pycache__ and .pyc) plus app.py}. Put its path in post_fix_snapshot.

VERDICTS (JSON):
${JSON.stringify(verdicts, null, 1)}

Report the truth in every field, including failed attempts.`
}

async function demoLane() {
  const out = { reviews: [], fixes: [] }
  const review = async (round, extra) => {
    const res = await parallel([
      () => advisor(reviewPresenter(round, extra), `Review presenter r${round}`, 'Demo review'),
      () => advisor(reviewFailure(round, extra), `Review failure r${round}`, 'Demo review'),
    ])
    if (!res[0] || !res[1]) throw new Error(`demo review failed in round ${round}`)
    return [{ lens: 'presenter', model: res[0].model, verdict: res[0].verdict }, { lens: 'failure', model: res[1].model, verdict: res[1].verdict }]
  }
  let vs = await review(0, '')
  out.reviews.push({ round: 0, must_fix: mustOf(vs), should_fix: shouldOf(vs) })
  log(`Demo review r0: ${mustOf(vs)} must_fix, ${shouldOf(vs)} should_fix`)
  let cleanup = null
  let round = 0
  while (round < 2 && (mustOf(vs) > 0 || (round === 0 && shouldOf(vs) > 0))) {
    round++
    const fx = await agent(fixPrompt(round, compact(vs)), { label: `Demo fix r${round}`, phase: 'Demo fix', schema: FIX })
    if (!fx) throw new Error(`Demo fix r${round} returned null; check listeners on 7861-7870, /api/ps and nvidia-smi`)
    out.fixes.push({ round, ...fx })
    cleanup = { api_ps_empty_after: fx.api_ps_empty_after, app_pid_stopped: fx.app_pid_stopped, gpu_mib_after: fx.gpu_mib_after }
    log(`Demo fix r${round}: app_code_changed=${fx.app_code_changed}, act_drafts=${fx.act_drafts || 'n/a'}, pytest=${fx.pytest_summary}, cleanup ok=${fx.api_ps_empty_after && fx.app_pid_stopped}`)
    vs = await review(round, JSON.stringify({ round, applied: fx.applied, app_changes: fx.app_changes || [], pytest_summary: fx.pytest_summary, runs_used: fx.runs_used, act_drafts: fx.act_drafts, b5_live: fx.b5_live, post_fix_snapshot: fx.post_fix_snapshot, fix_log: fx.fix_log }, null, 1))
    out.reviews.push({ round, must_fix: mustOf(vs), should_fix: shouldOf(vs) })
    log(`Demo review r${round}: ${mustOf(vs)} must_fix, ${shouldOf(vs)} should_fix`)
  }
  if (mustOf(vs) > 0) log(`Demo lane cap reached: ${mustOf(vs)} must_fix left`)
  out.cleanup = cleanup
  out.status = mustOf(vs) === 0 && vs.every(v => v.verdict.go) ? 'done' : 'open'
  out.final = compact(vs)
  return out
}

const LANES = (args && Array.isArray(args.lanes) && args.lanes.length) ? args.lanes : ['docs', 'demo']
log(`Lanes to run: ${LANES.join(', ')}`)
phase('Docs re-check')
const laneResults = await parallel([
  () => LANES.includes('docs') ? docsLane().catch(e => ({ status: 'blocked', reason: String((e && e.message) || e) })) : Promise.resolve({ status: 'skipped' }),
  () => LANES.includes('demo') ? demoLane().catch(e => ({ status: 'blocked', reason: String((e && e.message) || e) })) : Promise.resolve({ status: 'skipped' }),
])
const docs = laneResults[0] || { status: 'blocked', reason: 'docs lane returned null' }
const demo = laneResults[1] || { status: 'blocked', reason: 'demo lane returned null' }
log(`Docs lane: ${docs.status}. Demo lane: ${demo.status}.`)
return { docs, demo }
