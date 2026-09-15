# Personal_digital_twin

A local "digital twin" project on a Windows 11 laptop: RTX 2070 (8 GB VRAM), 32 GB RAM. The shell is Windows PowerShell 5.1.
Full setup details, measured numbers, and troubleshooting are in `docs/WINDOWS_SETUP.md`. Read it before changing the model setup.

## Local model endpoints (both on 127.0.0.1 only, no auth)

| Role | Request this name | Endpoint |
|---|---|---|
| Persona chat voice (fast) | `l3-8b-stheno-v3.2` (Stheno Q4_K_M) | LM Studio `http://127.0.0.1:1234/v1` |
| Persona chat voice (Q8_0, slow) | `fluffy/l3-8b-stheno-v3.2:q8_0` | Ollama `http://127.0.0.1:11434` |
| Twin B1/B2 decisions, structured output | `qwen3-8b-8k` | Ollama `http://127.0.0.1:11434` |
| Retrieval embeddings (768 dims) | `nomic-embed-text` | Ollama `/api/embed` |
| Retrieval embeddings, LM Studio side (768 dims; used by the Act tab so hermes3 isn't evicted) | `text-embedding-nomic-embed-text-v1.5` | LM Studio `http://127.0.0.1:1234/v1/embeddings` (load state via `GET /api/v0/models`) |
| Eval ceiling reference (one run) | `claude-sonnet-5` or `claude-opus-5` | Anthropic API, `ANTHROPIC_API_KEY` (the user sets it; never print or store it) |

## Rules learned during setup

- Request LM Studio's Stheno as `l3-8b-stheno-v3.2`. The identifier `stheno-8b` returns HTTP 400 once the model has idled out.
- Use `qwen3-8b-8k`, not `qwen3:8b`. The Ollama app's default context (65536) pushes plain `qwen3:8b` mostly onto the CPU, about 5× slower.
- The Ollama desktop app ignores the `OLLAMA_CONTEXT_LENGTH=8192` user env var and forces 65536, so every plain Ollama request must send `options.num_ctx` (8192 for 8B models, 4096 for llama3.2, 2048 for embedders) and `keep_alive`, constant per model. Only `qwen3-8b-8k` has it baked in.
- Disable Qwen3 thinking, or replies can come back empty: `"think": false` on `/api/chat`, `"reasoning_effort": "none"` on `/v1` (`think` is ignored on `/v1`).
- Always send a system message to the Q8_0 Stheno. Its built-in default contains unfilled `{{char}}`/`{{user}}` placeholders.
- 8 GB VRAM holds only one of these models fully at a time. Models unload when idle (Ollama after 5 min, LM Studio after 10 min).
- Stheno samplers: temperature 1.12 to 1.22, min_p 0.075, top_k 50, repeat penalty 1.1.

## Files and paths

- `models\lmstudio\` is LM Studio's models folder (its `downloadsFolder` setting points here).
- `models\ollama\` holds all Ollama models. `C:\Users\Adity\.ollama\models` is a junction to it. **Never delete or replace that junction**, because the Ollama app ignores `OLLAMA_MODELS` and only finds models through it.
- `modelfiles\qwen3-8b-8k.Modelfile` is the recipe for `qwen3-8b-8k`.
- The `lms` CLI isn't on PATH: `$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe`.
- Ollama CLI: `$env:LOCALAPPDATA\Programs\Ollama\ollama.exe`.
- In PowerShell, use `curl.exe`, not `curl`. `curl` is an alias for Invoke-WebRequest.
- Some `lms` commands (for example `lms import`) show a one-time Y/n prompt even with `--yes`. Feed them `y` on stdin or they hang.

## Open items

- LM Studio's "run server on login" hasn't been confirmed with a reboot. Ollama's auto-start was tested and works.
- `hermes3:8b`: Act tab tool agent (search_profile, get_datetime, calculator, draft_message; see docs/PLAN.md section 4).
- Project code: app.py + twin/ package; the build plan is docs/PLAN.md, the per-stage evidence table is docs/EVIDENCE.md; module API in docs/CONTRACTS.md; run: $env:PYTHONUTF8=1; python app.py --port 7861 (probes 7861..7870 if busy). Dev scratch scripts and logs from the live verification live in scripts/dev/, so data/ holds only the plan's artifacts.
- Everything remaining (interview-based profile v2, conditions, IPIP-50 item bank with retest normalization, safeguards, and the Gradio 6 UI redesign) is one approved plan: docs/PLAN_UNIFIED.md. All four workflows are done: A and B earlier on 2026-09-14, then C and D as PLAN_FINISH phases P3-P5 the same day (docs/PLAN_UNIFIED.md section 11). It supersedes docs/PLAN2.md and docs/PLAN3_UI.md, which stay as design references. Research inputs are in docs/research/D1..D4 and data/twin_profile.example.v2.md ("Mara"); the design brief is docs/claude_design_prompt.md (exports go under docs/design/). Decisions: politics stays out, IPIP-50 not BFI-44, one session, impeccable skipped. UI agents run with TWIN_NO_WARM=1 so they never touch the GPU.
- Design skills installed in .claude/skills (2026-09-14): `frontend-design` (Anthropic, Apache 2.0) for anyone writing theme or CSS; `redesign-existing-projects` (Leonxlnx/taste-skill, MIT) as the audit checklist for restyling; `web-design-guidelines` (Vercel, MIT) as the reviewer rubric (it fetches Vercel's rules at review time). Two more from the same taste-skill repo are parked in docs/skills-not-used/ because they target landing pages, not product UI. Node.js is not installed, so `npx skills add` and `impeccable` do not run here; `winget install OpenJS.NodeJS.LTS` would enable them.
- Restyled UI (P3-P4, 2026-09-14): tokens in docs/design/tokens.default.md reach Gradio through twin/ui/theme.py; styling lives in static/twin.css (tokens, shared classes), static/tabs/frame.css (frame) and static/tabs/<tab>.css (every selector starts with #tab-<id>; rules and classes in docs/CONTRACTS.md "UI styling"). UI check without GPU: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\ui_check.ps1 -Port <7871-7879> -OutDir <dir> [-Themes light,dark] [-Narrow] [-Measure] [-ViewApi]`; it boots with TWIN_NO_WARM=1 and always stops the app it started.
- Nocturne restyle (2026-09-15): docs/design/tokens.md (dark default, Inter, blurple accent, 4/8 px radii) is now the sheet in use, and it overrides tokens.default.md. It added outlined primary buttons, masthead readings with profile and warning disclosures, the Ask evidence rail, a full-width Decide verdict with Raw result behind a disclosure, and Status tiles. The list is in tokens.md section 5, the contract in docs/CONTRACTS.md "UI styling". No live model run has checked the Decide meter since its trigger moved to the result markdown.
- The PLAN_FINISH runbook (docs/PLAN_FINISH.md) is complete as of 2026-09-14. Its Progress log and scripts/dev/finish/state.json record every phase, and its helpers are in scripts/dev/finish/. pytest: 598 passed (pytest.ini sets testpaths = tests).
  - P1-P2: demo fixed and signed off.
  - P3-P4: UI restyled.
  - P5: integration and live checks (docs/EVIDENCE2.md stages 6-7).
  - P6: demo re-signed on the restyled UI.
  - P7: Mac guide docs/REPLICATE_ON_MAC.md.
  - P8: v2 zips C:\Users\Adity\Personal_digital_twin_no_models_v2.zip, ..._claude_memory_v2.zip and ..._claude_env_v2.zip.
- macOS/Linux: `./start.sh` creates .venv, installs requirements.txt and starts the app. It sets TWIN_NO_WARM=1 when no model server answers. Flags: --port, --no-warm, --warm, --test, --open, --dry-run. It hasn't been run on a Mac yet.
- Working preferences (2026-09-14): complete, not perfect (one review plus at most one fix per cycle, blockers only). Write a checkpoint after each phase and ask before starting the next, unless the user says to continue.
- Demo deliverables and evidence:
  - docs/DEMO.md and docs/demo/beats.json.
  - scripts/demo_prep.ps1 and scripts/demo_rehearse.py.
  - docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md.
  - Evidence lives in scripts/dev/demo/.
  - docs/PLAN_DEMO.md stays the demo spec (facts, beat sheet, Verification). Its three-session execution is superseded.
- Workflow scripts live in scripts/dev/workflows/. Advisors and critics run on Opus 5, because Fable 5.1 is over its monthly spend limit.
  
  Session habits: run `claude` in the project folder (Opus 5 with 1M context is the default), keep fast mode off (/fast is a toggle), run /effort ultracode, then paste the kickoff line from docs/PLAN_FINISH.md. Politics deflection is not enforced in code (twin/prompts.py, twin/pipelines/ask.py), so never take a politics question in a demo.
