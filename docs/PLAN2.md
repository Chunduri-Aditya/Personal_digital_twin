# Digital Twin phase 2: interview-based profile, conditions, item-bank evaluation, safeguards

Written 2026-09-13 for execution in a fresh Claude Code session. Everything a new session needs is in this file plus the files it names. Phase 1 (the working app) is documented in `docs/PLAN.md`, `docs/CONTRACTS.md` and `docs/EVIDENCE.md`; read those three first, they are authoritative for the existing code.

## 0. Kickoff (paste this single line into the new session)

```
ultracode: read docs\PLAN2.md in full, then execute sections 5 and 6 exactly; don't ask for confirmation between phases and don't stop until every stage has passing evidence or is blocked on something only I can supply, and list any blocked items at the end.
```

Standing instructions from the user, in their words: "don't stop until everything is built". Decisions already made by the user on 2026-09-13: Claude Opus in claude.ai conducts the interview (no local interviewer tab in this phase); public-issue items that touch politics are skipped from the item bank and the twin keeps deflecting them in chat.

## 1. Context and what phase 1 left in place

Method source: Park et al., "Generative Agent Simulations of 1,000 People" (arXiv 2411.10109) and the Stanford HAI policy brief (May 2025). Their agents are an LLM plus a two-hour semi-structured interview transcript; they beat demographic-only and persona-only agents by 14 to 15 points on survey replication, score 85% of the person's own two-week test-retest consistency, and add expert reflections derived from the transcript. This phase adapts that to an 8 GB GPU with 8192-token models: the transcript becomes a second retrieval source instead of being injected whole, reflections are generated once by the long-context model, and evaluation is normalized by the user's own retest.

Phase 1 facts that still hold (verified in `docs/EVIDENCE.md`): both servers on 127.0.0.1, model registry in `twin/config.py` (keys stheno_q4, stheno_q8, qwen3_8k, qwen3_long, hermes3, qwen25, llama31, qwen35_vision, llama32_3b, llama32_1b, nomic_ollama, embeddinggemma, nomic_lms, claude), GPU rules in `twin/gpu.py` (one lock, `MANAGER.session(key)` around every call), profile parser in `twin/profile.py` (chunk per `##`), three indexes in `twin/index.py`, pipelines in `twin/pipelines/` (ask, decide, act, see, evals, digest, voice), `app.py` with six tabs and `?tab=` deep links, 215 mocked tests, `scripts/screenshot_tabs.ps1`. gradio 6.27 (Chatbot messages format, theme/css/js on `launch()`), anthropic 1.5, pypdf installed. Python `C:\Users\Adity\anaconda3\python.exe`, run with `PYTHONUTF8=1`. Not a git repo: no worktrees, parallel agents get disjoint files. Never print or store `ANTHROPIC_API_KEY`.

Two hard rules from phase 1 stay: only one agent per workflow touches the model servers and runs alone in its own stage; everyone else tests with mocked clients. Every Ollama request carries `options.num_ctx` and `keep_alive` from the registry; qwen3 keys carry `think: false`; the Q8 Stheno always gets a system message; hermes3 gets its instruction in the first user turn because its template drops the system prompt when tools are sent.

## 2. Inputs from the user (use defaults when missing; never block the build on them)

| Input | Path | Produced by | If missing at build time |
|---|---|---|---|
| Research deliverables D1 to D4 | `docs/research/D1_ground_rules.md`, `D2_schema_v2.md`, `D3_interview_protocol.md`, `D4_item_bank_and_scoring.md` | `docs/research_profile_prompt.md` run in claude.ai with Research | Use the defaults in section 3; write `docs/PLAN2_inputs.md` saying so |
| Research deliverable D5 (synthetic v2 example) | `data/twin_profile.example.v2.md` | same | The scaffold agent extends the phase-1 "Ari" example with the new sections |
| Interview transcript | `data/interview_transcript.md` | Opus interview via `docs/opus_interview_prompt.md` (written in stage 0) | Scaffold writes `data/interview_transcript.example.md` for Ari (10 blocks, 60 turns) |
| Real profile v2 | `data/twin_profile.md` | Opus, derived from the transcript | Example profile as in phase 1 |
| Day-0 self answers | `data/items/self_answers.json` | The user in the new Items tab | Scaffold writes `data/items/self_answers.example.json` for Ari |
| Day-14 retest | `data/items/self_answers_retest.json` | The user, 14 days later | Scoring shows raw numbers and "ceiling pending" |
| Anthropic key | env `ANTHROPIC_API_KEY` | The user | Claude judge skipped, shown in the UI |

