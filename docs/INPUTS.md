# Inputs: what exists, what stage 0 generated, what the user still supplies

Written 2026-09-14 by workflow A (stage 0 of `docs/PLAN_UNIFIED.md`); it fills the plan's section-2 table with what is actually on disk. Sizes are bytes. Re-check with `Get-ChildItem data, data\items, docs\design, docs\research`.

## 1. Section-2 table, filled

| Input | Path | Status (2026-09-14) | Effect / notes |
|---|---|---|---|
| D1 ground rules | `docs/research/D1_ground_rules.md` | present, 6,198 | prefix <= ~1500 tokens, chunks 80-300 tokens, file 4000-7000 words, Eval and Changelog excluded from retrieval; `python -m twin.profile --lint` checks all of it |
| D2 schema v2 | `docs/research/D2_schema_v2.md` | present, 7,561 | frontmatter `schema_version`, `embedder`, `eval_frozen`; the new sections parse in `twin/profile.py` (`beliefs`, `routines`, `life_events`, `self_ratings`, `highlights`, `reflections`) |
| D3 protocol | `docs/research/D3_interview_protocol.md` | present, 5,043 | seven blocks; block 7 = the 20 gold Eval answers, so `exclude_blocks: [7]` in the transcript and a containment check at index build |
| D4 item bank | `docs/research/D4_item_bank_and_scoring.md` | present, 5,672 | IPIP-50, non-political GSS, four games, scoring and retest normalisation, conditions A/B/C |
| D5 example profile (Mara) | `data/twin_profile.example.v2.md` | present, 15,350 | schema v2; parses to 61 chunks (0 Eval, 0 Changelog), 15 decisions, 20 eval items, 4 reflection lenses, 5 belief topics; `resolve_profile_path()` falls back to it when no real profile exists |
| Phase-1 example profile (Ari) | `data/twin_profile.example.md` | present, 18,887 | schema v1; 42 chunks; the phase-1 tests pin this path explicitly |
| Real profile | `data/twin_profile.md` | **missing** | produced by the Opus interview (`docs/opus_interview_prompt.md`); when present it wins over both examples |
| Real transcript | `data/interview_transcript.md` | **missing** | same interview; `python -m twin.redact data\interview_transcript.md` writes `data/interview_transcript.redacted.md`, the only transcript the index reads |
| Example transcript (Mara) | `data/interview_transcript.example.md` | present, 26,426 (stage 0) | 60 turns T-001..T-060 in 7 blocks (6/5/5/6/5/11/22); block 7 excluded (22 turns), 38 indexed turns -> 40 chunks (T-001 and T-004 split into a/b); ~4,980 words; two planted redaction targets (one email in T-021, one full name in T-031); max Eval containment against blocks 1-6 = 0.50 |
| Item bank | `data/items/bank.json` | present, 73,851 (stage 0, item-bank agent) | see `docs/items_licensing.md` (11,398) for sources and the political blacklist |
| Item answers, real | `data/items/self_answers.json`, `data/items/self_answers_retest.json` | **missing** | wave 1 on day 0, wave 2 on day 14, through the Items tab or by copying the example shape |
| Item answers, example (Mara) | `data/items/self_answers.example.json` (4,483), `data/items/self_answers_retest.example.json` (4,636) | present (stage 0, item-bank agent) | wave 1 and wave 2 with realistic drift; used until the real files exist |
| Design export | `docs/design/tokens.md`, `docs/design/screens/` | **missing** | the tokens agent writes `docs/design/tokens.default.md` from the `frontend-design` two-pass plan instead; `twin/ui/theme.py` prefers `tokens.md` when it appears |
| Theme CSS | `static/twin.css` | present, 12,508 (tokens agent, this workflow) | `static/tabs/*.css` partials arrive with workflow C |
| Anthropic key | env `ANTHROPIC_API_KEY` | **not set** | Claude judge and the ceiling reference are skipped and shown as skipped in the UI; never printed or stored |
| Phase-1 artifacts (Ari) | `data/index_{nomic,gemma,lms_nomic}.npz` (3 x ~134,700), `data/chunks.json` (20,769), `data/digest.md` (1,684), `data/eval_results.json` (76,448), `data/telemetry.jsonl` (60,119) | present | built for the Ari sha; `python -m twin.index --build all --digest --reflect` rebuilds them for the resolved profile plus the transcript |

Nothing above blocks the build: the example profile, example transcript and example answers stand in for every missing user input.

## 2. What stage 0 generated (this workflow)

- `data/interview_transcript.example.md`: Mara's interview following D3's seven blocks, consistent with every fact in `data/twin_profile.example.v2.md` (decisions D-01..D-15 by title, people by role, routines, beliefs, one politics turn she deflects). Block 6 walks through 11 decisions with the five-field probe script; T-004 ("What did you learn from quitting the agency job?") is the stage-1 search check; block 7 administers the 20 Eval questions verbatim with the gold answers, the self-rating sheet and the consent confirmation.
- `docs/opus_interview_prompt.md`: D3 verbatim minus the politics seed question, plus the machine-readable output rules (per-block `## T-NNN` code blocks, the schema v2 profile with every label, reflections marked "DRAFT - review", `# Changelog v2.0`, a redaction checklist). `docs/opus_profile_prompt.md` keeps a superseded header.
- `docs/INPUTS.md`: this file.
- Item bank agent: `data/items/bank.json`, both example answer waves, `docs/items_licensing.md`.
- Tokens agent: `docs/design/tokens.default.md`, `static/twin.css`, `twin/ui/theme.py`.
- Code for the same stage: `twin/profile.py` (v2 + `--lint`), `twin/transcript.py`, `twin/redact.py`, plus `twin/index.py`, `twin/audit.py`, `twin/prompts.py`, `twin/pipelines/reflect.py` and the `twin/ui` split from the other build agents.

## 3. What the user still has to supply, and what to run afterwards

| When | Supply | Then run (project root, `$env:PYTHONUTF8=1`, never during a GPU stage) |
|---|---|---|
| While workflows B-D run | `data/twin_profile.md` and `data/interview_transcript.md` from the Opus interview (`docs/opus_interview_prompt.md`, about 90-120 min); paste the reviewed reflection drafts into `# Expert reflections` | `python -m twin.redact data\interview_transcript.md` (read the console list of removed strings), `python -m twin.index --build all --digest --reflect`, `python -m twin.profile --lint` |
| Optional, any time | `ANTHROPIC_API_KEY` in the environment | nothing; the Eval tab picks it up on the next run |
| Day 0 (after the session) | wave-1 item answers via the Items tab (about 45 min) -> `data/items/self_answers.json` | Items tab "Run twin" or `python -m twin.pipelines.items --run --condition all` |
| Day 14 | wave-2 answers -> `data/items/self_answers_retest.json` | `python -m twin.pipelines.items --run --condition all` then `--score` and read the decision line |
| After the session | Claude Design export (`docs/claude_design_prompt.md` plus the eight-tab screenshots in `scripts/dev/shots/`) -> `docs/design/tokens.md`, `docs/design/screens/` | re-run workflow A's tokens agent and workflow C with `resumeFromRunId` |

Skipped by decision: Node.js, the `impeccable` skill, political items and probes.
