export const meta = {
  name: 'finish-p7-mac-guide',
  description: 'PLAN_FINISH P7: map the finished project and write one verified docs/REPLICATE_ON_MAC.md (project, models, connections, Claude Code skills, memory and settings) for continuing on a MacBook',
  whenToUse: 'docs/PLAN_FINISH.md phase P7, after P1-P6 are done',
  phases: [
    { title: 'Map', detail: 'five parallel readers: purpose and status, architecture, model connections, data/tests/tooling, demo and evaluation' },
    { title: 'Write', detail: 'one writer composes docs/REPLICATE_ON_MAC.md from the notes' },
    { title: 'Verify', detail: 'accuracy lens and Mac replication lens (runs tests and a no-model app boot on 7879)' },
    { title: 'Fix', detail: 'apply must_fix and safe should_fix once; no re-verify (complete, not perfect)' },
  ],
}

const RUN_DATE = (args && args.runDate) || 'unknown date'
const FINAL_STATE = (args && args.finalState) || 'NOT PROVIDED: read the Progress log in docs/PLAN_FINISH.md and scripts/dev/finish/state.json for the final state before writing anything.'
const ZIPS = (args && args.zips) || 'C:/Users/Adity/Personal_digital_twin_no_models_v2.zip (project without models), C:/Users/Adity/Personal_digital_twin_claude_memory_v2.zip (memory notes), C:/Users/Adity/Personal_digital_twin_claude_env_v2.zip (settings and skills); built in PLAN_FINISH P8 after this guide'
const OUT = 'docs/REPLICATE_ON_MAC.md'

const CONTEXT = `CONTEXT (${RUN_DATE}, docs/PLAN_FINISH.md phase P7)
- Project root: C:/Users/Adity/Personal_digital_twin on Windows 11 (RTX 2070 8 GB, 32 GB RAM, Windows PowerShell 5.1, Python from anaconda3). Not a git repo.
- Why this guide exists: the user continues on a MacBook to work on the logic and connections without the models, and wants the same Claude Code environment there. The guide ships inside the project zip that PLAN_FINISH P8 builds right after this phase.
- Zips (P8): ${ZIPS}. The project zip keeps empty models/ollama and models/lmstudio folders, has top-level folder Personal_digital_twin/, and includes .claude/skills, docs/skills-not-used and scripts/dev/workflows. The memory zip has top-level folder memory/ (MEMORY.md plus notes). The env zip has claude_env/skills (frontend-design, redesign-existing-projects, web-design-guidelines), claude_env/skills-not-used (design-taste-frontend, high-end-visual-design, README.md) and claude_env/user-config/settings.json.
- Final project state (from the PLAN_FINISH Progress log): ${FINAL_STATE}
- Claude Code environment on Windows: native install (check claude --version). Read C:/Users/Adity/.claude/settings.json for the current keys (on 2026-09-14 it held model opus[1m], autoUpdatesChannel, tui, theme, agentPushNotifEnabled and no fastMode key). No user-level skills, agents, commands, hooks, output styles or keybindings. No plugins beyond the official marketplace Claude Code adds automatically. No project MCP servers and no saved tool permissions. claude.ai connectors come with the account login, not files. Claude in Chrome needs the browser extension (on Windows its browser could not open 127.0.0.1, so app screenshots use headless Chrome through scripts/screenshot_tabs.ps1). Never exported: ~/.claude/.credentials.json and ~/.claude.json (login tokens, account and machine ids); the user signs in again on the Mac. The three active skills are project skills in .claude/skills; the two in docs/skills-not-used are parked on purpose (the memory note design-skills-policy.md explains why). Node.js was not installed on Windows, so npx skills add and impeccable never ran.
- Session habits: run claude in the project folder (Opus 5 with 1M context is the default model), keep fast mode off (/fast is a toggle), run /effort ultracode for multi-agent workflows, advisors and critics on Opus 5 (Fable 5.1 was over its monthly spend limit), and use docs/PLAN_FINISH.md as the runbook with its Progress log and one repeatable kickoff line. Workflow scripts live in scripts/dev/workflows/; the GPU stages (P1 Fix, P5 Live, P6 gpu mode) need the Windows laptop's local models.
- Models installed on Windows (ollama list): hermes3:8b, qwen3:8b, llama3.1:8b, fluffy/l3-8b-stheno-v3.2:q8_0, qwen3-8b-8k (created from modelfiles/qwen3-8b-8k.Modelfile: FROM qwen3:8b, PARAMETER num_ctx 8192), nomic-embed-text, embeddinggemma:300m-qat-q4_0, qwen3.5:4b-q8_0, qwen2.5:7b, llama3.2:1b, llama3.2:3b. LM Studio: l3-8b-stheno-v3.2 (bartowski/L3-8B-Stheno-v3.2-GGUF, file L3-8B-Stheno-v3.2-Q4_K_M.gguf, 4,920,734,240 bytes) and text-embedding-nomic-embed-text-v1.5 (bundled with LM Studio; nomic-ai/nomic-embed-text-v1.5-GGUF, nomic-embed-text-v1.5.Q4_K_M.gguf, 84,106,624 bytes). Verified download URLs: https://huggingface.co/bartowski/L3-8B-Stheno-v3.2-GGUF/resolve/main/L3-8B-Stheno-v3.2-Q4_K_M.gguf and https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf
- Demo models (the per-model smoke test used these): nomic-embed-text, llama3.2:1b (router), llama3.2:3b (follow-up rewrite), qwen3-8b-8k (Decide), hermes3:8b (Act), qwen3.5:4b-q8_0 (See), LM Studio l3-8b-stheno-v3.2 (voice), LM Studio text-embedding-nomic-embed-text-v1.5 (Act retrieval). The others serve evaluations and the Q8 voice toggle.
- Claude Code memory on Windows lives at C:/Users/Adity/.claude/projects/C--Users-Adity-Personal-digital-twin/memory (the folder name is derived from the project path).`

