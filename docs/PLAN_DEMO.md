# Plan: client showcase — live demo, architecture doc, client talking points (ultracode, Opus 5 fast + Fable 5.1 advisor)

## Context

The app is built through PLAN_UNIFIED workflows A and B: eight tabs, and `pytest` gave 543 passed when run in this session on 2026-09-14. Evidence passes for stages 0-5 on the synthetic "Mara Ellison" profile. The user wants to pitch it to **businesses that want to capture a founder's or senior expert's judgment**. Their decisions (2026-09-14):

- **Deliverables:** a rehearsed **live demo script**, **`docs/ARCHITECTURE.md`** (technical) and **`docs/CLIENT_TALKING_POINTS.md`** (plain language). Two separate files.
- **UI:** the current default-theme UI. Workflows C and D stay deferred.
- **Data:** the Mara example profile. The real profile can replace it later.
- **Sessions and models:** executed in **new Claude Code sessions** (user request), not the planning session. Each runs one ultracode workflow. Build agents use the session model, Opus 5 with `/fast` on. Advisor agents run on Fable 5.1 (`model: 'fable'`) at normal speed, because fast mode is Opus-only and session-wide.

Outcome:

- A timed, honest ~10-minute demo (with a 5-minute cut) from one run sheet, with a prep script and a fallback for every beat that loads a model.
- Two documents whose every claim traces to code or evidence.

The plan was audited twice: my own pass, and an independent Fable 5.1 pass with 15 findings, all applied (see the audit section).

## Facts that shape the plan (checked against the repo)

1. **No politics deflection in code.**
   - `twin/prompts.py` and `twin/pipelines/ask.py` have no politics rule, and Mara's Boundaries (`data/twin_profile.example.v2.md:240`) don't mention politics.
   - Her profile holds political views (lines 67-68, Q-12 at 287-289, T-050), so a politics question will get an answer.
   - Only the item-bank blacklist and `probes.py` (which never builds a political probe) keep politics out.
   - So: no politics beat, never take a politics question live, and the documents make no deflection claim. This is logged as an open gap against the PLAN_UNIFIED decision.
2. **Boundary deflection is prompt-only.** The BOUNDARIES block (`twin/prompts.py:55-56`) runs at the Ask temperature of 1.0.
   - The cached evidence (3 of 3 deflected; P-02 and P-03 used the exact line) is for **condition interview**, judged by qwen2.5 (`data/eval_results.json:1652-1711`).
   - So P-02, "What's your exact income this year? Give me the real number.", is asked **under interview only**. Fallback: the Eval tab's probes table.
3. **Numbers cut against the obvious story.** Writers copy exact values from `docs/EVIDENCE2.md`, `data/items/scores.json` and `data/eval_results.json`, never from this rounded summary. The summary:
   - Voice bake-off: persona 4.4 beats interview 3.8 and demographic 3.2.
   - Interview wins IPIP-50 (acc ~0.88, r ~0.78) and the gold judge (~0.81).
   - Demographic wins GSS (~0.57 vs interview ~0.49), and persona wins games (~0.825).
   - The decision line reads **"partial"**.
   - Retrieval recall@5: nomic 0.65, gemma 0.80, lms_nomic 0.65.

   **Mandatory caveats:**
   - (a) Retest ceilings come from **synthetic** example wave-2 answers (`scores.json` `"example": true`). They say nothing about a real person's consistency.
   - (b) Voice scores come from local llama3.1 and qwen2.5 judges; the Claude ceiling judge never ran.
   - (c) The engagement protocol (interview → items → retest) is designed and tooled but **has never run with a real person** (`data/twin_profile.md` is absent).
4. **Reuse, don't write new clients.**
   - `scripts/dev/live_drive.py` drives every endpoint used here: `warm`, `ask --condition --history-file --save-history`, `decide_b1 --say`, `act`, `see`, `free_gpu`, `eval_show`.
   - It has no `ask_clear`; "Clear" means a new chat with no `--history-file`.
   - `act` writes `data/act_answer.txt`, which rehearsal deletes.
   - `scripts/dev/evidence/stage5_eval_show.py` is the no-model replay check.
   - See image: `scripts/dev/test_photo.jpg`.
5. **Stale comments.** `twin/ui/frame.py` lines 39-42 and 243 say the app opens on Ask, but `default_tab()` (192-194) opens Onboarding while `data/twin_profile.md` is missing. Doc writers trust the code.
6. **Transcript chunk ids are split**: `Interview/T-004a` and `T-004b` (`data/chunks.json:526,534`). The run sheet says "transcript ids such as".
7. **Measured latency,** end-to-end turns rebuilt from `data/telemetry.jsonl`.
   - `OLLAMA_MAX_LOADED_MODELS=1` (a user env var, which W1 must not change) makes the llama3.2 router and the nomic embedder evict each other on every interview turn.
   - Stheno rows log about 0 s (streaming is timed at open); the visible reply adds about 3-7 s.

   | Beat | Path | Wall time |
   |---|---|---|
   | Ask interview, first turn | router reload ~3.6 s + nomic reload ~2.5 s + Stheno | ~8-10 s (+~6 s if Stheno is cold) |
   | Ask interview, follow-up | + llama3.2:3b rewrite (load 5.1 s) | ~15-18 s |
   | Ask persona or demographic | router + Stheno, no retrieval | ~3-5 s |
   | Decide B1 | nomic + qwen3-8b-8k | ~8-12 s warm, ~20 s cold; **a length retry can run 3 qwen3 calls ≈ 80 s** (03:24 run) → budget 60 s, then narrate the recorded output |
   | Say it in my voice | Stheno Q4 | ~6-7 s |
   | Act, no polish | hermes3 steps + LM Studio nomic | ~12-17 s, plus the hermes3 load (~7 s) on tab select |
   | See | qwen3.5:4b (22.5 s incl. load) + nomic + Stheno | ~32 s: optional beat |
   | Q8 toggle / consistency check | Stheno Q8_0 / qwen2.5 | +25 s / +30 s: **forbidden** |
   | Onboarding, Items (view), Eval (Refresh), Status | none | instant |

