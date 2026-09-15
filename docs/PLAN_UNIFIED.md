# Digital Twin: unified plan for everything remaining (features + UI), with the file audit

Written 2026-09-14 for execution in one fresh Claude Code session using the phase-1 ultracode workflow pattern. Supersedes `docs/PLAN2.md` and `docs/PLAN3_UI.md` (kept on disk as design references; where they disagree with this file, this file wins). First action after approval: copy this file to `docs/PLAN_UNIFIED.md` so the next session reads it from the repo.

## Context

Phase 1 (2026-09-13) delivered a working twin: `app.py` with six Gradio 6 tabs, the `twin/` package, 215 mocked tests, and live evidence for every stage in `docs/EVIDENCE.md`, all on the synthetic "Ari" profile. Two follow-up plans were written separately (features in PLAN2, UI restyle in PLAN3); the user then ran the Claude Research prompt, whose deliverables now sit in `docs/research/D1..D4` plus `data/twin_profile.example.v2.md` ("Mara Ellison"), and installed three design skills. The user asked for one plan that builds all of it on the actual research deliverables, plus an audit that phase 1 is intact.

User decisions (2026-09-13/14) baked in: Opus in claude.ai conducts the interview; politics stays out (no political items, the Beliefs section may omit it, the twin deflects politics in chat); personality instrument is the public-domain IPIP-50; the whole build runs in one session; the impeccable skill is skipped (no Node.js).

## 1. Audit (read-only, 2026-09-14) and the fixes this plan schedules

Phase 1 is intact: `pytest -p no:cacheprovider` = 215 passed; `import app` works; every artifact `docs/EVIDENCE.md` cites exists (three (42,768) indexes, chunks.json, digest.md, eval_results.json, telemetry.jsonl, six screenshots, poll and eval logs); no `eval`/`exec` outside the AST calculator; no hard-coded model name reaches a server; `ANTHROPIC_API_KEY` only existence-checked; GPU 0 MiB, `/api/ps` empty, port 7861 free. Node.js and git absent, winget present; gradio 6.27, gradio_client 2.7, anthropic 1.5, pypdf 6.18 installed. The current parser already reads the v2 example (62 chunks) but indexes its `# Changelog` section. No test imports `app.py`, so splitting it cannot break the suite.

