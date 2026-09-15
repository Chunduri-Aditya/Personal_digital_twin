# PLAN_FINISH: finish the demo, restyle and integrate, then the Mac guide

One Opus 5 ultracode session runs everything left in this project, phase by phase, with a checkpoint after each phase. The user approved this plan on 2026-09-14.

It replaces the execution sections of two older plans:
- `docs/PLAN_DEMO.md`: its three-session execution.
- `docs/PLAN_UNIFIED.md` §8: its kickoff line.

Their specs, facts and verification steps still apply wherever this file doesn't change them.

**User decisions (2026-09-14):**
- **Scope, in this order:**
  1. Finish the demo.
  2. Run PLAN_UNIFIED workflows C (per-tab restyle) and D (integrate, live sanity, critics).
  3. Write `docs/REPLICATE_ON_MAC.md` and build new zips.
- **Session setup:** Opus 5 with 1M context, ultracode on, fast mode off.
- **Pace (changed 2026-09-14, about 15:45):** the plan first said run straight through. The user then asked: finish P2, then at the end of every phase write the checkpoint (Progress log and `state.json`) and ask the user before starting the next phase.
- **Advisors and critics:** Opus 5 only. Fable 5.1 is over its monthly spend limit and fails within about a second.
- **Complete, not perfect (2026-09-14, about 15:30, during P1 session 2):** the user saw review rounds keep finding new small items and asked for a finished result over a polished one.
  - Every review cycle is one review plus at most one fix: no re-review, no second S1, no critic re-run, no fallback rerun for wording.
  - must_fix means a real blocker (broken behaviour, failing tests or commands, a broken DEMO CONTRACT, GPU or data safety, a false claim a client would hear). Everything else is should_fix.
  - The gates are the mechanical checks in the main loop (pytest, view_api, contrast, selector grep, scrollWidth, dry-run, markers, GPU idle, scores SHA) plus "no unresolved must_fix" from the fixer.
  - The phase scripts in `scripts/dev/workflows/` were changed to match.

## Start here

1. In PowerShell, in `C:\Users\Adity\Personal_digital_twin`, run `claude`. The default model is Opus 5 with 1M context (`"model": "opus[1m]"` in `C:\Users\Adity\.claude\settings.json`). Confirm with `/model`.
2. Keep fast mode off.
   - settings.json has no `fastMode` key, so a new session starts with fast mode off.
   - `/fast` is a toggle: run it only if the status line shows fast mode.
3. Run `/effort ultracode`. The CLI flag `--effort` accepts only low, medium, high, xhigh and max, so ultracode has to be set inside the session.
4. Paste:

```
ultracode: read docs\PLAN_FINISH.md in full and run it from the first phase its Progress log does not mark done: the Phase 0 preflight, then each phase's workflow from scripts\dev\workflows\ (write the phase's script from its spec when it doesn't exist yet), its gate and verification, and a Progress log checkpoint. Advisors and critics run on Opus 5 with the adversarial note; never use Fable. Fast mode stays off. After each phase's checkpoint, ask me before starting the next phase. Stop at a failed gate, a blocked or open workflow, repeated agent failures, or anything only I can supply, and name the phase to resume from.
```

To pause, say "pause at the next checkpoint". To resume later, repeat steps 1-4.

## Progress log

At the end of every phase, before the next one starts, the session updates this table and `scripts/dev/finish/state.json` (same content).