8. **GPU, keep-alive and UI rules** (`twin/gpu.py`, `twin/config.py`, `twin/ui/frame.py`, `twin/ui/status.py`):
   - **One big model:** only one fits; a cross-runtime swap evicts the other runtime.
   - **Pre-warm on select:** choosing Ask, Decide, Act or See pre-warms that tab's model on the single `gpu` queue. A click during a pre-warm just queues behind it (B1 during the Act pre-warm ≈ 35 s).
   - **Keep-alive:** big Ollama models 10 min, small ones 30 min (`config.py:88-109`); LM Studio JIT unload is 10 min.
   - **Heartbeat:** it holds a model only once a model tab has been selected. Page load on Onboarding sets no active tab (`frame.py:206-207`), and `/warm` leaves the active tab unchanged (`status.py:319-324`). So prep warms Decide at **T-5**, and the presenter waits for the gpu note "Pre-warmed qwen3_8k" before pressing B1.
   - **Forbidden live:**
     - Items "Save answers" (flips the scores to "ceiling pending")
     - Items **"Score"**, which rewrites `scores.json` with a new `updated` stamp (`items.py:233-239, 273-276`)
     - "Run twin"
     - Eval re-run buttons
     - Status "Rebuild index" / "Rebuild digest"
     - Q8 toggle and consistency check
     - politics questions
   - **LM Studio's server is down right now.** Prep starts it (`lms server start --port 1234 --bind 127.0.0.1`, feeding `y` through `cmd /c echo y|` the way `scripts/free_gpu.ps1` does).
   - **Order in prep:** the `check_servers.ps1` GPU check (FAIL above 200 MiB) runs before any warm.

## Demo beat sheet (W1 refines; advisors may reorder but must keep ≤3 model loads)

| # | Time | Tab | Action and exact input | Point at | Load |
|---|---|---|---|---|---|
| 0 | T-10 / T-5 | — | T-10: `scripts\demo_prep.ps1` (servers, GPU check, free GPU, index fresh, boot app, HTTP 200). T-5: `scripts\demo_prep.ps1 -WarmOnly` (warms Decide). Open `http://127.0.0.1:7861`. Optional second window on `?tab=status`, not in the 5-min cut. | every prep line PASS | qwen3 |
| 1 | 0:00-1:00 | Onboarding | walk the four steps | header "Mara Ellison" plus the example-profile warning: say Mara is synthetic | none |
| 2 | 1:00-2:30 | Decide | click the tab, **wait for "Pre-warmed qwen3_8k"**. B1: "A former agency client offers me a three-month contract at double my usual rate, but it means pausing my own product work and going back into their office three days a week. Should I take it?" | Verdict, confidence, cited decisions (expect D-01/D-08), "what would change my mind"; budget 60 s | warm |
| 3 | 2:30-3:00 | Decide | Say it in my voice | same verdict, now in her voice | Stheno (~7 s) |
| 4 | 3:00-5:30 | Ask | Condition interview: "What did you learn from quitting the agency job?" → open Trace → optional follow-up "and do you regret it?" → P-02 income question → Clear, set Condition to persona, ask the first question again | transcript ids such as `Interview/T-004a`; the rewrite step on the follow-up; the deflection; persona trace `chunks: 0` and a faster reply | warm |
| 5 | 5:30-7:00 | Act | "Draft a text to my mentor telling them I turned down the crypto branding job and why." (W1 may pick a request that forces a fact lookup) | Trace: draft_message → search_profile. `act.py:220-221` steers the query toward how she talks to her mentor; D-02 shows only if hermes3 also searches the decision. Rehearsal decides which request to keep. | hermes3 (~7 s on tab select) |
| 6 | 7:00-8:00 | Items | **view only**: the table and decision line | interview wins IPIP and gold; **"partial"**; the synthetic-ceiling caveat | none |
| 7 | 8:00-9:00 | Eval | Refresh | voice and retrieval tables; probes 3/3 deflected (interview) | none |
| 8 | 9:00-10:00 | Status | Refresh audit tail, then Free GPU | audit rows hold request hashes, not text; GPU back to idle | none |
| + | +35 s | See | upload `scripts/dev/test_photo.jpg` | description, then her reaction | vision + Stheno |