const RULES = `RULES
- Read-only unless your task names a file to write. Code is frozen in this phase: never edit twin/, app.py, tests/, static/, data/, scripts/, CLAUDE.md or any doc other than the one your task names. Bugs you find go into the guide's known-issues list, not into code.
- Never start the app, run scripts/demo_prep.ps1, scripts/dev/live_drive.py or scripts/demo_rehearse.py (except --dry-run or --check-profile), call a model, or send HTTP requests to ports 11434, 1234 or 7861-7870. The Mac-lens verifier's prompt states its only exceptions.
- Cite sources as repo-relative path:line. Trust code over docs and comments when they disagree, and say so.
- Large files (docs/CONTRACTS.md, data/eval_results.json, data/telemetry.jsonl, docs/EVIDENCE2.md, docs/ARCHITECTURE.md, data/items/twin_answers.json): use Grep and Read with offset/limit.
- Never run python - with a here-string from PowerShell (its stdin is the null device and Python loops in a REPL). Write a small .py file under scripts/dev/finish/ and run that.
- Never open, print or copy ~/.claude/.credentials.json or ~/.claude.json.`

const NOTES = {
  type: 'object',
  properties: {
    area: { type: 'string' },
    summary: { type: 'string' },
    facts: { type: 'array', items: { type: 'object', properties: { claim: { type: 'string' }, source: { type: 'string' } }, required: ['claim', 'source'] } },
    commands: { type: 'array', items: { type: 'object', properties: { purpose: { type: 'string' }, windows: { type: 'string' }, mac: { type: 'string' }, source: { type: 'string' } }, required: ['purpose', 'source'] } },
    windows_only: { type: 'array', items: { type: 'object', properties: { item: { type: 'string' }, source: { type: 'string' }, mac_equivalent: { type: 'string' } }, required: ['item', 'source'] } },
    open_issues: { type: 'array', items: { type: 'string' } },
    uncertainties: { type: 'array', items: { type: 'string' } },
  },
  required: ['area', 'summary', 'facts', 'commands', 'windows_only', 'open_issues', 'uncertainties'],
}
const ISSUE = {
  type: 'object',
  properties: { quote: { type: 'string' }, problem: { type: 'string' }, source: { type: 'string' }, fix: { type: 'string' } },
  required: ['quote', 'problem', 'source'],
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
const WRITE = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    sections: { type: 'array', items: { type: 'string' } },
    lines: { type: 'integer' },
    unverified: { type: 'array', items: { type: 'string' } },
  },
  required: ['file', 'sections', 'lines', 'unverified'],
}
const FIXED = {
  type: 'object',
  properties: { applied: { type: 'array', items: { type: 'string' } }, skipped: { type: 'array', items: { type: 'string' } }, unresolved_must_fix: { type: 'array', items: { type: 'string' } } },
  required: ['applied', 'skipped', 'unresolved_must_fix'],
}
const OPUS_NOTE = 'MODEL NOTE: you run on Opus 5, the same model that wrote the material you are checking. Compensate: assume the author made mistakes and hunt for them; a statement is not evidence until you open the file that shows it. COMPLETE, NOT PERFECT (the user\'s instruction, 2026-09-14): one verification and at most one fix, never a re-verify. Raise must_fix only for a step that would fail or mislead on the Mac, a wrong command, path or fact the user would act on, or anything that exposes credentials; everything else goes briefly into should_fix.'