When a research file exists, its content overrides the matching default below; when it conflicts with a parser label listed in section 3, the label wins and the conflict is noted in `docs/PLAN2_inputs.md`.

## 3. Design

### 3.1 Profile v2 (parser stays backward compatible)

Everything in the phase-1 layout stays parseable (frontmatter; `# Identity`; `# Voice` with `## Style rules` and `## Sample 1..15`; `# Values`; `# Preferences` with the six subsections; `# People`; `# Decisions` with `## D-NN: title` and `Situation:/Options:/Choice:/Why:/Outcome:`; `# Goals`; `# Boundaries`; `# Eval` with `## Q-NN` and `Question:/Answer:`, excluded from retrieval). Default new sections, each subsection one chunk of 80 to 300 tokens:

- `# Life events` with `## E-01: title` blocks: `When:` (year or age range), `What:`, `Why it mattered:` (6 to 12).
- `# Beliefs` with one `##` per topic the user chose to cover (work, money, relationships, technology, learning, community); no political items unless the user added them; each 3 to 6 bullets in the user's words.
- `# Routines` with `## Weekday`, `## Weekend`, `## Under stress` (3 to 6 bullets each).
- `# Interview highlights` with `## H-01..H-15`: one verbatim quote from the transcript per block plus a one-line context, chosen because it reveals a value, a habit or a way of reasoning.

Self-ratings and item answers never go in the profile; they live in `data/items/` and are the ground truth for scoring.

### 3.2 Transcript: format, parser, redaction

`data/interview_transcript.md`: frontmatter (`name`, `date`, `blocks`); `# Block N: title` sections; `## T-NNN` turns, each with a `Q:` line (interviewer) and an `A:` block (the user, verbatim, may span lines). `twin/transcript.py` parses it into `Turn(id, block, question, answer)` and chunks `Interview/T-012` (text = "Q: ...\nA: ..."; turns over 300 tokens split at sentence boundaries into `T-012a`, `T-012b`). `twin/redact.py` runs on ingest: regex for emails, phone numbers, street addresses, card or ID-like numbers, URLs with usernames; then one qwen3-8b-8k pass per chunk with a JSON schema `{names: [..]}` listing third-party personal names, replaced with role tags the user's People section defines (unknown names become `[a person]`). Writes `data/interview_transcript.redacted.md` and a count report; the index reads only the redacted file. `--no-redact` exists for the example transcript.

### 3.3 Index sources and reflections

`twin/index.py` gains a `source` array in each npz (`profile` | `transcript` | `reflection`) and `chunks.json` records both shas. `build_all(profile, with_digest, with_reflections)` indexes profile chunks, transcript chunks and reflection chunks together; `search_chunks(..., sources=None)` can filter. Staleness checks both shas. `twin/pipelines/reflect.py`: four lenses (psychologist, behavioral economist, sociologist, close friend who knows their habits), each one call to `qwen3_long` (num_ctx 40960, keep_alive 0, think false, LM Studio unloaded first by the huge-model rule) over the redacted transcript plus the profile minus Eval, `num_predict` 400, output plain text, stored in `data/reflections.md` as `## <lens>` blocks with a combined-sha comment line, cached like the digest, one retry on empty. Reflection chunks get ids `Reflections/<lens>`.

### 3.4 Conditions (the paper's ablation)

`condition` in `{"demographic", "persona", "interview"}` threaded through `prompts.build_voice_system(profile, digest, chunks, condition=...)`, `ask.ask_turn`, `decide.decide_b1/b2`, and evals:

- demographic: system = VOICE_SYSTEM + Identity only; no samples, no digest, no chunks.
- persona: VOICE_SYSTEM + Identity + Style rules + 3 samples + Boundaries + digest; no chunks.
- interview: everything above plus the top-5 chunks from all sources plus the four reflections (Decide and items: top-8 chunks with reflections always included, boost `Decisions` and `Reflections`).

Ask tab gets a Condition dropdown (default interview); Decide gets the same; Eval runs all three.

### 3.5 Item bank and scoring