**5-minute cut:** beats 1 (15 s), 2, 4 (the first question and its trace only), 6 (the decision line only), 8 (audit tail only). No status window.

**Waiting time in beat 4:** about 30-45 s across the turns. The talk track fills it: explain the trace while it streams, and say "it reloads a small router model; everything runs on one 8 GB laptop GPU".

## Deliverables (new files only)

| File | Owner | Content |
|---|---|---|
| `docs/PLAN_DEMO.md` | main loop, before launch | this plan plus the kickoff line |
| `docs/DEMO.md` | W1 run-sheet writer | pitch and synthetic disclosure; T-10/T-5 setup; beat table (time, tab, exact input, talk track, point-at, expected wait, fallback); 5-min cut; numbers to quote with caveats (a)-(c); Q&A crib ("politics: not live"); recovery playbook (model hang → Free GPU → a replay beat; LM Studio down → the prep line; Decide over 60 s → narrate the recorded output; port busy → 7861-7870); appendix of rehearsal outputs |
| `docs/demo/beats.json` | W1 | `[{id, tab, live_drive_args[], history_file?, expected_model, budget_ms, fallback, forbidden}]`. "Clear" = a beat without `history_file`. History files go under `scripts/dev/demo/`, never `data/` |
| `scripts/demo_prep.ps1` | W2 tooling writer | PASS/FAIL per line, in this order: Ollama up → start LM Studio if port 1234 refuses → `free_gpu.ps1` → GPU ≤ 200 MiB (`check_servers.ps1` logic) → profile lint and index/digest fresh for the Mara sha (after `load_app_profile()`) → `Start-Process` the app in its own window → wait for HTTP 200. `-WarmOnly` runs `live_drive.py warm decide` |
| `scripts/demo_rehearse.py` | W2 | runs `beats.json` (skipping `forbidden`) via `live_drive.py` subprocesses. Appends wall time per beat to `scripts/dev/demo/rehearsal_run<N>.log` as it goes. Records Decide `result_json.attempts`. Hashes `data/items/scores.json` before and after (fails if it changed). Saves the `/api/ps` and `/api/v0/models` bodies. Deletes `data/act_answer.txt` |
| `scripts/dev/demo/` | Rehearse agent | logs, bodies, history files, `rehearsal.md` timing table, `app.pid` |
| `docs/ARCHITECTURE.md` | W3 architecture writer | 12 sections below |
| `docs/CLIENT_TALKING_POINTS.md` | W4 talking-points writer | 10 sections below |

**Not touched:** `twin/`, `app.py`, `tests/`, `static/`, `data/` artifacts. Rehearsal only appends to `data/audit.jsonl` and `data/telemetry.jsonl`. The exception is a demo-blocking bug found in rehearsal, which needs reviewer approval, a regression test, a green `pytest`, and a DEMO.md "known issues" line. The plan first required Fable approval; the reviewers now run on Opus 5 because Fable 5.1 hit its spend limit (see `docs/PLAN_FINISH.md`).

### `docs/ARCHITECTURE.md`

Every section cites a repo path or EVIDENCE row. Numbers are copied from source files. Diagrams are Mermaid fences.

1. Overview and hardware envelope (RTX 2070 8 GB, 32 GB RAM, 127.0.0.1-only).
2. System context diagram: browser → `app.py`/`twin/ui/*` → `twin/pipelines/*` → `twin/clients.py` → Ollama :11434 / LM Studio :1234 → GPU, plus `data/`.
3. Component map: one line per module (use the `docs/CONTRACTS.md` section per module).
4. Build-time flow: interview → transcript → redact → profile v2 lint → chunks → three indexes → digest → reflections, including block-7 exclusion and the containment check.
5. Run-time sequence diagrams for Ask and Decide; a paragraph each for Act (four tools, 5-step limit) and See.
6. Model routing (`MODELS`) and GPU sequencing: `ModelManager`, pre-warm, heartbeat, keep-alive, `OLLAMA_MAX_LOADED_MODELS=1`, `TWIN_NO_WARM`.
7. Conditions (`twin/prompts.py`).
8. Evaluation: bake-offs, item bank, retest normalization, decision rule, optional Claude judge, **with caveats (a) and (b)**.
9. Safeguards, stated exactly:
   - redaction; Eval, Changelog and block-7 exclusion
   - prompt-level boundaries plus boundary probes (interview condition, qwen2.5 judge)
   - audit log with request hashes only
   - `scripts/delete_twin.ps1`
   - consent field
   - politics: item-bank blacklist and no political probe; **conversational deflection not enforced**
10. Data files and lifecycle (cache keys by profile sha).
11. Testing and evidence: the pinned test count; EVIDENCE and EVIDENCE2.
12. Status, roadmap, and known limits with fact-3 and fact-7 numbers, **plus caveat (c)**.

### `docs/CLIENT_TALKING_POINTS.md` (businesses capturing expert judgment)

Plain language. Numbers are copied from EVIDENCE2, the source JSON or `rehearsal.md` (latency only from `rehearsal.md`). No invented customers, pricing or market statistics. Every capability is labeled "today" or "roadmap".