const READERS = [
  {
    key: 'R1 purpose and status',
    prompt: `You are reader R1 (purpose, plans, decisions, status) for a replication guide that lets the user continue this project on a MacBook.

${CONTEXT}

${RULES}

READ: README.md, CLAUDE.md (already in your context), docs/PLAN_FINISH.md (whole, including the Progress log), docs/PLAN.md, docs/PLAN_UNIFIED.md (including section 10), docs/PLAN_DEMO.md (whole, including the Checkpoint section), docs/PLAN2.md and docs/PLAN3_UI.md (design references only), docs/INPUTS.md, the stage tables of docs/EVIDENCE.md and docs/EVIDENCE2.md, docs/research/ (list each file with a one-line purpose), docs/opus_interview_prompt.md, docs/opus_profile_prompt.md, docs/research_profile_prompt.md, docs/talk_about_it_prompt.md, docs/claude_design_prompt.md, docs/items_licensing.md, docs/skills-not-used/README.md, .claude/skills/*/SKILL.md (front matter and purpose only), and the memory notes in C:/Users/Adity/.claude/projects/C--Users-Adity-Personal-digital-twin/memory/.

REPORT: what the project is for (the digital twin idea, who it serves, the three conditions, the synthetic profiles Ari and Mara and why they exist); each phase so far (phase 1 PLAN, PLAN_UNIFIED A-D, PLAN_DEMO, PLAN_FINISH P1-P6) with what it delivered and its evidence; the user's decisions; what is still blocked on the user; the engagement protocol as designed; the role of each skill and the design-skills policy; open gaps and known issues; the remaining work in order. Every fact gets a source.`,
  },
  {
    key: 'R2 architecture',
    prompt: `You are reader R2 (architecture and code map) for a replication guide that lets the user work on this project's logic and connections on a MacBook.

${CONTEXT}

${RULES}

READ: app.py; every module under twin/ (Glob twin/**/*.py; module docstrings, public functions, and the wiring between modules); docs/CONTRACTS.md (the section for each module); static/ (twin.css and static/tabs/*.css after the restyle); docs/design/.

REPORT: the repo tree with one line per important file or folder; the module dependency graph (who imports whom); for each tab (Onboarding, Ask, Decide, Act, See, Items, Eval, Status): its UI module, its pipeline function, its gradio api_name endpoints with inputs and outputs, the model calls it makes in order, and the data it reads and writes; the build-time pipeline (transcript, redact, profile lint, chunks, indexes, digest, reflections) with the exact commands to run each step (python -m ... and flags, with path:line); the conditions (demographic, persona, interview) and where their prompts are built; audit and telemetry writes; how the app starts (app.py flags, port probing, default tab, TWIN_NO_WARM, TWIN_THEME); the theme and CSS layering after the restyle; Gradio version specifics that matter. Give function names with path:line so a developer can find the seams.`,
  },
  {
    key: 'R3 models and connections',
    prompt: `You are reader R3 (the model and connection layer) for a replication guide that lets the user work on this project's logic and connections on a MacBook, with or without local models.

${CONTEXT}

${RULES}

READ: twin/config.py (MODELS and every constant); twin/clients.py; twin/gpu.py; wherever telemetry is written; twin/ui/status.py (warm, Free GPU, server checks); README.md (model setup, measured numbers, troubleshooting); modelfiles/qwen3-8b-8k.Modelfile. Grep twin/, app.py and scripts/ for: os.environ, getenv, 127.0.0.1, localhost, 11434, 1234, anthropic, ANTHROPIC, TWIN_, OLLAMA_, nvidia-smi, powershell, .exe, LOCALAPPDATA, USERPROFILE, winreg, msvcrt, subprocess, os.startfile, and path literals with backslashes.

REPORT: a table of every model role (config key, model name, runtime, endpoint path, request shape: num_ctx, keep_alive, think or reasoning_effort, samplers, system message, format or JSON schema, tools, images, max tokens); the client functions that call each endpoint (path:line); what happens when a server is down or a model is missing (errors shown, retries, whether the app still boots and renders); GPU sequencing (ModelManager, the gpu queue, pre-warm on tab select, heartbeat, keep-alive values, Free GPU); every environment variable the code reads, with its default and effect; every Windows-only dependency in Python code with a macOS equivalent; what would have to change, if anything, to run the app on macOS with Ollama and LM Studio for Mac, or to use models on another machine (for example an SSH tunnel that keeps 127.0.0.1). Keep "what the code does" (sourced) separate from "suggested for Mac" (labeled).`,
  },
  {
    key: 'R4 data, tests and tooling',
    prompt: `You are reader R4 (data files, tests, scripts and the development loop) for a replication guide that lets the user work on this project on a MacBook.

${CONTEXT}

${RULES}

READ: requirements.txt; tests/ (Glob tests/*.py: what each file covers, conftest and fixtures, how model calls are mocked, which tests need TWIN_NO_WARM); data/ (every file: what creates it, what reads it, input or generated artifact, cache keys by profile sha); scripts/*.ps1, scripts/*.py, scripts/dev/*.py, scripts/dev/evidence/, scripts/dev/workflows/ (what each workflow script is for and which need the GPU); docs/demo/beats.json (shape).
YOU MAY RUN (and only these): python --version; python -m pip show for gradio, gradio_client and every package in requirements.txt (record exact installed versions); python -m pytest --collect-only -q with TWIN_NO_WARM=1 and PYTHONUTF8=1 (test counts per file).

REPORT: the no-model development loop (exact commands to run the test suite on macOS zsh, with env vars and pytest flags); Python and package versions; a data-file lifecycle table; every script with its purpose and a macOS zsh equivalent (for example Free GPU: ollama stop for each model in ollama ps, and lms unload --all with the Mac lms CLI, usually ~/.lmstudio/bin/lms; server check: curl -s http://127.0.0.1:11434/api/tags and curl -s http://127.0.0.1:1234/api/v0/models; macOS has no nvidia-smi); which scripts are Windows-only; what delete_twin does.`,
  },
  {
    key: 'R5 demo, evaluation and safeguards',
    prompt: `You are reader R5 (demo, evaluation and safeguards) for a replication guide that lets the user continue this project on a MacBook.

${CONTEXT}

${RULES}

READ: docs/DEMO.md; docs/demo/beats.json; scripts/dev/demo/rehearsal.md (including "Runs after fixes" and "After restyle"); scripts/dev/demo/model_smoke.md; docs/EVIDENCE2.md stages 3-7; data/items/scores.json (decision line, retest normalization); data/eval_results.json (voice bake-off, retrieval recall, probes block); twin/pipelines/evals.py; the item bank code and data/items/bank.json (shape only); data/probes.json; the redaction module; twin/audit.py; scripts/delete_twin.ps1; twin/prompts.py (BOUNDARIES); sections 8-9 of docs/ARCHITECTURE.md and docs/CLIENT_TALKING_POINTS.md (verify against sources).

REPORT: what the evaluation measures and how (bake-offs, item bank of IPIP-50 + games + GSS, retest normalization, the decision rule, judges) with the exact current numbers and their caveats (synthetic retest ceilings; local judges; protocol never run with a real person); the safeguards exactly as implemented and their gaps (politics not enforced; See and Act polish not audited; demographic condition without BOUNDARIES; consent display-only); a summary of the signed-off demo (beats, measured timings, forbidden controls, known issues and app fixes); open decisions, with sources.`,
  },
]