| Phase | Status | Finished | Workflow | Result | pytest | Next |
|---|---|---|---|---|---|---|
| P0 | runs at every session start | | main loop | | | |
| P1 | **done** (complete, not perfect) | 2026-09-14 15:31 | `finish-p1-demo-ab.js` run `wf_03f85416-226` (session 2; stopped during its last read-only review round at the user's request; journal copied to `scripts/dev/finish/p1_journal_wf_03f85416-226.jsonl`) | docs lane: revise r2 applied 43 edits, then ARCHITECTURE and CLIENT re-checks both `go`; demo lane: Demo fix r1 and r2 (DEMO.md, beats.json, rehearsal.md 17.11-17.12, approval texts in fix_r2.md section 13; no app code, no GPU run), presenter review r1 `go`, failure review r1's 2 must_fix fixed in r2; gate: code and data equal `post_fix_snapshot.json`, both dry-runs OK, GPU idle; 21 latency markers left for P2 | 551 | P2 |
| P2 | **done** | 2026-09-14 about 16:10 | `finish-p2-demo-signoff.js` run `wf_9aa92837-79e` (3 agents) | Reconcile filled the 21 latency markers (0 left) and aligned beat ids and outcome wording; S1 no-go with 3 must_fix, all resolved by the final fix (0 unresolved); 17-item checklist in DEMO.md section 11; Verification 1-7 pass (prep 7/7 and 4/4, cleanup, number trace); `pytest.ini` added (`testpaths = tests`) after the `backup_pre_c` copy broke collection; snapshot `scripts/dev/finish/post_demo_snapshot.json`; rollback copy `scripts/dev/finish/backup_pre_c/` (38 files); demo marked done in PLAN_DEMO.md | 551 | P3, after the user says go |
| P3 | **done** | 2026-09-14 17:04 | `finish-p3-ui-frame.js` run `wf_6c9fa37a-f1e` (2 agents: restyle and visual review; no fix needed) | Frame restyled: masthead with the serif name and a monogram, gpu-note annotation bar, sidebar readout (label over value), tab strip with ink labels over an accent rule, shared classes scoped under `#twin-tabs`. Files: `twin/ui/frame.py` (layout only), `static/twin.css`, new `static/tabs/frame.css`, `tests/test_theme.py` (+7 tests), `docs/design/tokens.default.md`. Frame contract (37 variables, 20 classes, 15 rules), 7 demo_impact entries and the reviewer's 7 should_fix are in `scripts/dev/finish/p3_results.json`. Reviewer `go` (0 must_fix; web-design-guidelines fetched). Gate: pytest 558; contrast all ok; 0 internal selectors; `ui_check.ps1` PASS in `scripts/dev/shots/gate_p3` (view_api names, parameters and returns equal; only auto `value_NN` labels shifted by 2; Ask scrollWidth 400 in both themes; `/api/ps` untouched). Snapshot `scripts/dev/finish/p3_snapshot.json` | 558 | **HOLD** (user offline): P4 starts only when the user says go |
| P4 | **done** | 2026-09-14 18:36 | `finish-p4-ui-tabs.js` run `wf_1c55c342-750` (10 agents: 5 restyles and 5 reviews, no fix needed; 83 min) | All 5 lanes `done`, and every review r1 was `go` with 0 must_fix (should_fix: ask 7, decide 6, act_see 5, evals_status 9, onboarding_items 5). Files: the 8 `twin/ui` tab modules, 8 `static/tabs/*.css` partials and 5 new `tests/test_ui_*.py`; nothing outside lane ownership changed. The 32 demo_impact and 46 frame_requests entries are in `scripts/dev/finish/c_results.json` (P5 Fix and P6 use them). Gate: pytest 598; contrast all ok; 0 internal selectors; partials scoped (test_theme); `ui_check.ps1` PASS in `scripts/dev/shots/gate_p4` (view_api names, parameters and returns equal, only auto `value_NN` labels shifted; Ask scrollWidth 400 light and dark; `/api/ps` untouched; app stopped). Snapshot `scripts/dev/finish/p4_snapshot.json` | 598 | **paused by the user** after P4; P5 (GPU phase) next, when the user says go |
| P5 | **done** | 2026-09-14 about 21:05 | `finish-p5-integrate.js` run `wf_bae626c6-50a` (6 agents: assemble, live GPU, 3 critics, fix; 60 min) | Stage 6: 14 EVIDENCE2 rows; final shots in `scripts/dev/shots/stage6_final`; README, CLAUDE.md, CONTRACTS and ARCHITECTURE UI lines updated. Stage 7 (live, 8 rows): cold prep 7/7 and `-WarmOnly` 4/4; rehearsal run 12, 14/14 ok in 93.7 s, with an Act draft; See; three-condition Ask; pre-warm on tab select (hermes3); status strip vs `/api/ps` and `lms ps` (real-time capture; the prescribed virtual-time screenshots showed the boot state, a tooling limit); items run through the UI, both files restored, scores SHA unchanged; GPU freed; snapshot `scripts/dev/finish/p5_live_snapshot.json`. Critics (feature, UI, correctness) all `go` with 0 must_fix. The fix applied 7 (act.css, onboarding.css, EVIDENCE2) and deferred 13 frozen or post-demo items (`scripts/dev/finish/p5_results.json`). Gate: pytest 598, GPU idle, items equal their backup, data 20 files, `ui_check.ps1` PASS in `scripts/dev/shots/gate_p5`. PLAN_UNIFIED marked done | 598 | P6 in docs mode (only two CSS files changed after the live snapshot) |
| P6 | **done** | 2026-09-14 21:45 | `finish-p6-demo-regression.js` run `wf_3e990d6f-e14` (docs mode; 3 agents: regress, fix, S1; 35 min) | Docs mode: only `static/tabs/act.css` and `onboarding.css` changed after `p5_live_snapshot.json`, and CSS cannot change what the `gradio_client` rehearsal sees, so run 12 (14/14 ok, 14/14 expect_ok, 93.7 s on the restyled app) is the rehearsal. Regress: 8 restyled shots in `scripts/dev/demo/shots_restyled`, 15 UI differences mapped to DEMO.md lines, 0 expect failures, 0 wait changes; a real mouse-click probe found that Gradio's Walkthrough disables steps 2-4. Fix r1 applied 15 (DEMO.md sections 2, 5, 8 and 11 and beats B1.1, B4.4, B5.2, B7.1, B8.1 and B8.2; beats.json fallbacks; rehearsal.md section 18 "After restyle"; log `scripts/dev/finish/p6_fix_r1.md`); dry-runs OK. S1 `go`, 0 must_fix, 0 broken beats, 7 should_fix (`scripts/dev/finish/p6_results.json`). Gate: pytest 598, GPU idle, scores SHA and data list unchanged, 0 latency markers. Code frozen for P7-P8: snapshot `scripts/dev/finish/p6_snapshot.json` | 598 | P7 |
| P7 | **done** | 2026-09-14 about 23:15 | `finish-p7-mac-guide.js` run `wf_427e8bb9-87b` (9 agents: 5 readers, writer, 2 verifiers, fix; 75 min) | `docs/REPLICATE_ON_MAC.md` (1342 lines; 13 sections and 2 appendices): what the project is, where it stands, the zips, Claude Code on the Mac (install, settings merge, skills, memory), repo map, architecture, build pipeline, models and connections, Python setup, Windows-only pieces, working without models, remaining work, rules. Every Mac command is labeled untested on macOS. Verify r0 found 3 must_fix (the LM Studio embedder import, the venv and project instructions for a Mac Claude session, `claude` on PATH in zsh) and 22 should_fix; the fix applied 22 and left 0 must_fix unresolved (`scripts/dev/finish/p7_results.json`). The code freeze held (`p6_snapshot.json` code_match). The harness flagged settings.json-shaped text in three agents' outputs, because the guide covers settings.json; nothing was acted on | 598 | P8 |
| P8 | **done** | 2026-09-14 | main loop | `./start.sh` added (a macOS/Linux launcher, at the user's request; reviewed by an agent, 1 must_fix fixed; not run, because this laptop has no bash); README.md and `docs/REPLICATE_ON_MAC.md` point to it; `build_zips.py` stores `.sh` files as executable and skips `.venv`. Zips built and checked by `python scripts/dev/finish/build_zips.py --pytest-count 598` (report `scripts/dev/finish/zips_report.json`): `C:\Users\Adity\Personal_digital_twin_no_models_v2.zip`, `C:\Users\Adity\Personal_digital_twin_claude_memory_v2.zip`, `C:\Users\Adity\Personal_digital_twin_claude_env_v2.zip`. CLAUDE.md, memory and the plan status lines were updated before the build | 598 | finished |

**P1 outcome (hand-off session, 2026-09-14 about 14:05).** The full results are in `scripts/dev/demo/resume/p1_handoff_results.json`.

- **Demo lane: open, nearly done.**
  - **App fixes (Fix round 2, approved):**
    - `twin/pipelines/act.py`: once `search_profile` has run, `draft_message` tells the model to write.
    - `twin/pipelines/ask.py`: a reply cut off by the token limit is trimmed to its last full sentence.
    - 8 new tests: 2 in `tests/test_act.py`, 6 in `tests/test_ask.py`.
    - pytest: 551 passed, 0 failed.
  - **P-02:** out of the live flow.
  - **Live re-rehearsal:** run 8 was a full flow; runs 9-11 re-tested Act.
    - Act drafted a message in 4 of 4 attempts, where it had drafted in 0 of 6 before the fix. So `b5_live` is true.
    - B4.1 now ends at a full sentence.
  - **Cleanup:** confirmed (app stopped, `/api/ps` empty, GPU 0 MiB). `scripts/dev/demo/post_fix_snapshot.json` is written. The next free run number is 12.
  - **Final review:** the failure lens returned `go`. The presenter lens has 2 must_fix, both DEMO.md wording and neither needing the GPU. The §9 Known issues row and the Appendix B5.2 intro say all 6 pre-fix Act attempts hit the step limit. In fact 5 did; run 3's B5.1 ended after 2 steps with a prose answer.
  - **Caveats on the drafts:**
    - Run 8's draft doesn't match decision D-02.
    - Run 10's draft is 5 sentences, where 1-4 were asked for.
    - No draft addresses the mentor by role.
- **Docs lane: open.**
  - The final re-check found 5 must_fix and 12 should_fix in ARCHITECTURE.md, and 5 must_fix and 9 should_fix in CLIENT_TALKING_POINTS.md.
  - Its revise ran during plan mode and applied nothing. Its edit list, already checked against the sources, is in `scripts/dev/demo/resume/docs_revise_r2_planned_edits.md`.
  - The demo fixes also left 20 `notes_for_session_c` (7 from round 1, 13 from round 2) that affect these docs.
- **Next:** rerun P1 with `finish-p1-demo-ab.js` and these `args`:
  - `lanes`: `["docs", "demo"]`
  - `pytestCount`: 551
  - `nextRun`: 12
  - `launchState`: name `p1_handoff_results.json` and the planned-edits file, and say the app fixes and runs 8-11 are done. The demo lane should then only need the two DEMO.md wording fixes and a re-review, with no GPU run.

## State at hand-off (2026-09-14, about 13:00)

- **P1 is running in the hand-off session** (workflow `demo-resume-ab`).
  - **Docs lane:** the re-check found 8 and 2 must_fix, and revise round 2 ran.
  - **Demo lane:** the review found 4 and 6 must_fix, and Demo fix round 1 was working.
    - Fix round 1 may change `twin/pipelines/act.py`, `twin/pipelines/ask.py` and `tests/`, then re-rehearse on the GPU.
  - The hand-off session records the outcome in the Progress log before the new session starts.
- **Before P1's fixes:**
  - Code unchanged since `scripts/dev/demo/pre_snapshot.json`.
  - pytest 543 passed (`TWIN_NO_WARM=1`, `PYTHONUTF8=1`).
  - `data/items/scores.json` SHA-256 `24D60CA6E76C16B3E04C5148028D9ABEA78D602D13FB7408F11C2565E6885DEF`.
  - The `data/` file list equals `scripts/dev/demo/data_files_before.txt`.
- **Demo deliverables:**
  - `docs/DEMO.md` and `docs/demo/beats.json`.
  - `scripts/demo_prep.ps1`.
  - `scripts/demo_rehearse.py` (`--run`, `--only`, `--include-optional`, `--dry-run`, `--check-profile`, `--smoke`).
  - `docs/ARCHITECTURE.md` and `docs/CLIENT_TALKING_POINTS.md`.
- **Evidence:**
  - `scripts/dev/demo/`: rehearsal runs 1-7, `rehearsal.md`, `model_smoke.md` (8/8 PASS), `shots/`, `cleanup.txt`.
  - `scripts/dev/demo/resume/`: the claims-check round 0 results and the fix logs.
- **Rehearsal findings and the default for each:**
  1. **Act never drafted.** It produced no draft in 0 of 6 attempts (`twin/pipelines/act.py:209-222`). Fix it with a regression test and live re-tests. B5 stays live only if at least 2 of 3 attempts draft.
  2. **P-02 slipped.** It held in 1 of 2 runs. Take it out of the live flow and show the Eval probes table instead.
  3. **Ask replies get cut off** at `VOICE_TOKENS = 300` (`twin/pipelines/ask.py:56`). A small tested fix if a reviewer approves it, otherwise a demo workaround.
- **Still open for sign-off:**
  - 30 `[latency: from rehearsal]` markers (ARCHITECTURE.md 16, CLIENT_TALKING_POINTS.md 14).
  - The DEMO.md §11 checklist.
- **Traps:**
  - `scripts/dev/demo/app.pid` may hold a stale PID (10788 at hand-off), and Windows reuses PIDs.
  - Items "Run twin" and "Score" rewrite `data/items/twin_answers.json` and `scores.json`.
  - Headless screenshots of model tabs show the pre-warm still pending.
- **Zips from 2026-09-14 (stale once this plan runs):**
  - `C:\Users\Adity\Personal_digital_twin_no_models_2026-09-14.zip`
  - `C:\Users\Adity\Personal_digital_twin_claude_memory_2026-09-14.zip`
  - `C:\Users\Adity\Personal_digital_twin_claude_env_2026-09-14.zip`
  - P8 builds `_v2` versions.
- **Still blocked on the user:**
  - the real profile and interview transcript
  - day-0 and day-14 item answers
  - `ANTHROPIC_API_KEY` (optional)
  - Claude Design exports (optional)
  - the decision on enforcing politics deflection in code

## Phases

Each workflow stays under 15 agents; the whole plan runs about 35-60. All scripts live in `scripts/dev/workflows/`.

| Phase | Work | Agents | GPU | Gate |
|---|---|---|---|---|
| P0 | Preflight (main loop) | 0 | read-only | every P0 check passes, or the drift is explained |
| P1 | Demo review and fix, docs re-check | 4-13 | Fix agent only | both lanes done; pytest green; post-fix snapshot; cleanup confirmed |
| P2 | Demo sign-off (PLAN_DEMO Session C) and Verification | 2-4 | none in the workflow (Verification 2 boots prep) | S1 `go`; Verification 1-7 pass; no latency markers |
| P3 | UI frame restyle (workflow C, part 1) | 2-3 | none | reviewer `go`; pytest; `view_api` equal; frame contract |
| P4 | Tab restyle lanes (workflow C, part 2) | 10-15 | none | every lane `go`; pytest; no internal selectors |
| P5 | Integrate, stage 7 live, critics (workflow D) | 6-7 | Live agent only | critics `go`; stage 6-7 evidence; GPU freed; scores SHA unchanged |
| P6 | Demo regression on the restyled UI, re-sign-off | 2-4 | Regress agent (gpu mode only) | S1 `go` on the restyled UI |
| P7 | Mac replication guide | 8-14 | none | both verifiers `go` |
| P8 | Zips and wrap-up (main loop) | 0 | none | zip checks pass; docs and memory final |

## P0: preflight (main loop, every session start)

1. **Find the next phase.** Read this file and `scripts/dev/finish/state.json`. The next phase is the first one not marked done.
2. **Confirm the laptop is idle:**
   - `curl.exe -s http://127.0.0.1:11434/api/ps` returns `{"models":[]}`.
   - `nvidia-smi` shows `memory.used` of 200 MiB or less.
   - LM Studio answers `curl.exe -s http://127.0.0.1:1234/api/v0/models`. If it doesn't, note it; `scripts/demo_prep.ps1` starts it inside a GPU stage.
   - No python process is listening on ports 7861-7880.
3. **Clean up an interrupted GPU stage** (a leftover listener or a loaded model):
   1. Confirm the PID in `scripts/dev/demo/app.pid` belongs to a python process that owns the listener on the port in `scripts/dev/demo/app.port`, and stop only that PID.
   2. Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\free_gpu.ps1`.
   3. Re-run the step 2 checks.
4. **Check tests and data:**
   - `$env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider` matches `pytest_count` in state.json.
   - The scores SHA and the `data/` file list are unchanged.
   - Code write times match the latest snapshot named in state.json.
5. **Record the next free rehearsal run number:** the highest `scripts/dev/demo/rehearsal_run<N>.log`, plus 1.
6. **Build the phase's `args` and launch its workflow by `scriptPath`.** The args are:
   - `runDate`.
   - `launchState`: what steps 2-5 found, plus the evidence already on disk for this phase.
   - `pytestCount` and `nextRun`.
   - Any phase-specific inputs.

If P0 finds drift nobody can explain, the session stops.

## P1: demo review and fix, docs re-check

- **Script.** The hand-off session ran `demo-resume-ab`. Its "Demo fix r1" and "Docs revise r2" stages ran while the main session was in plan mode, so they stayed read-only and changed nothing; count them as not done. If the Progress log shows P1 open or blocked, run `scripts/dev/workflows/finish-p1-demo-ab.js` with `args` `{runDate, launchState, pytestCount, nextRun, lanes}`. `lanes` is `["docs"]`, `["demo"]` or both, and should list only the lanes that are not done. `launchState` must list fixes and evidence already on disk (`scripts/dev/demo/resume/fix_r*.md`, and rehearsal runs after run 7), so agents verify that work instead of redoing it.
- **Docs lane:** A2 re-checks ARCHITECTURE.md and CLIENT_TALKING_POINTS.md, then revise, then re-check. No GPU.
- **Demo lane:** presenter and failure reviews, then Fix (the only GPU user), then a re-review. At most two fix rounds. Fix writes `scripts/dev/demo/post_fix_snapshot.json`.
- **Gate:**
  - Both lanes `done`.
  - pytest green with any new tests.
  - The post-fix snapshot exists.
  - Cleanup confirmed: `/api/ps` empty, GPU at 200 MiB or less, app stopped.
  - If a lane ends `open`, run the fallback script once more. If it is still open, stop.

## P2: demo sign-off (PLAN_DEMO Session C) and Verification

- **Script to write:** `scripts/dev/workflows/finish-p2-demo-signoff.js`, with phases Reconcile, Sign-off and Final fix (2-4 agents).
- **Reconcile** (effort low). It owns ARCHITECTURE.md, CLIENT_TALKING_POINTS.md and DEMO.md §6. It must:
  - Replace every `[latency: from rehearsal]` marker with measured values from `scripts/dev/demo/rehearsal.md`, including its "Runs after fixes" section, and name the run and the range.
  - Align beat ids across the three docs and `beats.json`: P-02 is optional and out of the cut; B5 is live or trace-only according to P1's `b5_live`.
  - Match P1's outcome in the Act wording, the reply-cut wording and the today/roadmap labels.
  - Apply P1's `notes_for_session_c`.
  - Keep every number traceable to `docs/EVIDENCE2.md`, the source JSON, or rehearsal.md.
- **Sign-off S1** (Opus, adversarial):
  - Gives go or no-go across the five deliverables plus `beats.json` and the two scripts.
  - Returns `{go, must_fix, should_fix, checklist[]}`, where `checklist` is the pre-show checklist.
- **Final fix** (effort low) runs only on no-go, followed by S1 once more. Log that the cap was reached.
- **Main loop afterwards:**
  1. Append the checklist to DEMO.md §11.
  2. Run `docs/PLAN_DEMO.md` Verification 1-7.
     - Verification 1 compares against `post_fix_snapshot.json`.
     - Verification 2 runs `scripts/demo_prep.ps1` cold, then `-WarmOnly`. Afterwards stop the verified app PID and free the GPU.
  3. Write `scripts/dev/finish/post_demo_snapshot.json`.
  4. Copy `twin/ui/`, `static/`, `app.py` and `tests/` to `scripts/dev/finish/backup_pre_c/`. This is the only rollback, since the project is not a git repo.
  5. Mark the demo done in PLAN_DEMO's Checkpoint section.
- **Gate:** S1 `go`; Verification passes; no latency markers left.

## P3: UI frame restyle (workflow C, part 1)

- **Script to write:** `scripts/dev/workflows/finish-p3-ui-frame.js` (2-3 agents, no GPU). Use `UI_REVIEWER` in `C:\Users\Adity\.claude\projects\C--Users-Adity-Personal-digital-twin\3e254742-bcd3-4168-95a8-8984b67430b8\workflows\scripts\twin-workflow-a-wf_51f1ad60-e4c.js` as the template.
- **Before screenshots:** all 8 tabs, light theme, 1440 px, `TWIN_NO_WARM=1` on port 7871, saved to `scripts\dev\shots\before_c`. Use `scripts\screenshot_tabs.ps1 -Port 7871 -OutDir scripts\dev\shots\before_c`; the script also takes `-Theme`, `-Width`, `-Tabs` and `-VirtualTimeMs`.
- **Restyle agent:**
  - Invokes the `frontend-design` skill, then runs the `redesign-existing-projects` audit.
  - Owns:
    - `twin/ui/frame.py`, for layout and classes only. Tab-select warm, the heartbeat and `TAB_JS` behaviour stay frozen.
    - `twin/ui/theme.py`, `static/twin.css`, `static/tabs/frame.css` and `tests/test_theme.py`.
    - `docs/design/tokens.default.md`, but only together with `twin.css`, because `test_twin_css_defaults_match_the_default_sheet` pins the two files to each other.
  - Returns `frame_contract` (the CSS variables and classes the tab lanes may use) and `demo_impact[]`.
- **Visual reviewer:**
  - Port 7871; light and dark at 1440 px, plus Ask at 400 px.
  - Checks the PLAN_UNIFIED §3.8 rubric and `web-design-guidelines`. If that skill's online fetch fails, record it.
  - `view_api` equals `scripts/dev/view_api_baseline.json` plus the six new names (follow `scripts/dev/evidence/stage2_view_api_check.py`).
  - `twin.ui.theme.check_contrast()` returns `[]`.
  - `/api/ps` and `/api/v0/models` return the same body before and after.
- **Fixer** (effort low) runs only on must_fix.
- **Gate:** reviewer `go`; full pytest green; `view_api` equal.

## P4: tab restyle lanes (workflow C, part 2)

- **Script to write:** `scripts/dev/workflows/finish-p4-ui-tabs.js` (10-15 agents, no GPU). Use the lane skeleton in `C:\Users\Adity\.claude\projects\C--Users-Adity-Personal-digital-twin\3e254742-bcd3-4168-95a8-8984b67430b8\workflows\scripts\twin-workflow-b-wf_ff2bc65b-c89.js` as the template.
- **Structure:** `pipeline()` over five lanes. Each lane runs restyle (skills as in P3, using `frame_contract`), then an adversarial visual reviewer, then a fixer only on must_fix.
- **Lanes and ports:**

  | Lane | Port | Extra check |
  |---|---|---|
  | ask | 7872 | Ask `scrollWidth` 400 or less at 400 px |
  | decide | 7873 | |
  | act + see | 7874 | |
  | evals + status | 7875 | |
  | onboarding + items | 7876 | |

- **Ownership:**
  - Each lane owns only `twin/ui/<tab>.py`, `static/tabs/<tab>.css` and an optional new `tests/test_ui_<lane>.py`.
  - No lane edits `frame.py`, `theme.py`, `twin.css`, `app.py` or `tests/test_ui_build.py`.
- **Outputs:** screenshots go to `scripts/dev/shots/lane_<key>/`. Each lane returns its check outputs (for stage 6 evidence), `demo_impact[]` and `frame_requests[]`.
- **Main loop afterwards:**
  - Run the full pytest suite and the `view_api` check.
  - Grep `static/` for `svelte-`, `.block` and `.gradio-container`; there must be no hits.
  - Save `scripts/dev/finish/c_results.json`.
- **Gate:** every lane `go`; pytest green; no internal selectors.

## P5: integrate, stage 7 live sanity, critics (workflow D)

- **Script to write:** `scripts/dev/workflows/finish-p5-integrate.js` (6-7 agents).
- **Assemble** (effort low, port 7877, `TWIN_NO_WARM=1`):
  - The full screenshot set: light and dark for all 8 tabs at 1440 px, plus Ask at 400 px in both themes.
  - Stage 6 rows in `docs/EVIDENCE2.md`, built from `c_results.json`, with pasted output.
  - Updates to README.md, CLAUDE.md, the UI section of `docs/CONTRACTS.md`, and the UI lines of ARCHITECTURE.md.
- **Live** (the only GPU agent; port 7861; no `TWIN_NO_WARM`):
  1. **Setup:**
     - Check the GPU is idle.
     - Back up `data/items/twin_answers.json` and `scores.json` to `scripts/dev/finish/items_backup/`.
     - Run `scripts/demo_prep.ps1`, then `-WarmOnly`.
  2. **Rehearsal run:** a full `python scripts/demo_rehearse.py --run <next>`. Count the Act drafts.
  3. **Live checks through the restyled UI:**
     - One See.
     - The three-condition Ask.
     - Pre-warm on tab select.
     - The status strip compared with the `/api/ps` and `lms ps` bodies; save those bodies to `scripts/dev/evidence/stage7_*`.
  4. **Items check:** run items once through the UI. Then restore both items files and confirm the scores SHA.
  5. **Cleanup and records:**
     - Stop the verified app PID and run `scripts/free_gpu.ps1`.
     - Write the stage 7 rows in EVIDENCE2 and `scripts/dev/finish/p5_live_snapshot.json`.
- **Critics** (3 in parallel, Opus, read-only):
  - **Feature completeness:** stages 0-7 each have rows with pasted output.
  - **UI completeness:** the rubric, `web-design-guidelines`, and the screenshots actually opened.
  - **Correctness:** tests, API, GPU gating, data safety and the DEMO CONTRACT.
- **Fix** (effort low): must_fix items plus `frame_requests`. Then pytest, and a boot check on port 7878 with `TWIN_NO_WARM=1`.
- **Main loop afterwards:** mark `docs/PLAN_UNIFIED.md` done, with the list of items still blocked on the user.
- **Gate:** critics `go` after Fix; the evidence rows are present; GPU freed; scores SHA unchanged.

## P6: demo regression on the restyled UI and re-sign-off

- **Script to write:** `scripts/dev/workflows/finish-p6-demo-regression.js` (2-4 agents).
- **Mode:** gpu mode when anything in `twin/`, `app.py` or `static/` is newer than `p5_live_snapshot.json`. Otherwise docs mode, where P5 Live's run files count as the rehearsal.
- **Regress:**
  - **In gpu mode** it is the only GPU agent and runs:
    - a cold `demo_prep.ps1`, every line PASS
    - `-WarmOnly`
    - a full rehearsal run
    - the 5-minute-cut model steps from cold, as run 7 did
    - cleanup
  - **In both modes** it takes all 8 tabs with `scripts\screenshot_tabs.ps1 -OutDir scripts\dev\demo\shots_restyled` and opens every PNG:
    - gpu mode: port 7861 with `-VirtualTimeMs 40000`
    - docs mode: port 7871 with `TWIN_NO_WARM=1`
- **Fix** (effort low):
  - Owns DEMO.md, `beats.json`, an "After restyle" section in rehearsal.md, and the UI claims in ARCHITECTURE.md and CLIENT_TALKING_POINTS.md.
  - Updates in DEMO.md:
    - §2 (sidebar and status strip) and the §3 labels.
    - The "Exact input" and "Point at" cells of changed beats.
    - §5, §8 and §11.
    - Waits, but only where the new run differs.
  - Changes an `expect` string in `beats.json` only if it legitimately changed, then runs `--dry-run`.
- **Sign-off:** S1 on the presenter lens, then Fix, then S1 once more.
  - If a UI change broke a beat and one fix round can't repair it, revert that lane's CSS from `backup_pre_c`.
  - If the revert doesn't fix it either, stop and report.
- **Gate:** S1 `go`; data safety and cleanup confirmed.

## P7: Mac replication guide

- **Script:** `scripts/dev/workflows/finish-p7-mac-guide.js`, with `args` `{runDate, finalState, zips}`.
  - `finalState` summarizes the Progress log:
    - the final pytest count and app fixes
    - the restyle and the stage 6-7 evidence
    - the re-signed demo
    - items still blocked on the user
    - the politics gap
  - `zips` lists the P8 zip names.
- **Structure:** five readers, a writer, then an accuracy verifier and a Mac-lens verifier (V2 boots with `TWIN_NO_WARM=1` on port 7879), then a fixer. At most two rounds.
- **Code freeze:** code is frozen during P7-P8. Bugs found then are logged as open items, not fixed.
- **Gate:** both verifiers `go`.

## P8: zips and wrap-up (main loop)

- **Build.** Write `scripts/dev/finish/build_zips.py` (Python `zipfile`, run as a file) and build these zips. Keep the older zips.
  - **Project:** `C:\Users\Adity\Personal_digital_twin_no_models_v2.zip`
    - Top folder `Personal_digital_twin/`.
    - No files under `models/`, but keep the empty `models/ollama/` and `models/lmstudio/` folders.
    - No `__pycache__` or `.pytest_cache`.
    - Includes `docs/REPLICATE_ON_MAC.md`, `.claude/skills` and `scripts/dev/workflows`.
  - **Memory:** `C:\Users\Adity\Personal_digital_twin_claude_memory_v2.zip`, the memory folder after the final memory update.
  - **Env:** `C:\Users\Adity\Personal_digital_twin_claude_env_v2.zip`
    - `claude_env/user-config/settings.json`, `claude_env/skills` and `claude_env/skills-not-used`.
    - Never `.credentials.json` or `.claude.json`.
- **Checks:**
  - `testzip()` returns None.
  - File counts match the files on disk.
  - No secrets: no `.credentials.json`, no `.claude.json`, and no real `sk-ant-` keys.
  - Extract the project zip to `%TEMP%`, run pytest there, and get the same count. Then delete the copy.
- **Final:**
  - Update CLAUDE.md open items, memory, and the status lines in `docs/PLAN_DEMO.md` and `docs/PLAN_UNIFIED.md` to the finished state.
  - GPU idle; leave LM Studio running.
  - Send the user the three zips and the guide.

## Rules for every workflow

- **Advisors and critics:** Opus 5, leaving `model` unset. Each prompt starts with the adversarial note: it runs on the same model that wrote the material, so it must assume mistakes and open the source for every claim. A null result blocks the workflow and must never read as "no findings".
- **Agents:** every `agent()` call sets `opts.phase`. Revise, fix, reconcile and assemble agents use `effort: 'low'`.
- **GPU:**
  - One GPU agent per workflow, alone in its stage, and it checks the GPU is idle first.
  - UI agents use `TWIN_NO_WARM=1` on ports 7871-7879 and never touch 7861-7870.
- **Processes:** stop a PID only after confirming it is a python process that owns the listener on the recorded port.
- **Helper scripts:** they go under `scripts/dev/finish/`. Never run `python -` from PowerShell: its stdin is the null device, and Python loops in a REPL.
- **Launch facts:** passed in through `args`, never hard-coded. Workflows run by `scriptPath`; resume in the same session with `resumeFromRunId`.
- **Standing project rules** (CLAUDE.md, `docs/PLAN_DEMO.md` fact 8):
  - Local servers only, on 127.0.0.1.
  - Use `curl.exe`, not `curl`.
  - Never touch the `.ollama` junction or the `OLLAMA_*` variables.
  - Never print `ANTHROPIC_API_KEY`.
  - No politics questions in any live check.
  - Forbidden live controls stay forbidden.

## DEMO CONTRACT (P3-P5)

- **API:** the api_names and their parameter lists stay equal to `scripts/dev/view_api_baseline.json`, plus the six new names.
- **Endpoint output:** these strings stay exactly as they are:
  - the strings the `beats.json` `expect` checks look for
  - the strings DEMO.md "Point at" quotes: the verdict and cited decisions, footers, trace lines, gpu notes, "Last action"

  Restyle through classes, CSS and wrappers only, never by changing what an endpoint returns.
- **Labels and links:**
  - Every bold label quoted in DEMO.md §3-§4 stays.
  - The deep links `?tab=`, `__theme` and `nomotion=1` keep working.
  - The elem_ids `twin-header`, `twin-tabs` and `tab-<id>` stay.
- **Exceptions:** any unavoidable change goes into `demo_impact[]` with the DEMO.md line it affects.

## Pause and resume

- **Checkpoints:** every phase ends with a Progress log entry and a `state.json` update, both written before the next phase starts.
- **To pause:** say "pause at the next checkpoint". The session lets the current workflow finish, then stops.
  - Stopping a workflow mid-run is allowed only outside a GPU stage.
  - If a GPU stage was interrupted, the next P0 cleans up (step 3).
- **Resume in the same session:** `Workflow({scriptPath, resumeFromRunId, args})`, using the args stored in state.json.
- **Resume in a new session:** the setup and kickoff from "Start here". P0 re-checks the state. A half-done phase reruns its workflow, with `launchState` listing the evidence already on disk.
- **Automatic stops:**
  - pytest fails.
  - P0 finds drift nobody can explain.
  - The GPU is busy before a GPU stage.
  - A workflow ends in any status other than `done`.
  - Two agents in a row return null.
  - An input only the user can supply is missing.

## Verification summary

| Phase | What must be true |
|---|---|
| P1-P2 | pytest green with the new tests; cold prep PASS after the last code change; post-fix run ok and within budgets; B5 draft count decides live or trace-only; no latency markers; S1 `go` |
| P3-P4 | pytest green; `view_api` equals the baseline plus six; `check_contrast()` returns `[]`; no internal selectors in `static/`; Ask `scrollWidth` 400 or less; `/api/ps` untouched |
| P5 | stage 6-7 evidence rows with pasted output; items files restored with the scores SHA unchanged; GPU freed; critics `go` |
| P6 | DEMO.md matches the restyled screenshots and the `twin/ui` strings; `--dry-run` passes; S1 `go` |
| P7-P8 | V1 and V2 `go`; zips pass `testzip`; the extracted zip gives the same pytest count; no secrets in any zip; GPU idle at the end |

## References

- **Demo:**
  - `docs/PLAN_DEMO.md`: facts 1-8, the beat sheet, deliverables, Verification, Checkpoint.
  - `docs/DEMO.md`, `docs/demo/beats.json`, `scripts/dev/demo/rehearsal.md`.
- **Features and UI:** `docs/PLAN_UNIFIED.md` (§3.8 UI rubric, §5 stages 6-7, §6 workflows C and D, §10 execution update), `docs/EVIDENCE2.md`, `docs/CONTRACTS.md`.
- **Tooling:** `scripts/demo_prep.ps1`, `scripts/demo_rehearse.py`, `scripts/dev/live_drive.py`, `scripts/screenshot_tabs.ps1`, `scripts/free_gpu.ps1`, `scripts/check_servers.ps1`.
- **Memory notes:** `C:\Users\Adity\.claude\projects\C--Users-Adity-Personal-digital-twin\memory\` (build state, workflow lessons, design-skills policy, run-plans-in-new-sessions).