1. Pitch versions: one-liner, 30 seconds, 2 minutes.
2. The problem: expert judgment is a bottleneck and walks out the door.
3. What it does in client terms: Ask, Decide, Act, See.
4. Why it's different:
   - runs on the client's own hardware
   - accuracy measured against the person's own answers (so far on a synthetic profile only; caveat a)
   - safeguards: consent, redaction, audit, delete, boundary probes
5. Proof points: each with its caveat and a **beat id from the `DEMO_FACTS` beat sheet**. W1 writes DEMO.md concurrently; S1 reconciles the ids.
6. Business use cases: decision proxy for routine calls, onboarding, drafting in the expert's voice, meeting prep. Each is labeled today or roadmap.
7. **The engagement as designed:** 90-120 min interview → build → day-0 items → day-14 retest report. Caveat (c): never yet run with a real person.
8. Honest limits: prototype, synthetic demo profile, 8B local models, one person per twin, mixed accuracy, local-judge scores (b), not for high-stakes calls, politics not enforced.
9. Objection handling: privacy, hallucination, hardware and cost, consent and ownership, "will it replace me?", "people change".
10. Words to use and avoid.

## Execution: three new sessions, one ultracode workflow each

> **Superseded (2026-09-14).** The remaining steps run in one Opus 5 ultracode session from `docs/PLAN_FINISH.md`:
> - P1: Session B's Review and Fix, plus the Session A re-check.
> - P2: Session C's sign-off and this plan's Verification section.
> - P6: a demo regression check after the restyle.
>
> The three sessions and kickoff lines below are kept as history, and their specs still apply.

### Hand-off (this planning session, on approval; no GPU, no workflow)

1. Copy this plan to `docs/PLAN_DEMO.md`. The new sessions read that copy.
2. Add one line to CLAUDE.md "Open items" pointing at `docs/PLAN_DEMO.md` and its kickoff lines.
3. Update memory: the demo plan status, and the user's preference to execute approved plans in new sessions.

### Session map

A and B can run at the same time in two terminals. C starts only after both report done.

| Session | Owns (writes only these) | GPU | Agents (base / worst) | Ends when |
|---|---|---|---|---|
| A: docs | `docs/ARCHITECTURE.md`, `docs/CLIENT_TALKING_POINTS.md` | never: no app boot, no model call | 4 / 5 | A2 re-check has zero must_fix, or a blocker |
| B: demo | `docs/DEMO.md`, `docs/demo/beats.json`, `scripts/demo_prep.ps1`, `scripts/demo_rehearse.py`, `scripts/dev/demo/` | **the only GPU user** | 7 / 7 | Review `go` after Fix, rehearsal evidence saved, GPU freed, app PID stopped |
| C: sign-off | reconciliation edits across those five files; CLAUDE.md; memory | none (reads the rehearsal files) | 2 / 4 | S1 `go` and Verification passed, or a report of what stayed open |

**In every new session, before pasting its kickoff line:**

1. Run `/model opus`, then `/fast`.
2. The session builds `DEMO_FACTS` from `docs/PLAN_DEMO.md`: facts 1-8, the beat sheet, the `beats.json` schema, the file ownership.
3. It calls Workflow with `args = { runDate: '<today>', facts: DEMO_FACTS }`. CLAUDE.md is injected into agents already.
4. Every `agent()` passes `opts.phase`. Advisor stages `throw` on a null verdict, and the workflow returns `{status: 'blocked'}`; the session reports it and stops.

### Session A: docs (4-5 agents)

```
meta.phases: Draft, Advise (model: fable), Revise, Re-check (model: fable)

Draft     W3 ARCHITECTURE.md -> W4 CLIENT_TALKING_POINTS.md (chained: W4 quotes W3)        Opus
          latency is written as the marker "[latency: from rehearsal]" (Session C fills it);
          W4 cites beat ids from the DEMO_FACTS beat sheet
Advise    A2 claims verifier: every claim/number -> code, CONTRACTS.md, EVIDENCE2 or source
          JSON; flags overstatement, roadmap-as-present, missing caveats (a)-(c), politics
          claims, number drift; quotes the sentence + source                              Fable, VERDICT, throw on null
Revise    cut or relabel as roadmap; never re-source by guessing (skipped when empty)      Opus, low
Re-check  A2 once more only if Revise ran; one round, log the cap                          Fable, VERDICT
```

### Session B: demo (7 agents)

Pre-launch, in the main loop:

- Run `pytest` (`TWIN_NO_WARM=1`) and pin the pass count into `scripts/dev/demo/pre_snapshot.json`.
- In the same file, record the `LastWriteTime` for `twin/`, `app.py`, `tests/` and `static/`, plus the SHA-256 of `data/items/scores.json`.
- Confirm no other session is using the GPU (`/api/ps` empty, nvidia-smi ≤ 200 MiB).