function writerPrompt(notes) {
  return `You are the writer. Create ${OUT}: ONE self-contained Markdown guide that lets the user (and Claude Code on their MacBook) understand everything this project does, set up the same Claude Code environment (skills, memory, settings), and continue working on the project's logic and connections on macOS, starting from the three zips without the models. Someone with only this file and the zips must be able to get oriented, set up Claude Code and Python, run the tests, boot the app without models, find the seams to work on, and see what work remains. Link to the deeper docs inside the zip rather than copying them wholesale.

${CONTEXT}

${RULES}

You may write only ${OUT}. Re-open sources to confirm what you state; the reader notes below are leads with citations, not gospel. Where readers disagree, check the code. For the Claude Code install and skills paths on macOS you may use WebFetch on the official Claude Code docs (for example https://docs.claude.com/en/docs/claude-code/setup and https://docs.claude.com/en/docs/claude-code/skills); state only what you confirm there, otherwise point to the docs page.

STRUCTURE: a title, a one-paragraph summary, a table of contents, then numbered H2 sections:
1. What this project is: the digital twin idea in plain words, who it serves, the eight tabs and what each does, the three conditions, the synthetic profiles (Ari, Mara) and why they exist.
2. Where it stands (as of ${RUN_DATE}): what is built and evidenced (name the evidence docs), the test count, the signed-off demo and the restyled UI, app fixes and known issues, decisions made, what is still blocked on the user, open gaps (politics deflection not enforced, and any others the sources show).
3. The three zips and unpacking on the Mac: what each zip holds and exact zsh commands (unzip the project into the home folder so it lands at ~/Personal_digital_twin; keep the memory and env zips for section 4).
4. Claude Code on the Mac: install Claude Code (confirmed command or the docs link) and sign in; apply claude_env/user-config/settings.json to ~/.claude/settings.json (merge by hand if the file already exists; never overwrite other keys blindly); skills: the three active skills arrive with the project in .claude/skills and load when Claude Code runs in the project folder, optionally copy them to ~/.claude/skills for every project, keep the two parked skills out unless the user decides otherwise (explain why they're parked); memory: open Claude Code in ~/Personal_digital_twin once, then copy memory/ from the memory zip into the folder Claude Code created under ~/.claude/projects/ for the Mac path (explain that the Windows folder name C--Users-Adity-Personal-digital-twin came from the Windows path, so the Mac name differs, and how to find it); what does not transfer and why (credentials, ~/.claude.json, claude.ai connectors come with login, the official plugin marketplace is added automatically, the Claude in Chrome extension must be installed in the Mac browser); optional Node.js for npx skills add and impeccable (untested); session habits (Opus 5 1M default, fast mode off, /effort ultracode, Opus advisors, docs/PLAN_FINISH.md as the runbook pattern); a checklist to confirm the environment (the skills show up, CLAUDE.md is loaded, memory recall works).
5. Repo map: a tree with one line per important file or folder; which files are inputs and which are generated; scripts/dev/workflows/ and which workflows need the Windows GPU.
6. Architecture: one Mermaid flowchart (browser -> app.py and twin/ui -> twin/pipelines -> twin/clients -> Ollama, LM Studio, Anthropic API; plus data/), then per tab: UI module, pipeline function, gradio api_name, model calls in order, data read and written.
7. The build-time pipeline: from interview transcript to redaction, profile lint, chunks, indexes, digest and reflections, with exact commands.
8. Models and connections: the MODELS table (role, config key, model name, runtime, endpoint, request settings), client functions, GPU sequencing and keep-alive, environment variables with defaults, telemetry and audit, and the rules learned on Windows, labeled "observed on Windows" where they may not apply on macOS (the Ollama desktop app ignoring OLLAMA_MODELS and OLLAMA_CONTEXT_LENGTH, the models junction, LM Studio identifiers, Qwen3 thinking off, the Stheno system message and samplers, one big model at a time on 8 GB).
9. Setting up the Python project on the MacBook: the Python version and exact package versions from the Windows machine, a venv, pip install -r requirements.txt, running the tests with TWIN_NO_WARM=1 (state the final count from the sources), booting the app with TWIN_NO_WARM=1 and what works without model servers (and what errors show); optional: installing Ollama and LM Studio for Mac and getting the models (Mac commands; memory guidance for Apple Silicon unified memory without inventing the user's specs; which models the demo needs vs the evaluations); optional: using the Windows laptop as the model server through an SSH tunnel that keeps 127.0.0.1 (label untested).
10. Windows-only pieces and Mac equivalents: a table (PowerShell scripts, curl.exe, the lms.exe path vs the Mac lms CLI, the Ollama CLI path, nvidia-smi, the .ollama junction, headless chrome.exe screenshots, Start-Process and PIDs, PYTHONUTF8, backslash paths), plus any Windows-only code paths in Python.
11. Working on logic and connections without models: the test suite and how clients are mocked; docs/CONTRACTS.md; the seams (function names with path:line) for each pipeline and client; how to change or add a model route safely; exercising endpoints with scripts/dev/live_drive.py when a server is available; suggested next logic work in priority order drawn from the open issues in the sources, each with its source and labeled "suggested".
12. Remaining work and how to continue: what is blocked on the user (real profile and interview, day-0 and day-14 item answers, ANTHROPIC_API_KEY, Claude Design exports, the politics decision), the real-person engagement as designed, and how to run a runbook-style session like PLAN_FINISH on the Mac (GPU stages still need the Windows laptop).
13. Rules and gotchas: CLAUDE.md rules, the workflow lessons from memory, and safety rules (forbidden live controls, Items Run twin and Score rewrite data files, never delete the junction on Windows, 127.0.0.1 only, never print ANTHROPIC_API_KEY, never share Claude Code credential files).
Appendix A: command cheat sheet, Windows PowerShell and macOS zsh side by side.
Appendix B: glossary (twin, condition, digest, reflections, block 7, probes, retest normalization, pre-warm, heartbeat, keep-alive, skill, auto-memory, DEMO CONTRACT).

WRITING RULES: plain, direct sentences; exact names, paths, commands and numbers from sources; label anything not tried on a Mac "untested on macOS"; no invented features or numbers; tag code blocks (zsh, powershell, python, json, text); Mermaid only as flowchart or sequenceDiagram with quoted labels and no semicolons; tables to stay compact; completeness over brevity, but no wholesale copies of other docs.

BEFORE RETURNING: re-read the whole file; confirm every repo path you cite exists (Glob); confirm every command's flags against the code or script it runs; list anything you could not verify in unverified (and mark it in the file).

READER NOTES (JSON):
${JSON.stringify(notes, null, 1)}`
}