Fixes folded into stage 0:
- `docs/CONTRACTS.md` drift: see.py `describe_image`/`react` return dicts; act.py `run_agent(max_steps)` returns `steps`; evals.py listed twice; about 40 load-bearing helpers undocumented (ask.route/rewrite/retrieve/check_reply, decide.render_result_markdown, evals.validate_keys/summary_rows/live_one signature, clients.LMSClient.models_v1, gpu.TAB_MODEL, index.main). Rewrite the pipelines section from the code and add the new module APIs (items, transcript, redact, audit, reflect, ui).
- `docs/PLAN.md` layout omits `twin/pipelines/voice.py`, `scripts/screenshot_tabs.ps1`, `scripts/dev/`, pillow/pytest: add a "post-build additions" note, do not rewrite history.
- `requirements.txt`: `gradio>=6,<7`, add `gradio_client`, `pypdf`.
- ask.py and see.py duplicate the Stheno-to-llama3.2:3b fallback: route both through `voice.reply_in_voice` with byte-identical request bodies (tests pin them).
- Missing tests for index, clients, prompts, voice: add mocked request-body tests.
- Stray files: delete root-level duplicates `D1_ground_rules.md`..`D4_item_bank_and_scoring.md` (byte-identical to `docs/research/`), the empty `files\` dir; move `data/app_fix_boot.log` and `scripts/dev/*.pid` to `scripts/dev/old/`; regenerate `.pytest_cache`.
- Doc conflicts settled by this plan: example personas (Ari for phase-1 tests, Mara for v2); reflection lenses per D2; IPIP-50 not BFI-44; game parameters per D4; eight tabs; screenshot script flags; README folder layout; CLAUDE.md phase notes replaced by a pointer to `docs/PLAN_UNIFIED.md`.

## 2. Inputs and what the research deliverables fix

| Input | Path | Status | Effect |
|---|---|---|---|
| D1 ground rules | `docs/research/D1_ground_rules.md` | present | prefix <= ~1500 tokens (Identity 120, Style rules 200, 3 samples 180, Boundaries 150, digest 400); chunks 120-250 tokens (floor 80, ceiling 300); file 4000-7000 words; self-contained first-person chunks; freeze Eval + item bank + digest prompt per version tag; embedder in frontmatter; Changelog excluded; one variable per evaluated version |
| D2 schema v2 | `docs/research/D2_schema_v2.md` | present | frontmatter `schema_version`, `embedder`, `eval_frozen`; new sections and their order; reflections inside the profile, human-checked |
| D3 protocol | `docs/research/D3_interview_protocol.md` | present | seven blocks, ~90-120 min; block 7 administers the 20 Eval questions verbatim plus self-ratings (see the leak rule in 3.2) |
| D4 item bank | `docs/research/D4_item_bank_and_scoring.md` | present | IPIP-50; GSS core items by variable name (non-political only); games with fixed parameters; JSON answer shapes; scoring and retest normalization; conditions A/B/C; decision rule |
| D5 example | `data/twin_profile.example.v2.md` | present | parser test data and default example for the v2 build |
| Real profile, transcript | `data/twin_profile.md`, `data/interview_transcript.md` | missing | example transcript for Mara generated in stage 0 |
| Item answers | `data/items/self_answers*.json` | missing | example wave-1 and wave-2 answers for Mara generated in stage 0 |
| Design export | `docs/design/tokens.md`, `docs/design/screens/` | missing | tokens agent runs the `frontend-design` two-pass plan instead |
| Anthropic key | env | missing | Claude judge skipped, shown in the UI |

The build never blocks on missing inputs; section 7 says when the user supplies them and what to re-run.

## 3. Design

### 3.1 Profile v2 parser (`twin/profile.py`, `twin/config.py`)

Keep every phase-1 label and the module-level cache names tests monkeypatch (`ask._profile_cache`, `decide._PROFILE_CACHE`, `see._PROFILE_CACHE`, `act._PROFILE`). Add frontmatter fields `schema_version`, `embedder`, `eval_frozen`, optional `consent`; exclude `Eval` and `Changelog` from chunks; the new sections parse with the existing rules (`# Beliefs and attitudes` with topic `##`; `# Routines` `## Weekday`/`## Weekend`; `# Life events` free `## <title>`; `# Self-ratings` one chunk; `# Interview highlights` `## <topic>`; `# Expert reflections` `## Psychologist`/`## Behavioral economist`/`## Political scientist`/`## Demographer`). `Profile` gains `schema_version`, `consent`, `reflections: dict[lens, text]`, `self_ratings`, `beliefs`, `routines`, `life_events`, `highlights`. `python -m twin.profile --lint [path]` reports chunks outside 80-300 tokens, prefix size versus the 1500 budget, word count versus 4000-7000, missing sections, and warns on any `## Society and politics` chunk. Examples: `data/twin_profile.example.md` (Ari) stays for phase-1 tests; `config.EXAMPLE_PROFILE_V2_PATH` = the Mara file; `resolve_profile_path()` prefers real > v2 example > v1 example; phase-1 tests pin the Ari file explicitly.

### 3.2 Transcript and redaction (`twin/transcript.py`, `twin/redact.py`)

File: frontmatter (`name`, `date`, `blocks`, `exclude_blocks: [7]` default); `# Block N: title`; `## T-NNN` turns with a `Q:` line and a multi-line `A:` block. Parser yields `Turn(id, block, question, answer)`; chunk ids `Interview/T-012`, text `Q: ...\nA: ...`, split at sentence boundaries into `T-012a/b` above 300 tokens. **Leak rule:** block 7 holds the verbatim gold Eval answers, so excluded blocks are never chunked, ingest prints the excluded count, and the index build computes `evals.containment` of every Eval answer against every transcript chunk and fails above 0.6. Redaction before indexing: regex (emails, phones, street addresses, card/ID-like numbers, URLs with usernames) then one `qwen3_8k` pass per chunk with schema `{"names": [...]}` for third-party names, replaced by role tags from the People section or `[a person]`; writes `data/interview_transcript.redacted.md` plus a count report; the index reads only the redacted file; `--no-redact` for the example. Stage 0 writes `data/interview_transcript.example.md` for Mara following D3's seven blocks (about 60 turns, block 7 included so the exclusion is exercised) with two planted targets (an email, a third-party name).

### 3.3 Index sources and reflections (`twin/index.py`, `twin/pipelines/reflect.py`)

`index.collect_chunks(profile, transcript_path=None, reflections_path=None) -> (chunks, shas)`: chunk dicts gain `source` in `{profile, transcript, reflection}`; profile chunks under `# Expert reflections` are tagged `reflection` (D2 wins); `data/reflections.md` (the reflect.py draft) is indexed only when that section is absent, ids `Reflections/<lens>`. `combined_sha = sha256("profile:<sha>|transcript:<sha or ''>|reflections:<sha or ''>")`. npz keeps `vectors, ids, embedder, sha` (profile sha) and adds `source`, `combined_sha`; `load_index` defaults missing keys so old files still load. `chunks.json` keeps `sha/path/chunks` and adds `shas`, `combined_sha`, per-chunk `source`; `chunk_lookup()` unchanged. `is_stale` unchanged; new `is_stale_sources(index_key)` for the header. `search(..., sources=None)` masks before top-k; `search_chunks` passes it through. `build_index(index_key, profile, tab, corpus=None)` (None = profile only, today's tests); `build_all(profile, with_digest, force=False, with_reflections=False)`; CLI `--reflect`. reflect.py: one `qwen3_long` call per lens (num_ctx 40960, keep_alive 0, think false, num_predict 400, one retry on empty) over the redacted transcript plus the profile minus Eval and Changelog, cached by combined sha, output `data/reflections.md` with `## <lens>` blocks and a sha comment; the Political scientist lens only when a `## Society and politics` chunk exists. Status shows a "review and paste into # Expert reflections" note. Decide and Items boost `Decisions`, `Expert reflections` and `Reflections`.

### 3.4 Conditions (`twin/prompts.py`, `ask.py`, `decide.py`, `evals.py`, `items.py`, UI)

`prompts.CONDITIONS = ("demographic", "persona", "interview")`, `DEFAULT_CONDITION = "interview"`. `build_voice_prefix(..., condition=DEFAULT_CONDITION)`: demographic returns Identity only; persona and interview unchanged. `build_voice_system(..., condition=DEFAULT_CONDITION)`: non-interview drops the CONTEXT block and uses `VOICE_SYSTEM_NO_CONTEXT(name)`; interview stays byte-identical to today. `ask._ask_events/ask_turn/ask_sync` gain `condition`; non-interview skips retrieval, demographic blanks the digest, trace line `condition: X (chunks: N, digest: yes|no)`, `done.data["condition"]`; CLI `--condition`. `decide._decide/decide_b1/decide_b2(..., condition)`, `retrieve_for_decision` appends every reflection chunk for interview, `build_context(chunks, digest, condition, profile)` gives identity-only or identity+digest for the ablations; `result["condition"]` stored so `say_it(result)` keeps its signature. `evals.run_voice_bakeoff(..., conditions=("interview",))`, `live_one(..., condition)`; cache key stays `cand` for interview and becomes `f"{cand}@{condition}"` otherwise, so the phase-1 `eval_results.json` replays unchanged and `validate_keys` splits on `@`. `items.run_items(conditions=..., progress=None)` stores `twin_answers.json[sha][condition][item_id]`. UI: the condition `gr.Dropdown` is appended as the last input of `/ask`, `/decide_b1`, `/decide_b2`, `/eval_live` so phase-1 positional gradio_client calls still work.

### 3.5 Item bank and scoring (`data/items/bank.json`, `twin/pipelines/items.py`)

Record: `{id, instrument: ipip50|gss|game|gold, domain?, reverse?, type: likert5|categorical|number|fraction|binary|open, text, options?, range?, source_url}`. Contents: the 50 IPIP Big-Five Factor Markers (public domain; the builder fetches ipip.ori.org and stores factor and key; the rules reviewer re-fetches and diffs all 50; BFI phrasing grepped for and rejected), the four games with D4 parameters (dictator give 0-10 of 10; trust send 0-10 tripled; trustee fraction 0-1; public goods 0-10, group of 4, multiplier 1.6; prisoner's dilemma cooperate/defect with a stated payoff matrix), the 20 Eval questions as open items, and GSS items from D4's list minus a political blacklist (`POLVIEWS`, `PARTYID`, `PRES*`, `VOTE*`, confidence-in-government items); GSS wording must be verified from the NORC GSS Data Explorer or the item is omitted and listed in `docs/items_licensing.md` as "not included: wording unverified". `docs/items_licensing.md` records every instrument's source and license.

Answers: `data/items/self_answers.json` = `{wave: 1, date, answers: {id: value}}`, `self_answers_retest.json` = wave 2; Mara example files for both waves (retest with realistic drift) in stage 0. Twin run with model-outer ordering to keep GPU loads to at most four: retrieval precomputed with `lms_nomic`, then `qwen3_8k` answers all closed items for all conditions through per-item JSON schemas (D4 shapes `{"item_id","answer"}`, `{"game","give"|"fraction"|"action"}`, temperature 0.2, one retry on invalid JSON), then `stheno_q4` answers open items, then `llama31` and `qwen25` judge them; results written after every call, resumable. Scoring per D4: categorical accuracy; continuous MAE, Pearson r per domain/game family, and `1 - MAE/range`; normalized = twin metric / retest metric at domain level (wave 2 is the ground truth, wave 1 vs wave 2 the denominator); bootstrap 95% CI over items (1000 resamples); "ceiling pending" without a retest; final decision line: does C beat A and B, and "fix retrieval (recall@5) before content if normalized categorical < 0.5". CLI `python -m twin.pipelines.items --run --condition all|demographic|persona|interview`, `--score`, `--show`. The answer distribution per condition is printed to catch enum collapse.

### 3.6 Safeguards (`twin/audit.py`, `twin/pipelines/probes.py`, `scripts/delete_twin.ps1`)

`audit.record(tab, condition, request_text, chunk_ids, model_keys, ok)` appends one JSON line to `data/audit.jsonl` (request stored as sha256, never text); pipelines call it; Status shows the last 50 and counts per day. `probes.py`: three boundary probes derived from the profile's Boundaries section (example set generated for Mara) run in the Eval tab and must score "deflected" (judge: no withheld fact revealed). `scripts/delete_twin.ps1 -Confirm` removes profile, transcripts, indexes, chunks, digest, reflections, item answers, eval results, audit and telemetry, after which the app opens on Onboarding. The redaction report is shown in Status after every ingest. Consent date from frontmatter is shown in the header.

### 3.7 Interview prompt (`docs/opus_interview_prompt.md`)

D3 verbatim (standing instructions, seven blocks with seed questions and follow-up rules, per-decision probe script, block 7 Eval administration and self-ratings, consent confirmation) minus block 5's politics seed question, plus the machine-readable output: at the end of every block Claude prints that block's turns in `## T-NNN` format inside a code block (block 7 tagged so `exclude_blocks` catches it); after block 7 it prints the complete profile v2 with all 3.1 labels, the Expert reflections section as drafts marked for review, and `# Changelog v2.0`, then a redaction checklist. `docs/opus_profile_prompt.md` stays with a header pointing here.

### 3.8 UI (`twin/ui/*`, `static/`, `app.py`, `scripts/screenshot_tabs.ps1`)

Eight tabs: Onboarding (first when no real profile), Ask, Decide, Act, See, Items, Eval, Status. `app.py` becomes the assembler (keeps `--port/--host`, `pick_port`, `TAB_JS`, `TAB_IDS`, `main`); `twin/ui/state.py` holds `PROFILE`, `PROFILE_ERROR`, `load_app_profile`, `no_warm()` under today's names, read through the module; each tab module exposes `build(ctx)` and wires its own events with the existing api_names plus `items_save`, `items_run`, `items_score`, `onboarding_check`, `audit_tail`, `redaction_report`. Before the split, `scripts/dev/view_api_baseline.json` is captured from the monolith; `tests/test_ui_build.py` asserts the api_name set, `concurrency_id="gpu"` on model endpoints and `api_name=False` on hooks. `twin/ui/frame.py`: persona header (name, avatar initial, source, freshness, consent, warnings), `gr.Sidebar` status strip (GPU MiB of 8192, LM Studio and Ollama loaded models with GPU percent and context, active tab, heartbeat idle/loading/ready/busy from a new `MANAGER.busy` set inside `session()`), tab strip; the 5 s timer stays GET-only. Switches: `TWIN_NO_WARM=1` (read at call time; gates tab-select warm, `start_heartbeat`, `/warm`, `/rebuild_*`) and `TWIN_THEME=light|dark`. Theme: `twin/ui/theme.py` `TwinTheme(gr.themes.Base)` from `docs/design/tokens.md` when present, else from the `frontend-design` two-pass plan written to `docs/design/tokens.default.md` (palette 4-6 named hexes grounded in "a private console for one person's twin", one or two Google Fonts with reasons, type scale, radius rule, tinted shadows, tabular numerals, monospace only in trace panels, none of the skill's anti-default clusters); `theme.py` globs `static/tabs/*.css` after `static/twin.css`; selectors only on our `elem_id`/`elem_classes`. Screenshot script: `-Port`, `-Theme`, `-Width` (1440 and 400), per-port Chrome `--user-data-dir`, output `scripts/dev/shots/<theme>_<width>_<tab>.png`. Per-tab restyle targets (from PLAN3 3.2 and the brief): verdict card, quote card, chat avatars and placeholder, step-trace cards, bar chart of overall per candidate, line chart of tokens per second, models table with state pills, Walkthrough for Onboarding, Items form grouped by instrument. Skills: restyle agents invoke `frontend-design` first and run the `redesign-existing-projects` audit; reviewers run `web-design-guidelines`; acceptance rubric: tokens only, one primary action per area, status strip visible, all states (empty, streaming, loading a model, inline error, ceiling pending), dark complete, 400 px Ask with `scrollWidth <= 400`, contrast >= 4.5:1 by a WCAG function over the token sheet, copy unchanged, api_names unchanged, no internal selectors. Impeccable skipped; evidence records it.

## 4. Repo changes

```
twin/profile.py (v2, --lint)  twin/transcript.py  twin/redact.py  twin/audit.py  twin/config.py (paths, EXAMPLE_PROFILE_V2_PATH)
twin/index.py (collect_chunks, source, combined_sha, --reflect)   twin/prompts.py (conditions)   twin/gpu.py (busy)
twin/pipelines/reflect.py  items.py  probes.py   ask.py decide.py evals.py (condition + audit)   voice.py (used by ask/see)
twin/ui/__init__.py theme.py frame.py state.py onboarding.py ask.py decide.py act.py see.py items.py evals.py status.py
static/twin.css  static/tabs/<tab>.css   app.py (assembler)   scripts/screenshot_tabs.ps1 (flags)   scripts/delete_twin.ps1
scripts/dev/view_api_baseline.json  scripts/dev/evidence/*.json  scripts/dev/shots/
data/items/bank.json  self_answers.example.json  self_answers_retest.example.json   data/interview_transcript.example.md
docs/PLAN_UNIFIED.md  docs/INPUTS.md  docs/opus_interview_prompt.md  docs/items_licensing.md  docs/design/tokens.default.md  docs/EVIDENCE2.md
docs/CONTRACTS.md (rewritten)  docs/PLAN.md (additions note)  README.md  CLAUDE.md  requirements.txt
tests/test_transcript.py test_redact.py test_reflect.py test_audit.py test_probes.py test_items.py test_conditions.py
tests/test_index.py test_clients.py test_prompts.py test_voice.py test_theme.py test_ui_build.py test_ui_items.py + updated phase-1 tests
```

## 5. Build stages and verification (PowerShell 5.1, `PYTHONUTF8=1`)

0. **Inputs, docs, cleanup**: `docs/INPUTS.md` records what was found; section-1 fixes applied; `docs/opus_interview_prompt.md`, `docs/items_licensing.md`, Mara example transcript and both example answer waves written; `requirements.txt` updated. Pass: files exist; `bank.json` loads with 50 IPIP items (10 per domain, reverse flags, source_url), 5 game items, 20 gold items, only verified non-political GSS items; reviewer confirms IPIP wording against ipip.ori.org.
1. **Foundation v2 + UI split**: `pytest` green (215 plus new); `python -m twin.profile --lint data/twin_profile.example.v2.md` shows no Changelog chunk and the prefix under budget; `python -m twin.redact data/interview_transcript.example.md` reports the planted email and name removed; `python -m twin.index --build all --digest --reflect` writes indexes whose `source` arrays cover profile and transcript (reflection only when the profile lacks the section), prints "excluded blocks: 1" and passes the containment check; `--search "what did you learn from quitting the agency"` returns an `Interview/T-NNN` id in the top 3; `/api/ps` empty afterwards. UI split: app boots on 7871 with `TWIN_NO_WARM=1`, `view_api()` equals the baseline, `/api/ps` empty after screenshotting all tabs; without the switch `/warm ask` loads Stheno.
2. **Conditions**: one Ask question under three conditions via gradio_client: demographic trace `chunks: 0, digest: no`; persona `chunks: 0, digest: yes`; interview five ids with at least one `Interview/` or reflection id; Decide under interview lists a reflection id.
3. **Items**: `items --run --condition all` on the example answers covers every item x condition with at most four model loads in telemetry; `--score` prints per-instrument tables with the normalized column (example retest present), bootstrap CIs and the decision line; Items tab saves a wave-1 file with a date; with the retest removed the column reads "ceiling pending".
4. **Safeguards**: three probes deflected under interview; Status shows the audit tail; `delete_twin.ps1 -Confirm` on `data_test/` removes every listed file and the app opens on Onboarding; redaction report visible after a rebuild.
5. **Eval**: voice bake-off for Stheno Q4 across three conditions (5 questions, two judges) plus the items run cached; Eval tab replays both with `/api/ps` empty; phase-1 rows still replay.
6. **UI theme and restyle**: token sheet passes contrast; light and dark shots of all eight tabs at 1440 plus Ask at 400 in `scripts/dev/shots/`; every tab passes the rubric; no `svelte-`/`.block` selectors in `static/`; `view_api()` equals the baseline plus the six new names.
7. **Final live sanity and evidence**: without `TWIN_NO_WARM`, one Ask, one B1, one Act, one See, one items run through the UI; status strip matches `ollama ps`/`lms ps` (bodies saved to `scripts/dev/evidence/`); pre-warm on tab select works; GPU freed (`scripts/free_gpu.ps1`, `/api/ps` empty, nvidia-smi <= 200 MiB); `docs/EVIDENCE2.md` has one row per check in stages 0-7 with pasted output; README, CLAUDE.md, CONTRACTS final; `docs/PLAN_UNIFIED.md` marked done with the blocked list.

## 6. Execution: four ultracode workflows, one session

Rules (as phase 1): agents inherit the session model; design, review and live agents keep session effort; scaffolding and fixes use `effort: 'low'`; one GPU agent per workflow, alone in its own stage; disjoint file ownership per parallel agent (not a git repo); UI agents boot on port 7871 + lane with `TWIN_NO_WARM=1`; `pipeline()` by default; read each result before launching the next; on failure fix and resume with `resumeFromRunId`; live agents paste actual command output into `docs/EVIDENCE2.md` after every check and save `/api/ps` and `lms ps` bodies under `scripts/dev/evidence/`; critics reject evidence rows without output. Run all four back to back; end only when every stage in section 5 has evidence or is blocked on the user.

### Workflow A: foundation v2, UI split, tokens, item bank (about 10 agents)

```
phase Build      parallel 4, disjoint files:
                 A1 core (low): profile v2 + lint, transcript.py (exclude_blocks), redact.py, audit.py, index sources/combined sha/
                    --reflect + containment check, prompts conditions, reflect.py, config paths, CONTRACTS additions, INPUTS.md,
                    opus_interview_prompt.md, example transcript (Mara), requirements, root cleanup
                 A2 ui split (low): capture view_api baseline, app.py assembler, twin/ui/* (behaviour-identical, 6 tabs) + placeholder
                    items.py/onboarding.py (READY=False), state.py, TWIN_NO_WARM/TWIN_THEME, MANAGER.busy, screenshot flags,
                    tests/test_ui_build.py
                 A3 tokens (session effort, frontend-design skill): docs/design/tokens.default.md (or parse tokens.md), theme.py,
                    static/twin.css, tests/test_theme.py with the contrast check
                 A4 item bank (session effort): bank.json (IPIP-50 fetched + verified, games, gold, non-political GSS), both example
                    answer waves, items_licensing.md
phase Verify     parallel 3, mocked: rules reviewer (registry rules, IPIP diff against a fresh fetch, political blacklist, redaction
                 never bypassed, Changelog/Eval/block-7 exclusion, qwen3_long keep_alive 0); tester (writes test_transcript/redact/
                 reflect/audit/index/prompts/voice/clients, updates test_profile); UI reviewer (boots 7871 with TWIN_NO_WARM=1, diffs
                 view_api against the baseline, no internal selectors)
phase Fix        1 agent, low, only if findings
phase Live       1 agent (GPU): stage 1 checks; evidence rows
```

### Workflow B: pipelines v2 with their functional UI (about 13 agents)

`pipeline()` over three lanes, each: implement -> adversarial reviewer ("the request that returns empty, loads the wrong model, leaks Eval/self-answers/Changelog/block 7 into a prompt, skips redaction, or breaks the phase-1 cache or api_names") -> fixer when issues exist.
- conditions lane: `twin/pipelines/ask.py decide.py evals.py` + tests (also inserts `audit.record` calls), then `twin/ui/ask.py decide.py evals.py` (condition dropdown last input) and `scripts/dev/live_drive.py --condition`.
- items lane: `twin/pipelines/items.py` + `tests/test_items.py`, then `twin/ui/items.py onboarding.py` (READY=True) + `tests/test_ui_items.py`.
- safeguards lane: `twin/pipelines/probes.py`, `twin/ui/status.py` (audit tail, redaction report, reflections note), `scripts/delete_twin.ps1`, `tests/test_probes.py test_audit.py`.
Then: Live (GPU): stages 2 to 5 via gradio_client on 7861, evidence rows; Fix (low).

### Workflow C: per-tab restyle (12 to 15 agents, no GPU)

`pipeline()` over six lanes: frame (+ `theme.py`, `static/twin.css`, `static/tabs/frame.css`), ask, decide, act+see, evals+status, onboarding+items. Each owns its `twin/ui/<tab>.py` and `static/tabs/<tab>.css` only: restyle with `frontend-design` and the redesign audit -> visual reviewer (port 7871 + lane, `TWIN_NO_WARM=1`, light/dark/400 px shots, rubric + `web-design-guidelines`) -> fixer when findings. Must prove: rubric per tab, `scrollWidth <= 400` on Ask, api_names unchanged, `/api/ps` untouched.

### Workflow D: integrate, live sanity, critics (about 7 agents)

```
phase Assemble   1 agent: full shot set, README/CLAUDE/CONTRACTS final pass, EVIDENCE2 completeness
phase Live       1 agent (GPU): stage 7 plus a re-run of the three-condition Ask through the restyled UI; free GPU
phase Critic     parallel 3: feature completeness, UI completeness, correctness (with web-design-guidelines)
phase Fix        1 agent, low; tests + boot check
```

## 7. The user's tasks and when to do them

1. Nothing is required to start. Optional now: `ANTHROPIC_API_KEY`.
2. While workflows B to D run (they never touch the interview files): run the interview with Opus using `docs/opus_interview_prompt.md` (available after workflow A; about 90-120 minutes); save `data/interview_transcript.md` and `data/twin_profile.md`; review the reflections drafts and paste them into `# Expert reflections`. Rebuild only between workflows, never during a GPU stage: `python -m twin.index --build all --digest --reflect` then `python -m twin.profile --lint`.
3. After the session: day-0 Items form (about 45 minutes); run Claude Design with `docs/claude_design_prompt.md` and the eight-tab screenshots from `scripts/dev/shots/`; drop `docs/design/tokens.md` and screens; then re-run workflow A's tokens agent and workflow C with `resumeFromRunId` (or a short follow-up session) to apply the real design. Day 14: retest form, then "Run twin" for all conditions and read the decision line.
4. Skipped by decision: Node.js and impeccable.

## 8. Kickoff line for the next session

> **Superseded (2026-09-14):** workflows C and D now run as phases P3-P5 of `docs/PLAN_FINISH.md`; use the kickoff there. See section 10.

```
ultracode: read docs\PLAN_UNIFIED.md in full, then execute sections 5 and 6 exactly; don't ask for confirmation between workflows and don't stop until every stage has passing evidence or is blocked on something only I can supply, and list any blocked items at the end.
```

## 9. Risks and mitigations

- Gold Eval answers leak through the transcript (D3 block 7): `exclude_blocks` default, containment check fails the build above 0.6.
- IPIP or GSS wording invented: fetched from the sources, re-fetched and diffed by the reviewer; unverified GSS items omitted and listed; BFI phrasing rejected.
- The app.py split changes behaviour: baseline `view_api` JSON captured first; split with zero styling changes; module cache names frozen in CONTRACTS.
- Two agents editing the same tab: workflow B lanes own disjoint ui modules; workflow C lanes own one module and one CSS partial; per-port Chrome profile dirs.
- GPU contention in the items run: model-outer ordering, retrieval precomputed with `lms_nomic`, telemetry must show at most four loads; runs resume after every call.
- Phase-1 eval cache invalidated by conditions: `cand@condition` keys for non-default conditions.
- Politics leaking in through D2/D4 defaults: lint warning, blacklist in the bank builder, a politics boundary probe, the Political scientist lens only when the section exists.
- `TWIN_NO_WARM` half-applied: read at call time, gates every warm path, tested with a `MANAGER.warm` spy, live evidence compares `/api/ps` before and after screenshots.
- Design export absent during the session: default token plan from `frontend-design`; real design applied later by re-running the tokens agent and workflow C.
- Wall-clock: four workflows, roughly 45 agents; GPU stages (index/reflections, items run, bake-off) dominate; plan for an evening.

## 10. Execution update (2026-09-14)

Workflows A and B are done (`docs/EVIDENCE2.md` stages 0-5). Workflows C and D now run inside `docs/PLAN_FINISH.md`, after the demo sign-off. The specs in sections 3.8, 5 and 6 still apply, with these changes:

- **Workflow C is split in two:**
  - **P3, C1 (frame):** `frame.py` layout, `theme.py`, `static/twin.css`, `static/tabs/frame.css`.
  - **P4, C2 (tab lanes):** ask, decide, act+see, evals+status, onboarding+items. These build on the frame contract.
- **Workflow D runs as P5.**
  - The stage 7 items check backs up `data/items/twin_answers.json` and `scores.json` first, then restores them and confirms the scores SHA. Running items rewrites both files.
  - P6 then re-checks and re-signs the demo on the restyled UI.
- **The UI work keeps a DEMO CONTRACT** (defined in PLAN_FINISH):
  - API names and parameters stay unchanged.
  - The endpoint output strings that the demo quotes stay unchanged.
  - The labels, deep links and elem_ids the demo relies on stay unchanged.
- **Reviewers and critics** run on Opus 5 with an adversarial note. Fable 5.1 is over its monthly spend limit.
- **The kickoff in section 8 is superseded:** use the kickoff in `docs/PLAN_FINISH.md`.

## 11. Done (2026-09-14, `docs/PLAN_FINISH.md` P3-P5)

All four workflows have run, and every stage in section 5 has evidence rows in `docs/EVIDENCE2.md` (stages 0-5, 14 stage 6 rows and 8 stage 7 rows).

- **Workflow C: done.**
  - P3 restyled the frame (run `wf_6c9fa37a-f1e`) and P4 restyled all eight tabs in five lanes (run `wf_1c55c342-750`). Every reviewer was `go` in round 1.
  - Results: `scripts/dev/finish/p3_results.json` and `c_results.json`.
  - Gate: pytest 598; contrast all ok; no internal selectors; view_api names, parameters and returns unchanged; Ask scrollWidth 400 at a true 400 px in both themes; `/api/ps` untouched.
- **Workflow D: done** (P5, run `wf_bae626c6-50a`; `scripts/dev/finish/p5_results.json`).
  - Assemble added the stage 6 rows and the final shots in `scripts/dev/shots/stage6_final`.
  - Live checks:
    - cold prep 7/7 and `-WarmOnly` 4/4;
    - rehearsal run 12 (14/14 ok, 93.7 s; Act drafted);
    - See, the three-condition Ask, and pre-warm on tab select (hermes3 loaded);
    - the status strip matches `/api/ps` and `lms ps` in a real-time capture;
    - items run through the UI, both files restored, scores SHA unchanged;
    - GPU freed.
  - Two prescribed virtual-time screenshot checks failed for a tooling reason (headless virtual time captures the boot state). The real-time captures that replaced them passed.
  - The three critics were `go` with 0 must_fix. The fix applied 7 items, all CSS and evidence, and deferred 13 that the DEMO CONTRACT froze.
- **Still blocked on the user:**
  - the real profile and interview transcript (`docs/opus_interview_prompt.md`);
  - day-0 and day-14 item answers;
  - `ANTHROPIC_API_KEY` for the Claude ceiling judge;
  - Claude Design exports (`docs/design/tokens.md`), optional;
  - the decision on enforcing politics deflection in code.
- **UI follow-ups deferred until after the demo regression (P6):** see `p5_results.json` fix.skipped and each critic's should_fix. The main ones:
  - the status strip shows its boot value until the first 5 s tick;
  - `color-scheme` on the root in dark mode;
  - pinning `gradio==6.27.0`;
  - the strings frozen by the DEMO CONTRACT (h1, skip link, confirmations on Rebuild and Re-run).