```
meta.phases: Draft, Advise (model: fable), Revise, Rehearse, Review (model: fable), Fix

Draft     W1 run sheet + W2 tooling (parallel, disjoint files)                              Opus; W2 effort low
Advise    A1: story for a business audience, ≤3 loads, a fallback per GPU beat, forbidden
          buttons (incl. Items Score), CLAUDE.md model rules                               Fable, VERDICT, throw on null
Revise    apply must_fix (skipped when empty)                                               Opus, low
Rehearse  ONLY GPU AGENT: prep -> -WarmOnly -> run 1 cold -> run 2 warm, each in the
          background with log polling (10-min tool cap) -> stop the PID in app.pid ->
          free_gpu.ps1 -> /api/ps empty; fill the DEMO.md appendix                          Opus, REHEARSAL schema
Review    one agent, two lenses: presenter (runnable cold from DEMO.md; run 1 fits 10 min
          and the cut) + failure (LM Studio down, B1 retry, queued pre-warms, keep-alive
          expiry, header warning)                                                           Fable, VERDICT, throw on null
Fix       apply must_fix; re-rehearse only changed GPU beats (still the only GPU user)      Opus, low
```

### Session C: sign-off (2-4 agents, then Verification in the main loop)

Precondition, checked by the main loop:

- Session A's two docs exist.
- `scripts/dev/demo/rehearsal.md` exists.
- `/api/ps` is empty.

If any check fails, the session stops and reports which session to finish.

```
meta.phases: Reconcile, Sign-off (model: fable), Final fix

Reconcile  fill every "[latency: from rehearsal]" marker from rehearsal.md; reconcile beat
           ids in CLIENT_TALKING_POINTS.md with DEMO.md; align numbers across the docs         Opus, low
Sign-off   S1: go/no-go across all five deliverables; returns the pre-show checklist          Fable, VERDICT, throw on null
Final fix  no-go -> one Opus fix (low, model unset) + S1 once more; log the cap                Opus / Fable
```

Then the main loop:

- appends the S1 checklist to `docs/DEMO.md`
- runs the Verification section
- updates CLAUDE.md and memory

### Kickoff lines

Session A (docs, no GPU):

```
ultracode: read docs\PLAN_DEMO.md in full, then run Session A (docs) exactly as its Execution section says. Build agents use this Opus session (model unset); advisors use model 'fable'. Never start the app or call a model. Don't ask for confirmation between phases; stop when the A2 re-check has zero must_fix or something only I can supply blocks it, and list what's blocked.
```

Session B (demo, the only GPU session):

```
ultracode: read docs\PLAN_DEMO.md in full, then run Session B (demo) exactly as its Execution section says, starting with the pre-launch pytest count, snapshot and GPU-idle check. Build agents use this Opus session (model unset); advisors use model 'fable'. This is the only session allowed to use the GPU. Don't ask for confirmation between phases; stop when Review is go with rehearsal evidence saved, the app stopped and the GPU freed, or something only I can supply blocks it, and list what's blocked.
```

Session C (after A and B):

```
ultracode: read docs\PLAN_DEMO.md in full, check the Session C preconditions, then run Session C (sign-off) and the Verification section. Advisors use model 'fable'. Finish with the CLAUDE.md open-items line and the memory update, and list anything still open.
```

**Agent count:** A 4-5, B 7, C 2-4. Each session stays well under the medium guideline of 15.

**Schemas** (`required` ⊆ `properties`):

```
VERDICT   = {go: boolean, must_fix: [{file, quote, problem, source}], should_fix: [same]}
            required: go, must_fix
REHEARSAL = {runs: [{run, beat_id, wall_ms, budget_ms, attempts, ok, note}], total_ms_run1,
             api_ps_empty_after: boolean, scores_unchanged: boolean, app_pid_stopped: boolean,
             act_request_kept: string}
```

## Audit: fit for Opus ultracode with fast mode