function accuracyPrompt(round, prior) {
  return `You are verifier V1 (accuracy lens), round ${round}, for ${OUT}. Read-only: edit nothing.

${CONTEXT}

${RULES}

Default stance: every statement is unproven until you open its source. Read ${OUT} in full. Check every path, module and function name, path:line reference, command and flag, environment variable, model name, endpoint, request setting, number, status claim and plan step against the repo (code first, then docs/CONTRACTS.md, docs/PLAN_*.md, docs/EVIDENCE*.md, scripts/dev/demo/rehearsal.md, the data JSON files). Check the claims about the zips against docs/PLAN_FINISH.md P8 and, if the zips already exist, list them with a small Python zipfile script (names only). Check the Mermaid block parses by eye (flowchart or sequenceDiagram header, quoted labels, no semicolons).
must_fix: anything wrong, invented, contradicted by code, or stale; a command that would fail as written; a missing required section; a claim presented as tested on macOS when it was not; any instruction that would copy or expose credentials.
should_fix: unclear wording, missing cross-links, weak but not wrong claims.
${prior ? 'PREVIOUS ROUND must_fix (confirm each is really fixed and nothing new broke):\n' + prior : ''}
For each item: quote (exact text), problem, source (path:line and what it shows), fix (the corrected text when you know it). go is true only when must_fix is empty. List the checks you ran.`
}