`data/items/bank.json`: `[{id, instrument, type: "likert5"|"likert7"|"categorical"|"number", text, options?, range?, reverse?, source}]`. Defaults when D4 is missing: the BFI-44 items (John and Srivastava, free for research use; the agent copies item text from the published instrument, never invents items), the four economic games as numbers (dictator: keep 0 to 100 of 100; trust game player 1 send 0 to 100 and player 2 return 0 to 300; public goods contribute 0 to 20; prisoner's dilemma cooperate or defect), and the 20 Eval questions as open items. GSS items are added only from D4 and only non-political ones. A `docs/items_licensing.md` records each instrument's source and license line.

Items tab in `app.py`: "Self" form (one item per row, saves `self_answers.json` with a date; a second save after 14 days goes to `self_answers_retest.json`), "Run twin" (for each condition, qwen3-8b-8k answers likert and categorical items via a JSON schema built from the item, Stheno Q4 answers open items; written to `data/items/twin_answers.json` after every call, resumable), and a scoring table: per instrument and condition, categorical accuracy, Likert MAE and Pearson r, game MAE, open-item judge score (reusing evals.judge_reply), then normalized = twin metric divided by the retest metric when the retest exists, else "ceiling pending". `twin/pipelines/items.py` holds this; the CLI `python -m twin.pipelines.items --run --condition all`.

### 3.6 Safeguards

- Audit: `twin/audit.py` appends one JSON line per twin request to `data/audit.jsonl` (time, tab, condition, request hash, chunk ids used, model keys); Status tab shows the last 50 and a count per day.
- Consent and boundaries: the profile frontmatter gains `consent: <date>`; the header shows it; the Boundaries section is always in the prefix for persona and interview conditions and the deflection is tested by three boundary probes in the Eval tab (must not reveal the withheld fact).
- Deletion: `scripts/delete_twin.ps1` removes profile, transcript (raw and redacted), indexes, chunks, digest, reflections, item answers, eval results, audit and telemetry after a `-Confirm` switch, then the app header shows the "no profile" state.
- Redaction report shown in Status after every ingest.

### 3.7 Interview prompt (replaces the interview part of `docs/opus_profile_prompt.md`)

`docs/opus_interview_prompt.md`, written in stage 0 from D3 or the default protocol: ten blocks of about twelve minutes (life story; education and work; relationships by role; routines and habits; values; money and big decisions; technology and media; free time; views on public issues limited to the user's non-political choices; goals). Rules for Claude: one question at a time, follow up on specifics ("tell me about a time when", "why", "what did you weigh"), keep the user's wording, skip answered topics, accept refusals, and at the end of every block output that block's turns in the `## T-NNN` format inside a code block so the user can paste them into `data/interview_transcript.md`. After the last block, output the profile v2 (the phase-1 labels plus section 3.1) in one code block, then a redaction checklist. Voice samples are still pasted messages, requested in block 1.

## 4. Repo additions

```
twin/transcript.py            parse + chunk the transcript;  twin/redact.py  regex + qwen3-8b-8k name pass
twin/audit.py                 audit log;  twin/pipelines/reflect.py  four reflections;  twin/pipelines/items.py  item bank run + scoring
twin/index.py                 sources, combined sha, reflections;  twin/prompts.py  condition-aware prefix;  twin/profile.py  v2 sections
twin/pipelines/ask.py decide.py evals.py   condition parameter;  app.py  Items tab, Condition dropdowns, audit and redaction in Status
data/items/bank.json  self_answers[.example].json  twin_answers.json;  data/interview_transcript[.example].md;  data/reflections.md;  data/audit.jsonl
docs/opus_interview_prompt.md  docs/items_licensing.md  docs/PLAN2_inputs.md  docs/EVIDENCE2.md;  scripts/delete_twin.ps1
tests/test_transcript.py test_redact.py test_reflect.py test_items.py test_audit.py + updated test_profile/test_index/test_ask/test_decide/test_evals
```

## 5. Build stages and verification (PowerShell 5.1)

0. **Inputs and docs**: read `docs/research/*` and `data/twin_profile.example.v2.md` if present; write `docs/PLAN2_inputs.md` (what was found, what defaults apply); write `docs/opus_interview_prompt.md`, `docs/items_licensing.md`, `data/interview_transcript.example.md` (Ari, 10 blocks, about 60 turns, with two planted redaction targets: an email and a third-party name), `data/items/bank.json` and `data/items/self_answers.example.json` for Ari. Pass = files exist, `bank.json` loads, no invented survey items (every BFI item text matches the published instrument, checked by the reviewer).
1. **Parsers, redaction, index**: `python -m pytest tests -q` green; `python -m twin.redact data/interview_transcript.example.md` reports the planted email and name removed; `python -m twin.index --build all --digest --reflect` builds three indexes with `source` arrays covering profile, transcript and reflection chunks; `--search "what did you learn from your first job"` prints at least one `Interview/T-NNN` id; `data/reflections.md` has four `##` blocks; `/api/ps` is `{"models":[]}` afterwards.
2. **Conditions**: via gradio_client, the same Ask question under the three conditions returns three replies; the trace for demographic shows "chunks: 0, digest: no"; persona shows "chunks: 0, digest: yes"; interview shows five chunk ids including at least one `Interview/` or `Reflections/` id; Decide under interview lists `Reflections/` in its context ids.
3. **Items**: `python -m twin.pipelines.items --run --condition all` on the example answers writes `twin_answers.json` covering every item and condition; the Items tab renders the scoring table with raw metrics and "ceiling pending"; saving the Self form writes `self_answers.json` with a date; a synthetic retest file makes the normalized column appear.
4. **Safeguards**: three boundary probes in the Eval tab score "deflected" for the interview condition; Status shows the audit tail after the calls above; `scripts/delete_twin.ps1 -Confirm` on a copy of the data folder removes every listed file (run against `data_test/` not `data/`); the redaction report appears in Status after a rebuild.
5. **Eval**: voice bake-off restricted to Stheno Q4 across the three conditions (5 questions, two judges) plus the item-bank run, cached in `data/eval_results.json` and `data/items/twin_answers.json`; the Eval tab replays both with `/api/ps` empty; `docs/EVIDENCE2.md` gets one row per check above with actual output.

Also: rerun `scripts/screenshot_tabs.ps1` (seven tabs now) and keep `docs/EVIDENCE.md` untouched.

## 6. Execution: ultracode workflows

Same rules as phase 1: every agent inherits the session model; design, review and live agents keep the session effort; scaffolding and fixes use `effort: 'low'`; one GPU agent per workflow, alone in its own stage; disjoint file lists; `pipeline()` by default; read each workflow's result before launching the next; fix and resume with `resumeFromRunId` instead of restarting.

### Workflow 4: foundation v2 (6 agents)

```
phase Scaffold   1 agent, effort low: stage 0 files, twin/transcript.py, twin/redact.py (regex part + client call),
                 twin/audit.py, profile.py v2 sections, index.py sources + combined sha, prompts.py condition prefix,
                 pipelines/reflect.py, docs/CONTRACTS.md additions
phase Verify     parallel, 3 lenses: rules reviewer (registry rules, no invented items, redaction never bypassed,
                 reflections use qwen3_long with keep_alive 0), parser tester (tests for transcript, redact regex,
                 profile v2, index sources; no network), live smoke (the GPU agent: stage 1 checks)
phase Fix        1 agent, effort low, only if findings; re-smoke if the smoke failed (max 2 rounds)
```

### Workflow 5: pipelines v2 (9 to 12 agents)

`pipeline()` over `[conditions (ask+decide+evals changes), items, safeguards (audit view, boundary probes, delete script)]`: implement + mocked tests, adversarial reviewer ("find the request that returns empty, loads the wrong model, leaks Eval or self-answers into a prompt, or skips redaction"), fixer when issues exist.

### Workflow 6: integrate and verify live (5 agents)

```
phase Integrate  1 agent: app.py Items tab, Condition dropdowns, Status audit + redaction, seven-tab screenshots support
phase Live       1 agent (GPU): stages 2 to 5, evidence per check into docs/EVIDENCE2.md, small fixes in place
phase Critic     parallel 2: completeness (every section-3 feature present; every stage has evidence) and correctness
phase Fix        1 agent, effort low, reruns tests and the boot check
```

## 7. The user's tasks and timeline (the only blockers)

1. Run `docs/research_profile_prompt.md` in claude.ai with Research; save D1 to D4 under `docs/research/` and D5 as `data/twin_profile.example.v2.md`. Optional: the build works on defaults without them.
2. Run the interview with Opus using `docs/opus_interview_prompt.md` (about two hours); save the transcript as `data/interview_transcript.md` and the profile as `data/twin_profile.md`; then `python -m twin.index --build all --digest --reflect`.
3. Day 0: fill the Self form in the Items tab (about forty minutes). Day 14: fill it again (retest), which unlocks the normalized scores.
4. Optional: set `ANTHROPIC_API_KEY` for the Claude judge.

Expectation to state in the final report: the paper's 85% used a frontier model with the whole transcript; an 8B twin with retrieval will score lower, and the condition table is the honest measure of how much the interview adds.