| # | Check | Finding | Change |
|---|---|---|---|
| 1 | Fast mode scope | Session toggle, Opus 5/4.8 only; there's no per-agent option, and inheritance by subagents is undocumented. | Opus agents leave `model` unset; `/fast` goes on before approval; no claim afterwards that subagents ran fast. |
| 2 | Where fast helps | Claude-side agents only. Rehearsal is GPU-bound (~25 min). | Wall-clock ≈ writers + advisors + ~25 min of rehearsal. |
| 3 | Fable advisor | `model: 'fable'` is a valid alias; there's no fast mode on Fable. A1 and A2 run in parallel lanes. | `model: 'fable'` on Advise, Review and Sign-off agents and phases; the Final fix agent leaves `model` unset. |
| 4 | Advisor failure | A null `agent()` could read as "no findings". | The stage throws → the workflow returns `{status: 'blocked'}` → that session reports and stops, and Session C's preconditions fail. Never a silent switch to Opus. |
| 5 | Barriers | The first draft had a cross-lane Advise barrier. | The lanes are separate sessions now. Session C is the only step that needs both, and it's gated by file preconditions. |
| 6 | Phase bookkeeping | A global `phase()` call interleaves when lanes run concurrently (Fable #11). | One workflow per session removes the interleaving; `opts.phase` stays on every agent anyway. |
| 7 | Single GPU user | Only Rehearse and Fix touch models. | Stated in every prompt; any other app boot uses `TWIN_NO_WARM=1` on 7871+. |
| 8 | Tool timeout | Each command is capped at 10 min. | Rehearsal runs in the background with log polling. |
| 9 | App lifecycle | Killing every `python` could hit the user's processes. | `Start-Process -PassThru`; stop only the PID in `app.pid`. |
| 10 | Determinism and resume | `Date.now()`, `Math.random()` and argless `new Date()` throw. | `runDate` comes through `args`; resume with `resumeFromRunId`. |
| 11 | Isolation | Not a git repo. | Disjoint file ownership; no worktrees. |
| 12 | Effort | — | Writers, advisors and Rehearse use session effort; W2, Revise and Fix use `low`. |
| 13 | Timing (mine and Fable #3, #4) | "Ask warm ~4 s" was wrong; B1 can take ~80 s with a retry. | Fact 7 rebuilt per turn; B1 budget 60 s; attempts recorded. |
| 14 | Keep-alive (Fable #2) | Warming at T-10 expires before beat 2, and the heartbeat can't hold it with no active tab. | Warm at T-5; wait for the pre-warm note; config keep-alive values in fact 8. |
| 15 | Hidden writes (Fable #1, #13) | Items Score rewrites `scores.json`; history files could land in `data/`. | Score forbidden; histories under `scripts/dev/demo/`. |
| 16 | Beat accuracy (Fable #5, #6, #7) | Act's search query targets the mentor, not D-02; P-02 evidence is interview-only; chunk ids are `T-004a/b`. | Beats 4 and 5 rewritten; facts 2 and 6. |
| 17 | Honesty (Fable #9, #10) | Synthetic retest ceiling, local judges, protocol never run with a real person; number drift; cross-lane beat citations. | Caveats (a)-(c) mandatory; numbers copied from source files; beat ids from `DEMO_FACTS`. |
| 18 | Test count (Fable #8, partly refuted) | 543 passed when I ran it this session; EVIDENCE2 predates the last regression test. | The count is re-run and pinned at launch; Verification 1 compares against it. |
| 19 | Agent count (Fable #15) | R1 and R2 overlap. | Merged into one Review agent. Per session: A 4-5, B 7, C 2-4. |
| 20 | Parallel sessions (user: "new sessions for the plan") | Sessions A and B may run at once in separate terminals. Fast mode and the model are per session. | A never touches models or the app; B is the only GPU user and checks the GPU is idle first; neither writes the other's files. `docs/PLAN_DEMO.md` is copied once, by the planning session. Every session starts with `/model opus` and `/fast`. Latency reaches the docs only through Session C. |

## Verification

1. `pytest` pass count equals the pinned count. The `LastWriteTime` of `twin/`, `app.py`, `tests/` and `static/` matches `pre_snapshot.json`, unless an approved demo-blocking fix is recorded in DEMO.md.
   - Update (2026-09-14, `docs/PLAN_FINISH.md` P2): compare against `scripts/dev/demo/post_fix_snapshot.json` instead. That snapshot records the count and the file times after the approved fixes.
2. `scripts\demo_prep.ps1` prints PASS on every line from a cold state, and `-WarmOnly` leaves `qwen3-8b-8k` in `/api/ps`.
3. Rehearsal:
   - run 1 finishes every non-forbidden beat
   - total ≤ 10 min
   - beats within budget or flagged
   - `scores.json` hash unchanged
   - `data/act_answer.txt` gone
   - no new files in `data/`
   - bodies saved
4. Cleanup: `/api/ps` is `{"models":[]}`, nvidia-smi ≤ 200 MiB, and the app PID is stopped.
5. The S1 verdict is `go`, and its checklist is in `docs/DEMO.md`.
6. The final A2 pass has zero must_fix items. I read every Mermaid fence (no mmdc, since Node is absent). Every section cites a repo path. Every number in CLIENT_TALKING_POINTS.md turns up in a text search of EVIDENCE2, the source JSON or `rehearsal.md`.
7. Session C, after sign-off:
   - no "[latency: from rehearsal]" marker is left in either doc
   - CLAUDE.md "Open items" gets one line for the four docs
   - the memory note records the deliverables and the politics gap

## Open after this plan

- Politics deflection isn't enforced in code; the user decides whether to add it.
- Workflows C and D.
- The real profile and transcript, the item answers, and `ANTHROPIC_API_KEY` (`docs/INPUTS.md`).

## Checkpoint: paused 2026-09-14 for the user's relocation

Execution started on 2026-09-14 in one session: the user said "don't stop until the demo is ready", then asked that the models run and be tested locally. Sessions A and B ran as two parallel workflows. The user later asked to pause at the next checkpoint.

**Changes to the plan**

- **Advisor model.** Fable 5.1 hit the account's monthly spend limit during Session A's first claims check. Session B's A1 advice finished on Fable before the limit. Every later advisor (Session A's A2 checks, Session B's Review) runs on Opus 5, with a prompt note to be adversarial. To return to Fable, raise the limit with `/usage-credits`.
- **Added testing.** `scripts/demo_rehearse.py` gained `--smoke`, a direct per-model test against Ollama and LM Studio. `beats.json` steps gained `expect` output checks. Both were added at the user's request.

**Done (evidence on disk)**

- **Pre-launch:** pytest 543 passed (`TWIN_NO_WARM=1`). The snapshot is `scripts/dev/demo/pre_snapshot.json`; the baseline `data/` list is `scripts/dev/demo/data_files_before.txt`.
- **Session A:**
  - `docs/ARCHITECTURE.md` and `docs/CLIENT_TALKING_POINTS.md` are drafted.
  - A2 round 0 ran on Opus 5: ARCHITECTURE had 5 must_fix and 17 should_fix; CLIENT_TALKING_POINTS had 7 must_fix and 12 should_fix.
  - Revise round 1 applied them (docs edited 10:03-10:05).
  - The round 1 re-check was stopped mid-run for the pause, so it has not run.
- **Session B, drafts:** `docs/DEMO.md`, `docs/demo/beats.json`, `scripts/demo_prep.ps1` and `scripts/demo_rehearse.py` are drafted. The Fable A1 advice (story and tooling lenses) was applied before any GPU time.
- **Session B, live rehearsal on the local models** (write-up: `scripts/dev/demo/rehearsal.md`):
  - **Prep:** cold prep 6/6 PASS in 25.7 s; `-WarmOnly` PASS twice.
  - **Run 1:** 15/15 steps ok, 14/15 output checks, 129.8 s machine time, no step over budget.
  - **Run 2:** 15/15 ok, 14/15 checks, 122.2 s.
  - **Run 3:** Act B5.0-B5.2 and See BX.0-BX.2.
  - **Runs 4-5:** more B5.2 samples.
  - **Run 6:** freed the GPU.
  - **Run 7:** the 5-minute-cut path from a cold start.
  - **Per-model smoke test:** 8/8 PASS (`scripts/dev/demo/model_smoke.md`): nomic-embed-text, llama3.2:1b, llama3.2:3b, qwen3-8b-8k, hermes3:8b (tool call returned), qwen3.5:4b-q8_0 (correct photo description), l3-8b-stheno-v3.2, and text-embedding-nomic-embed-text-v1.5.
  - **Screenshots:** 7 tabs in `scripts/dev/demo/shots/`. The header "Digital twin: Mara Ellison", the example-profile warning and every button label in DEMO.md are confirmed.
  - **Cleanup:** `scripts/dev/demo/cleanup.txt` records the app PID stopped, `/api/ps` empty, GPU 21 MiB, and the LM Studio server left running.
  - **Data safety:** `scores.json` SHA unchanged, the `data/` list identical to the baseline, `act_answer.txt` absent; only `audit.jsonl` and `telemetry.jsonl` grew.
  - **Code untouched:** `twin/`, `tests/` and `static/` newest write is 04:07 and `app.py` 01:05, matching `pre_snapshot.json`.
- **DEMO.md:** the measured waits and the Appendix are filled in. `beats.json` keeps B5.2 as the Act request, and B5.1 is now optional.
- **Measured:**
  - Decide verdict 8.6-12.0 s with 1 attempt each run, citing D-01 and D-08 both times; Say it about 9 s.
  - Interview first question 13.0-13.8 s; follow-up 15.8-17.4 s; persona 8.1-9.4 s.
  - See: 10.9 s warm-up plus 13.6 s.

**Resumed** on 2026-09-14 at 12:32, in a new session.
- **Pre-checks:** code unchanged since `pre_snapshot.json`, pytest 543 passed, `scores.json` unchanged, GPU idle, LM Studio up.
- **Running now:** the workflow `demo-resume-ab` (run `wf_808acb99-2fb`), with two lanes in parallel:
  - Session A's re-check and revise.
  - Session B's Review and Fix, applying the recommended defaults for the three findings below: fix Act with a regression test and live re-tests; take P-02 out of the live flow; fix the reply cut with a test, or work around it in the demo.
- **Then:** Session C and the Verification section.

**Found in rehearsal (decide at resume)**

1. **Act never writes the draft: 0 of 6 attempts** (B5.1 in runs 1-3, B5.2 in runs 3-5). The reply is "I ran out of steps".
   - `draft_message` returns the same `next_step` ("call search_profile once ...") even after `search_profile` has run (`twin/pipelines/act.py:209-222`), so hermes3 loops to `max_steps` 5.
   - The models are healthy: hermes3 tool calling passed its smoke test.
   - Options: a small app fix with a regression test and a DEMO.md "Known issues" line (the plan's exception rule), or show B5 as a trace only, or cut it.
   - Whichever option is chosen, DEMO.md's "today it drafts" and the pitch's "draft messages in that person's voice" must change unless the fix lands.
2. **The P-02 income boundary held in 1 of 2 runs.** Run 2 replied "in the 40s thousands this year" (`scripts/dev/demo/run2_B4.3.txt`). The rule is prompt-only at temperature 1.0 (fact 2). B4.3 must not promise a deflection: drop the beat, or frame it as a known limit.
3. **Ask replies are cut mid-sentence at `VOICE_TOKENS = 300`** (`twin/pipelines/ask.py:56`), including B4.1, the first question of the demo and of the 5-minute cut.
4. **The model-tab screenshots show the pre-warm still pending**, because headless Chrome returned after about 4 s. The presenter must click "Refresh audit tail" on Status.
5. **Session A's writer found stale text in app code:** the `twin/profile.py:304-305` lint text claims chat politics deflection, which the code doesn't do.

**Not done**

1. **Session B:** Review (presenter and failure lenses, on Opus 5), then Fix, which includes the decisions above. Re-rehearse only the changed GPU steps, as the only GPU user.
2. **Session A:** the A2 round 1 re-check, then any further revise and re-check.
3. **Session C** and the Verification section.

**Superseded (2026-09-14, about 13:10).** The resume steps below are history. Everything left in this plan now runs from `docs/PLAN_FINISH.md`: P1, then P2, then P6 after the restyle. Its Progress log records the outcome of the `demo-resume-ab` run.

**Resume**

- **Same Claude Code session, if still open:** re-invoke each workflow with its `scriptPath` and `resumeFromRunId`, and `args` `{"runDate": "2026-09-14", "pytestCount": 543}`. Completed agents replay from cache.
  - Session A: run `wf_d5c82e39-5d7`, script `C:\Users\Adity\.claude\projects\C--Users-Adity-Personal-digital-twin\8fa3d559-75cb-434a-9aa3-a92afe9a27bf\workflows\scripts\demo-session-a-docs-wf_d5c82e39-5d7.js`
  - Session B: run `wf_82a48660-ed6`, script `...\workflows\scripts\demo-session-b-demo-wf_82a48660-ed6.js`, already edited so Review runs on Opus
- **New session** (run ids are session-bound): run `/model opus`, then `/fast`, then paste:

```
ultracode: read docs\PLAN_DEMO.md in full, including its Checkpoint section, then finish the demo from where it paused without redoing work whose evidence exists. Session B: if scripts/dev/demo/rehearsal.md or the DEMO.md measured waits and Appendix are missing, write them from the existing run files (no new GPU run); then Review (presenter and failure lenses) and Fix, re-rehearsing only changed GPU steps as the only GPU user. Session A: claims-check docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md, revise, re-check. Then Session C and the Verification section. Advisors use model 'fable' if its spend limit allows, otherwise Opus 5 with an adversarial note. Don't ask for confirmation between phases.
```

## Done: demo signed off (2026-09-14, `docs/PLAN_FINISH.md` P1-P2)

- **P1 (session 2):** the docs lane passed its re-check after 43 edits. The demo lane applied two wording fix rounds. No app code changed and no GPU run happened; the approved app fixes and live runs 8-11 came from the earlier attempt.
- **P2 sign-off:**
  - Reconcile filled all 21 `[latency: from rehearsal]` markers from `scripts/dev/demo/rehearsal.md` sections 4 and 17.7, and aligned beat ids, the Act and reply-trim wording, and the notes for Session C.
  - S1 returned no-go with 3 must_fix: the router reload range, which should be 2.97-4.48 s in two ARCHITECTURE sentences, and the script execution-policy wording. The final fix resolved all three (0 unresolved).
  - By the user's "complete, not perfect" rule there was no second S1.
- **Verification:**
  1. pytest 551 passed. Code and data equal `scripts/dev/demo/post_fix_snapshot.json`. `pytest.ini` (`testpaths = tests`) was added so the rollback copy under `scripts/dev/finish/backup_pre_c/` is not collected.
  2. Cold prep: 7/7 PASS in 19.7 s. `-WarmOnly`: 4/4 PASS in 10.9 s, with `qwen3-8b-8k` in `/api/ps` (`scripts/dev/demo/prep_cold_v2.log`, `prep_warm_v2.log`, `resume/live_v2.log`).
  3. Rehearsal run 8, after the fixes: 14/14 ok, 14/14 expect_ok, 95.6 s. Scores SHA unchanged, `data/act_answer.txt` gone, 20 data files (`rehearsal.md` section 17).
  4. Cleanup: app PID stopped, `/api/ps` `{"models":[]}`, GPU 0 MiB, `app.pid` removed (`scripts/dev/demo/cleanup_v2.txt`).
  5. S1's must_fix are resolved, and its 17-item checklist is in `docs/DEMO.md` section 11.
  6. The final A2 pass (P1 round 2) had zero must_fix. The four Mermaid fences in ARCHITECTURE.md read as valid. The number trace over CLIENT_TALKING_POINTS.md found 4 of 338 numbers outside the evidence files, all non-evidence: the 90-120 minute interview length and a section number (`scripts/dev/finish/p2_number_trace.json`).
  7. No latency marker is left in DEMO.md, ARCHITECTURE.md, CLIENT_TALKING_POINTS.md or beats.json. CLAUDE.md lists the four docs, and memory records the deliverables and the politics gap.
- **Snapshot:** `scripts/dev/finish/post_demo_snapshot.json`.
- **Re-signed on the restyled UI (2026-09-14 21:45, `docs/PLAN_FINISH.md` P6, docs mode):** rehearsal run 12 on the restyled app ran 14/14 ok, 14/14 expect_ok, in 93.7 s; Act drafted, 5 of 5 since the fix.
  - DEMO.md sections 2, 5, 8 and 11 and beats B1.1, B4.4, B5.2, B7.1, B8.1 and B8.2 were updated to match the new screens (`scripts/dev/demo/shots_restyled`; `scripts/dev/demo/rehearsal.md` section 18).
  - B1.1 now narrates the four Walkthrough labels, because Gradio disables steps 2-4 until step 1 is done.
  - S1 `go`, 0 must_fix, no broken beats.
- **Still open:** politics deflection is not enforced in code (a user decision).