function macPrompt(round, prior) {
  return `You are verifier V2 (Mac replication lens), round ${round}, for ${OUT}. You edit nothing.

${CONTEXT}

${RULES}

EXCEPTIONS FOR YOU ONLY (empirical checks on this Windows laptop, never loading a model):
- Run the test suite as the guide says, adapted to PowerShell: $env:TWIN_NO_WARM='1'; $env:PYTHONUTF8='1'; python -m pytest -q -p no:cacheprovider. Report the summary line.
- Boot the app with model loading disabled, in ONE command (the PowerShell tool ends processes a command started when that command returns, so a Start-Process in one tool call is gone by the next): powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\dev\\finish\\ui_check.ps1 -Port 7879 -OutDir scripts\\dev\\shots\\p7_v2 -NoShots -ViewApi. It boots python app.py with TWIN_NO_WARM=1, checks HTTP 200 and the view_api names, and always stops the app it started. Compare the api names in scripts/dev/shots/p7_v2/view_api.json with the guide. Never open a browser, never call an endpoint that runs a model, never touch ports 7861-7870.
- You may WebFetch the official Claude Code docs to check the guide's install command and skills and settings paths.

Walk the guide as a developer on a MacBook with only the three zips, no models and zsh:
- Could they install and sign in to Claude Code, apply the settings safely, get the skills recognized, restore the memory notes into the right ~/.claude/projects folder, create a venv, install the exact packages, run the tests and boot the app from these instructions alone? Are the zsh commands correct on macOS (unzip, python3 and venv, export for env vars, cp and mkdir -p, curl, the Mac lms CLI path, ollama CLI)? Is anything Windows-only presented without a Mac equivalent? Grep the Python code for Windows-only calls (os.startfile, winreg, msvcrt, powershell, .exe, nvidia-smi, LOCALAPPDATA, backslash paths) and check the guide lists every one that matters.
- Does the guide make "logic and connections" work concrete: the seams with path:line, how clients are mocked in tests, how to change a model route, how to test against a real server later?
- Is it honest about what needs the Windows laptop's GPU?
${prior ? 'PREVIOUS ROUND must_fix (confirm each is really fixed and nothing new broke):\n' + prior : ''}
must_fix: a step that would fail or mislead on a Mac, a missing prerequisite, an instruction that risks overwriting the user's Mac settings or exposing credentials, a result of your empirical checks that contradicts the guide. should_fix: friction and gaps. For each item: quote, problem, source (path:line, docs URL or your command output), fix. go is true only when must_fix is empty. List every check you ran with its result.`
}

function fixPrompt(round, verdicts) {
  return `You are the fixer, round ${round}. Edit only ${OUT}.

${CONTEXT}

${RULES}

Apply every must_fix below, and should_fix items that are safe and local. Re-open the cited source for each change; never replace one guess with another; if a claim can't be sourced, cut it or label it "untested on macOS" or "suggested". Keep the section structure and the table of contents in sync. Re-read any Mermaid block you touch.

VERDICTS (JSON):
${JSON.stringify(verdicts, null, 1)}

Return what you applied and what you skipped, with reasons, and unresolved_must_fix: each must_fix you could not fully resolve, with the reason (an empty list when all are resolved).`
}

phase('Map')
const readerResults = await parallel(READERS.map(r => () => agent(r.prompt, { label: r.key, phase: 'Map', schema: NOTES })))
const notes = readerResults.map((n, i) => n ? n : { area: READERS[i].key, summary: 'READER FAILED: gather this area yourself from the sources named in its prompt.', facts: [], commands: [], windows_only: [], open_issues: [], uncertainties: [] })
const failedReaders = READERS.filter((r, i) => !readerResults[i]).map(r => r.key)
if (failedReaders.length >= 2) return { status: 'blocked', stage: 'Map', reason: `readers returned nothing: ${failedReaders.join(', ')}` }
if (failedReaders.length) log(`Reader that returned nothing (writer covers it directly): ${failedReaders.join(', ')}`)
log(`Map done: ${notes.reduce((n, x) => n + x.facts.length, 0)} sourced facts, ${notes.reduce((n, x) => n + x.windows_only.length, 0)} Windows-only items`)

phase('Write')
const written = await agent(writerPrompt(notes), { label: 'Writer', phase: 'Write', schema: WRITE })
if (!written) return { status: 'blocked', stage: 'Write', reason: 'writer returned null' }
log(`Wrote ${written.file}: ${written.sections.length} sections, ${written.lines} lines, ${written.unverified.length} unverified items`)

async function verify(round, prior) {
  const res = await parallel([
    () => agent(OPUS_NOTE + '\n\n' + accuracyPrompt(round, prior ? prior.accuracy : ''), { label: `V1 accuracy r${round}`, phase: 'Verify', schema: VERDICT }),
    () => agent(OPUS_NOTE + '\n\n' + macPrompt(round, prior ? prior.mac : ''), { label: `V2 Mac lens r${round}`, phase: 'Verify', schema: VERDICT }),
  ])
  if (!res[0] || !res[1]) throw new Error(`verifier returned null in round ${round}`)
  return { accuracy: res[0], mac: res[1] }
}
const must = v => v.accuracy.must_fix.length + v.mac.must_fix.length
const should = v => (v.accuracy.should_fix || []).length + (v.mac.should_fix || []).length

let verdicts
try {
  verdicts = await verify(0, null)
} catch (e) {
  return { status: 'blocked', stage: 'Verify', reason: String((e && e.message) || e), written }
}
log(`Verify r0: ${must(verdicts)} must_fix, ${should(verdicts)} should_fix`)
const rounds = [{ round: 0, must_fix: must(verdicts), should_fix: should(verdicts) }]
const fixes = []
// Complete, not perfect (user, 2026-09-14): one verification, at most one fix, no re-verify.
let unresolved = []
if (must(verdicts) > 0 || should(verdicts) > 0) {
  phase('Fix')
  const fx = await agent(fixPrompt(1, verdicts), { label: 'Fix r1', phase: 'Fix', effort: 'low', schema: FIXED })
  if (!fx) return { status: 'blocked', stage: 'Fix', round: 1, reason: 'fixer returned null', verdicts }
  unresolved = fx.unresolved_must_fix || []
  fixes.push({ round: 1, applied: fx.applied.length, skipped: fx.skipped, unresolved_must_fix: unresolved })
  log(`Fix r1: ${fx.applied.length} applied, ${fx.skipped.length} skipped, ${unresolved.length} must_fix unresolved`)
}
return {
  status: unresolved.length === 0 ? 'done' : 'open',
  unresolved_must_fix: unresolved,
  file: OUT,
  written,
  rounds,
  fixes,
  final_checks: { accuracy: verdicts.accuracy.checks_run, mac: verdicts.mac.checks_run },
  remaining_must_fix: { accuracy: verdicts.accuracy.must_fix, mac: verdicts.mac.must_fix },
  remaining_should_fix: { accuracy: verdicts.accuracy.should_fix || [], mac: verdicts.mac.should_fix || [] },
}
