# Digital Twin demo: self-contained build plan

Written 2026-09-13 for execution in a fresh Claude Code session. Everything a new session needs is in this file; nothing depends on the conversation that produced it.

## 0. Kickoff (paste this single line into the new session)

```
ultracode: read C:\Users\Adity\.claude\plans\are-these-models-enough-keen-bachman.md in full, copy it to docs\PLAN.md and its section 3 to docs\opus_profile_prompt.md, then execute sections 5 and 6 exactly; don't ask for confirmation between phases and don't stop until every stage has passing evidence or is blocked on something only I can supply, and list any blocked items at the end.
```

Standing instructions from the user, in their words: "don't stop until everything is built", "update the plan for fable 5.1 ultracode fast mode". Fast mode is an Opus-only feature and cannot be enabled on Fable 5.1 by the assistant; if the user wants it they switch with `/model` to Opus 5 then `/fast`. The workflows run unchanged on either model.

## 1. Context

`C:\Users\Adity\Personal_digital_twin` holds two working local model servers and 13 models, but no code. The user wants a local web demo of an "answer as me" digital twin that gives every model in the folder a visible job, plus a prompt to run in Claude Opus that produces the twin's personal profile file. Verdict from the audit: **the models are enough; nothing new is needed.** The only constraint is the 8 GB GPU, which the design handles by sequencing loads.

### Verified facts (audited 2026-09-13; trust these, re-probe only if something fails)

Windows 11, RTX 2070 8 GB, 32 GB RAM, Windows PowerShell 5.1. Python 3.13.9 at `C:\Users\Adity\anaconda3\python.exe`. Installed: openai 2.x, httpx, requests, numpy, streamlit. Not installed: gradio, anthropic. Port 7860 free. Project is **not** a git repository (no worktrees possible). CLAUDE.md and README.md in the project document the servers; read them first.

LM Studio 0.4.24, `http://127.0.0.1:1234/v1`, OpenAI-compatible, no auth, JIT load, unload after 600 s idle:

| Model id | What | Notes |
|---|---|---|
| `l3-8b-stheno-v3.2` | Llama-3 8B Stheno Q4_K_M, ctx 8192 | cold ~6 s, warm 0.3 s, 49 tok/s, 5.6 GB. Never request as `stheno-8b` |
| `text-embedding-nomic-embed-text-v1.5` | embeddings, 768 dims | not in README yet |

`GET /api/v0/models` reports `state: loaded|not-loaded` without triggering a load. Unload: `& "$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe" unload --all`. Some `lms` commands prompt Y/n even with `--yes`; feed `y` on stdin.

Ollama 0.34.0, `http://127.0.0.1:11434`, no auth. Effective server config (from server.log): `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=5m`, flash attention on, KV cache q8_0, **`OLLAMA_CONTEXT_LENGTH` forced to 65536 by the desktop app** (the user env var 8192 is ignored), models path forced to `C:\Users\Adity\.ollama\models`, which is a junction to `Personal_digital_twin\models\ollama`. Never delete that junction.

| Model | Size on disk | Capabilities | Measured | Notes |
|---|---|---|---|---|
| `fluffy/l3-8b-stheno-v3.2:q8_0` | 8.5 GB | completion | 14 s cold, 12 tok/s, 67% GPU | Llama-3 template. Built-in default system prompt has unfilled `{{char}}`; always send a system message |
| `qwen3-8b-8k` | shares qwen3:8b blob | tools, thinking | 6.7 s cold, 47 tok/s, 100% GPU, ctx 8192 baked | `think:false` required or content comes back empty; `format` schema works |
| `qwen3:8b` | 5.2 GB | tools, thinking | 9 s cold, 16 tok/s, 8.8 GB, ctx 40960 | only for one-shot long-context use |
| `hermes3:8b` | 4.7 GB | tools | | ChatML template with native `<tools>` block, works with `/api/chat` `tools` |
| `llama3.1:8b` | 4.9 GB | tools | | |
| `qwen2.5:7b` | 4.7 GB | tools | | |
| `qwen3.5:4b-q8_0` | 5.3 GB | vision, tools, thinking | | the only vision model; metadata ctx 262144, so `num_ctx` is mandatory |
| `llama3.2:3b` | 2.0 GB | tools | | small, fits beside Stheno |
| `llama3.2:1b` | 1.3 GB | tools | | small, fits beside Stheno |
| `nomic-embed-text` | 0.27 GB | embedding, 768 | 1.3 to 2.8 s cold | |
| `embeddinggemma:300m-qat-q4_0` | 0.24 GB | embedding, 768 | | |

Anthropic: `claude-sonnet-5` / `claude-opus-5` when `ANTHROPIC_API_KEY` is set. **It is not set anywhere right now.** Never print or store it.

Two consequences that drive the design:

- Every Ollama request must send `options.num_ctx` (8192 for 8B models, 4096 for llama3.2, 2048 for embedders), constant per model, or plain models load at 65536 context and spill to CPU like qwen3:8b does.
- With one loaded Ollama model at a time, any Ollama embedding call evicts the Ollama chat model. The tool-agent tab therefore embeds with LM Studio's nomic.

Stheno samplers from its card: temperature 1.12 to 1.22, min_p 0.075, top_k 50, repeat penalty 1.1. In PowerShell use `curl.exe` for GETs and `Invoke-RestMethod -Body (@{..} | ConvertTo-Json -Depth 6)` for JSON POSTs (PowerShell 5.1 mangles inline JSON quotes passed to curl.exe).

## 2. Profile file: `data\twin_profile.md`

The app chunks this file by `##` headings, so the layout is fixed. The user produces it with the Opus prompt in section 3. Until it exists, the build uses a synthetic `data\twin_profile.example.md` in the same layout.

```
---
name: <first name>
updated: YYYY-MM-DD
---
# Identity
<3-6 lines: name, age range, city, what they do, one-line self-description>

# Voice
## Style rules
<8-12 bullet rules: sentence length, punctuation habits, slang, emoji use, how they greet, how they disagree, what they never say>
## Sample 1
<one verbatim message the user actually wrote, 1-4 sentences>
## Sample 2 ... ## Sample 15

# Values
<6-10 bullets, each a principle plus one sentence on how it shows up>

# Preferences
## Food
## Tech and tools
## Work style
## Free time
## Money
## Communication
<3-8 bullets each>

# People
<roles only, no real names: "my manager", "my closest friend", one line on how the user talks to each>

# Decisions
## D-01: <short title>
Situation: <2-3 sentences>
Options: <A> | <B> [| <C>]
Choice: <A>
Why: <2-3 sentences in the user's reasoning style>
Outcome: <1 sentence, or "unknown yet">
## D-02 ... ## D-20  (at least 15)

# Goals
<5-8 bullets, near-term and long-term>

# Boundaries
<what the twin must refuse or deflect: topics, people, private facts>

# Eval
## Q-01
Question: <something someone might ask the user>
Answer: <how the user would actually answer, in their voice, 1-3 sentences>
## Q-02 ... ## Q-20
```

Rules: no passwords, addresses, account numbers, or other people's real names; samples verbatim, not invented; Eval answers are gold labels in the user's real phrasing. The Eval section is excluded from the retrieval index.

## 3. Opus prompt (complete, paste into claude.ai with Opus; also saved to `docs\opus_profile_prompt.md`)

````
You are helping me build a local "digital twin": a small language model that answers questions as me, in my voice, and predicts my decisions. It reads ONE markdown file, so your job is to interview me and then write that file perfectly.

## How to work
1. Interview me in rounds. Each round, ask at most 8 focused questions, grouped by topic, then wait for my answers. Order: Identity → Voice → Values → Preferences → People → Decisions → Goals → Boundaries → Eval. Skip anything I already answered.
2. For Voice, ask me to paste 15 real messages I've sent (texts, chats, emails, comments). Do not invent or polish them. From them, derive the style rules yourself and show me the rules for approval.
3. For Decisions, dig for at least 15 real choices from the last few years (jobs, purchases, moves, habits, relationships, tech, money). For each, get the situation, the options I had, what I picked, my actual reasoning, and what happened. Push for specifics; vague entries are useless.
4. For Eval, write 20 questions a friend, recruiter, or family member might realistically ask me, then ask me to answer each in one to three sentences in my own words. Keep my wording verbatim.
5. Research angle: when I give you a document (resume, bio, journal excerpt, old posts), extract facts and voice evidence from it and ask only about gaps. Quote my own phrasing wherever you can.
6. Privacy: never include passwords, addresses, account or ID numbers, health details I haven't explicitly approved, or other people's real names. Refer to people by role ("my manager", "my sister").
7. After the interview, output the complete file in a single markdown code block, in EXACTLY the structure below. Headings, section order, and the `D-NN` / `Q-NN` / `Sample N` labels are parsed by software, so do not rename or reorder them. Then ask me to review and tell you what to fix.

## Required file structure
```
---
name: <first name>
updated: YYYY-MM-DD
---
# Identity
<3-6 lines: name, age range, city, what I do, one-line self-description>

# Voice
## Style rules
<8-12 bullet rules: sentence length, punctuation habits, slang, emoji use, how I greet, how I disagree, what I never say>
## Sample 1
<one verbatim message I actually wrote, 1-4 sentences>
## Sample 2
...
## Sample 15

# Values
<6-10 bullets, each a principle plus one sentence on how it shows up>

# Preferences
## Food
## Tech and tools
## Work style
## Free time
## Money
## Communication
<3-8 bullets under each>

# People
<roles only, no real names, one line on how I talk to each>

# Decisions
## D-01: <short title>
Situation: <2-3 sentences>
Options: <A> | <B> [| <C>]
Choice: <A>
Why: <2-3 sentences in my reasoning style>
Outcome: <1 sentence, or "unknown yet">
## D-02 ...
(at least 15, up to 20)

# Goals
<5-8 bullets, near-term and long-term>

# Boundaries
<what the twin must refuse or deflect: topics, people, private facts>

# Eval
## Q-01
Question: <something someone might ask me>
Answer: <how I would actually answer, in my voice, 1-3 sentences>
## Q-02 ...
(exactly 20)
```

## Start
Begin round 1 now: Identity and a first pass at Voice. Ask me to paste my first batch of real messages.
````

## 4. App design

Single Gradio app (`app.py`) with six tabs: **Ask, Decide, Act, See, Eval, Status**. Install: `pip install gradio anthropic`. Run: `$env:PYTHONUTF8=1; $env:GRADIO_ANALYTICS_ENABLED="False"; python app.py --port 7861`, bound to 127.0.0.1.

### Model → role map (every model has a job)

| Model | Runtime | Job | VRAM class | num_ctx | keep_alive |
|---|---|---|---|---|---|
| l3-8b-stheno-v3.2 | LM Studio | Voice: the twin's reply in Ask, Decide "say it", See reaction, Act polish. Bake-off candidate | big | fixed 8192 | LMS TTL + heartbeat |
| stheno q8_0 | Ollama | Voice "high precision" toggle. Bake-off candidate | huge (spills) | 8192 | 10m |
| qwen3-8b-8k | Ollama | Decide B1 (yes/no) and B2 (A vs B) as JSON schema. Bake-off candidate | big | baked | 10m |
| qwen3:8b | Ollama | One-shot profile digest at index build (whole profile, 40960 ctx) cached to `data\digest.md`, unloaded right after | huge | default | 0 |
| hermes3:8b | Ollama | Act tab: native tool calling: search_profile, get_datetime, calculator, draft_message | big | 8192 | 10m |
| qwen2.5:7b | Ollama | Consistency checker (reply vs retrieved chunks): opt-in in Ask, always on in Eval. Second judge | big | 8192 | 10m |
| llama3.1:8b | Ollama | Primary LLM judge for the voice bake-off (different family from Stheno). Candidate | big | 8192 | 10m |
| qwen3.5:4b-q8_0 | Ollama | See tab: describes an uploaded image, then Stheno reacts | big | 8192 | 10m |
| llama3.2:3b | Ollama | Follow-up query rewrite; fallback voice if LM Studio is down | small | 4096 | 30m |
| llama3.2:1b | Ollama | Router: intent JSON (about_me / decide / tool / image / smalltalk) | small | 4096 | 30m |
| nomic-embed-text | Ollama | Primary retrieval index | small | 2048 | 30m |
| embeddinggemma | Ollama | Second index for the retrieval bake-off | small | 2048 | 30m |
| nomic v1.5 | LM Studio | Act tab search_profile embedder (does not evict hermes3); third index | small | n/a | LMS TTL |
| claude-sonnet-5 | Anthropic | Optional ceiling judge, only when the key is set | none | | |

### Repo layout

```
app.py                      Gradio Blocks, 6 tabs, UI wiring only
requirements.txt            gradio>=5, openai, httpx, numpy, anthropic
twin\config.py              model registry (runtime, vram class, num_ctx, keep_alive, samplers), endpoints, CLI paths, data paths
twin\clients.py             httpx/openai wrappers: ollama chat/embed/ps/tags/show/stop, lms chat/embed/models_v0, anthropic; records telemetry
twin\gpu.py                 ModelManager: ensure(model), warm(model), heartbeat, one global lock
twin\telemetry.py           ring buffer of call records (tab, model, load ms, tokens, tok/s, wall ms) + data\telemetry.jsonl
twin\profile.py             parse twin_profile.md into chunks, decisions, eval Q/A, sha256
twin\index.py               build/load/search three .npz indexes; CLI: --build all | --digest | --search "q"
twin\prompts.py             system prompts and JSON schemas: voice, router, rewrite, B1, B2, checker, judge, vision, agent
twin\pipelines\ask.py decide.py act.py see.py digest.py evals.py
tests\test_*.py             mocked-client tests asserting exact request bodies; no network
scripts\check_servers.ps1   stage-0 health check;  scripts\free_gpu.ps1  the README unload commands
docs\PLAN.md                copy of this file;  docs\opus_profile_prompt.md  section 3
data\                       twin_profile.md (user), twin_profile.example.md, digest.md, chunks.json, index_*.npz, eval_results.json, telemetry.jsonl
```

### GPU manager rules (`twin\gpu.py`)

1. Loading Stheno on LM Studio: if `/api/ps` shows a big Ollama model, stop it first (`POST /api/generate {"model": X, "keep_alive": 0}`). Small Ollama models stay.
2. Loading a big Ollama model: if LM Studio `/api/v0/models` shows Stheno `loaded`, run `lms unload --all` first. Ollama evicts its own previous model.
3. Small Ollama models: no action; they fit beside Stheno.
4. Every Ollama request carries `options.num_ctx` and `keep_alive` from the registry. Never vary num_ctx for a model between calls.
5. `warm(model)`: Ollama no-prompt `/api/generate` with keep_alive; LM Studio a 1-token chat. Pre-warm on tab select (Ask→Stheno, Decide→qwen3-8b-8k, Act→hermes3, See→qwen3.5). Heartbeat thread re-warms only the active tab's model every 4 min.
6. All model calls go through one `threading.Lock`; Gradio `default_concurrency_limit=1`.

Ask-turn budget with Stheno warm: router 0.7 s + rewrite 2 s (follow-ups only) + embed 0.5 s + 150 tokens at 49 tok/s ≈ 6 s; plus 6 s if Stheno is cold.

### Pipelines

- **Ask**: llama3.2:1b router (`format` schema `{intent enum}`, temp 0; parse failure → about_me) → llama3.2:3b rewrite when history exists → nomic embed with `search_query:` prefix → cosine top-5 (+0.05 boost on Decisions when intent=decide) → Stheno stream. Static voice prefix (Identity, Voice rules, 3 samples, Boundaries, digest ≤400 tokens) identical every turn so LM Studio's prefix cache hits, then `CONTEXT:` chunks, then last 6 turns. System prompt: "You are <name>, replying as yourself in a text chat. Output only your message: no asterisks, actions, narration, stage directions, quotes, or character/AI mentions. First person. Only state facts about yourself that appear in CONTEXT; otherwise say you don't remember." Temperature slider default 1.0, `extra_body` min_p 0.075 / top_k 50 / repeat_penalty 1.1, max_tokens 300. Strip `*action*` spans and `Name:` prefixes. Q8 toggle sends the same system message via `/api/chat` with the samplers in `options`. `tool`/`image` intents show a hint pointing at the Act/See tab. Opt-in qwen2.5 checker: `format` `{consistent: bool, unsupported_claims: [], contradictions: []}`, temp 0, shown as a badge. Fallback voice llama3.2:3b when the LM Studio health probe fails.
- **Decide**: embed situation → top-8 from Decisions/Values/Preferences/Boundaries + digest → qwen3-8b-8k `think:false`, temp 0.2, `num_predict` 600, `format` schema. *Deviation (as built):* the situation is embedded with LM Studio's nomic v1.5 (`index_lms_nomic.npz`, falling back to Ollama nomic only when that index is missing) so the Ollama embed cannot evict a pre-warmed qwen3-8b-8k (`OLLAMA_MAX_LOADED_MODELS=1`); `gpu.ensure("qwen3_8k")` unloads LM Studio only when a chat model is loaded, so the 0.27 GB embedder stays resident for its LM Studio TTL. After a Decide turn `lms ps` therefore shows `text-embedding-nomic-embed-text-v1.5` (no chat model), not an empty list. B1: `{verdict yes|no, confidence 0-1, reasons[], cited_decisions[], what_would_change_my_mind}`. B2: `{choice A|B, confidence, reasons[], cited_decisions[], tradeoff}`. On `done_reason == "length"` retry with num_predict 1200. "Say it in my voice" button renders the JSON as a one-liner with Stheno (swap happens only on click).
- **Act**: hermes3 `/api/chat` with OpenAI-style `tools`, temp 0.3, loop ≤5: on `message.tool_calls` run the tool, append `{"role":"tool","tool_name":name,"content":json}`, repeat. Tools: `search_profile(query,k)` via LM Studio nomic against `index_lms_nomic.npz`; `get_datetime()`; `calculator(expression)` via an `ast`-restricted evaluator (never `eval`); `draft_message(recipient_role, intent)` returns Voice rules + 2 samples so hermes3 drafts in voice, with a "Polish with Stheno" button. Unknown tool → error message back to the model. Trace in an accordion.
- **See**: resize to ≤1024 px, base64 in `images`, qwen3.5 `think:false`, temp 0.7, "Describe this image factually in 5 sentences." → stop qwen3.5 → Stheno reacts with voice prefix + "You just saw: <description>" + retrieval on the description.
- **Digest**: once per profile sha with qwen3:8b, `think:false`, `keep_alive: 0`, LM Studio unloaded first.
- **Status**: `/api/ps`, `/api/tags`, LM Studio `/api/v0/models` and `/v1/models`, `nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader`, a Models table (every registry model with its job and loaded / on disk state), digest state (chars, builder qwen3:8b, sha, fresh/stale), per-index staleness, telemetry table, buttons Free GPU / Warm tab / Refresh / Rebuild index + digest / Rebuild digest (force), `gr.Timer` 5 s.

### Indexing

Split on `^# ` sections then `^## ` chunks; sections without `##` are one chunk each (split on blank lines above 1500 chars). Chunk record `{id:"Decisions/D-03", section, subsection, title, text}`; Decisions also parsed into fields. **Eval is parsed to `[{qid, question, answer}]` and excluded from the index.** Batched embeds of 32; L2-normalised float32 in `data\index_<key>.npz` (`vectors`, `ids`, `embedder`) plus `data\chunks.json` with the profile sha (stale → rebuild prompt in UI). Prefixes: nomic `search_document:` / `search_query:`; embeddinggemma `title: {title} | text: {text}` / `task: search result | query: {q}`. Search = `V @ q`, argpartition top-k.

### Eval tab

- Voice bake-off: 6 candidates (Stheno Q4, Stheno Q8, llama3.1, qwen2.5, hermes3, qwen3-8b-8k) × 5 Eval questions, candidate-outer loop so each model loads once, retrieval precomputed with nomic. Identical voice prefix + chunks for all; Qwen candidates `think:false`, Stheno samplers for Stheno, temp 0.7 for others. llama3.1 judges anonymised responses against the gold answer and Voice rules with `format` rubric `{factual_agreement 1-5, voice_fidelity 1-5, no_roleplay_artifacts 1-5, overall 1-5, note}`; qwen2.5 as second judge; Claude in a parallel thread when the key exists.
- Retrieval bake-off: recall@1/3/5, MRR, embed latency for nomic-Ollama, embeddinggemma, nomic-LM-Studio; ground truth = highest lexical-overlap chunk with the gold answer, or a `Sources:` line if present.
- Estimated 5 min single judge, 6.5 min with both. Written to `data\eval_results.json` after every call (keyed by sha, candidate, qid, judge) so runs resume and the demo replays instantly; UI shows cached table plus "Re-run (~6 min)" and "Live: one candidate × one question (~15 s)".

### Risks

- Swap latency mid-demo: pre-warm, keep_alive, heartbeat, demo order Ask → Decide → Act → See → Eval (replay), Status open in a second window, Free GPU button.
- Stheno roleplay drift: firm system prompt, post-processing, checker as visible safety net; Q8 always gets a system message.
- Qwen empty replies: `think:false` on every call to qwen3-8b-8k, qwen3:8b, qwen3.5; `num_predict` set; one retry.
- Port 7860 collision: default 7861; `app.py` probes 7861..7870 itself before launch (Gradio 6 scans only when no `server_port` is pinned, otherwise it raises `OSError: Cannot find empty port in range`).
- Swap latency with the Q8 toggle: the Ask handler tells the manager which voice is in use (`set_tab_model("ask", "stheno_q8")`), so the heartbeat and the tab pre-warm re-warm Q8 instead of evicting it for Q4. Selecting Status never changes the active tab (it is meant to stay open in a second window); Eval clears it; Free GPU clears it.
- Never print or store the Anthropic key; `PYTHONUTF8=1` for non-ASCII profile text; pin `gradio>=5` for Python 3.13.

## 5. Build stages and verification (PowerShell 5.1)

0. **Env and docs**: `pip install gradio anthropic`; write `scripts\check_servers.ps1` (`curl.exe -s http://127.0.0.1:1234/api/v0/models`, `curl.exe -s http://127.0.0.1:11434/api/tags`, `nvidia-smi`). Pass = both JSON bodies, GPU ≤ 200 MiB. Also update README.md and CLAUDE.md with the audit facts they lack: the five extra `OLLAMA_*` user env vars, that the app overrides `OLLAMA_CONTEXT_LENGTH` (so plain models need per-request `num_ctx`), the LM Studio nomic embedder, and replace the CLAUDE.md "No project code exists yet" open item with a pointer to `docs\PLAN.md`.
1. **Profile + index**: `data\twin_profile.md` if present else the example; `python -m twin.index --build all --digest`. Verify `--search "how do I decide about job offers"` prints top-3 with section ids; `np.load('data/index_nomic.npz')['vectors'].shape` is `(N, 768)`; `data\digest.md` exists; `curl.exe -s http://127.0.0.1:11434/api/ps` → `{"models":[]}`.
2. **MVP: Status + Ask + Decide**: `python app.py --port 7861` serves `http://127.0.0.1:7861`; after an Ask turn `/api/ps` shows only a small model and `lms ps` shows Stheno; after a Decide turn `ollama ps` shows qwen3-8b-8k 100% GPU ctx 8192 and `lms ps` / `GET /api/v0/models` shows no chat model loaded (the 0.27 GB `text-embedding-nomic-embed-text-v1.5` embedder may stay: see the Decide deviation in section 4). Evidence per check is recorded in `docs/EVIDENCE.md`.
3. **Ask extras**: Q8 toggle, rewrite, checker, heartbeat, pre-warm. Follow-up "and why?" shows a rewritten standalone query in the trace; checker badge renders; after Q8 `ollama ps` shows the 67% GPU split (expected).
4. **Act**: "What time is it and what's 17% of 240?" → trace shows get_datetime and calculator; "Draft a message to my manager asking for Friday off" → draft_message then search_profile, with `lms ps` showing the embedder and `ollama ps` still showing hermes3.
5. **See**: upload a photo; `ollama ps` shows qwen3.5:4b-q8_0 100% GPU ctx 8192; reaction is first person, no narration.
6. **Eval**: `python -m twin.pipelines.evals --run`; `data\eval_results.json` populated; UI replays with `/api/ps` empty.

CLI paths: `$env:LOCALAPPDATA\Programs\Ollama\ollama.exe`, `$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe`.

## 6. Execution: Fable 5.1, ultracode workflows

**Model.** Every workflow agent inherits the session model (no `model` override). Design, review, and live-verification agents keep the session effort; mechanical stages (scaffolding, fixes) use `effort: 'low'`.

**Ultracode.** The build runs as three Workflow scripts in sequence; read each result before launching the next so a failed phase never cascades. Each script stays under about 15 agents. Two hard rules for every agent:

- **One GPU.** Only one agent per workflow may call the model servers, and it runs alone in its own stage. All other agents test with mocked clients (pure Python, no network).
- **No shared files.** Not a git repo, so no worktree isolation; parallel agents get disjoint file lists.

**Standing instruction: do not stop until everything is built.** Run all three workflows back to back without pausing for confirmation, fix failures and resume the failed phase (`resumeFromRunId` caches passed agents), and end the turn only when every stage in section 5 has passing evidence or is blocked on something only the user can supply (the real profile file, the Anthropic key). List blocked items explicitly; never drop them silently.

### Workflow 1: foundation (5 agents)

```
phase Scaffold   1 agent, effort low: requirements.txt, twin\config.py, clients.py, telemetry.py, gpu.py,
                 profile.py, prompts.py, index.py, scripts\*.ps1, docs\PLAN.md, docs\opus_profile_prompt.md,
                 data\twin_profile.example.md (synthetic, full schema, 15 decisions, 20 eval Q/A),
                 README.md and CLAUDE.md updates from stage 0
phase Verify     parallel, 3 lenses, each returns {findings[]} via schema:
                   - rules reviewer: every request shape against section 1 (model names, think:false,
                     num_ctx on every Ollama call, system message on Q8, keep_alive, no eval())
                   - parser tester: runs profile.py on the example file, checks chunk ids, Eval excluded,
                     decisions parsed into fields
                   - live smoke (the only GPU agent): pip install, check_servers.ps1,
                     python -m twin.index --build all --digest, --search, /api/ps empty afterwards
phase Fix        1 agent, effort low, only if findings non-empty; reruns the parser test
```

### Workflow 2: pipelines (10 to 15 agents)

`pipeline()` over `[ask, decide, act, see, evals+digest]`, no barriers:

```
stage 1  implement module + tests\test_<module>.py with a mocked client asserting exact request bodies
         (think:false, format schema, tools list, images base64, num_ctx, keep_alive)
stage 2  adversarial reviewer prompted to refute: "find the request that returns empty, loads the wrong
         model, or leaves the GPU full"; returns {issues[]}
stage 3  fix agent, effort low, only when issues non-empty; reruns that module's tests
```

### Workflow 3: integrate and verify live (4 agents)

```
phase Integrate  1 agent: app.py with six tabs, tab-select pre-warm hooks, Status timer, --port 7861
phase Live       1 agent (GPU): runs stages 2 to 6 from section 5 in order against the real servers,
                 records each check's actual output, fixes small bugs in place, returns {stage, passed, evidence}[]
phase Critic     parallel, 2 agents: completeness critic ("which model has no visible job, which
                 verification step has no evidence") and a correctness reviewer; both return findings
phase Fix        1 agent, effort low, applies confirmed findings, reruns tests\
```

After workflow 3: run the app once, screenshot each tab, report the per-stage evidence table. If `data\twin_profile.md` arrives later: `python -m twin.index --build all --digest` re-indexes, and the Eval tab's re-run produces real scores.

## Post-build additions (2026-09-13/14)

Things that exist in the repo but are not listed above (the sections above are left as written):

- `twin/pipelines/voice.py`: the shared voice call (Stheno Q4 on LM Studio, `llama3.2:3b` when LM Studio is down, one retry on an empty reply) used by Decide "say it" and Act "polish"; Ask and See keep their own streaming flows.
- `scripts/screenshot_tabs.ps1`: headless `chrome.exe` screenshots of every tab (the browser extension cannot reach 127.0.0.1).
- `scripts/dev/`: dev scratch scripts, logs and screenshots from the live verification (`live_drive.py`, `ps_poll.ps1`, `view_api_baseline.json`, `shots/`, `old/app_monolith.py`), so `data/` holds only the plan's artifacts.
- `requirements.txt`: `pillow` (the See tab's test photo) and `pytest` (the mocked suite: `python -m pytest tests -q -p no:cacheprovider`).
- Everything after phase 1 (profile v2 and `--lint`, interview transcript and redaction, expert reflections, the demographic/persona/interview conditions, item bank, safeguards, the Gradio 6 UI split and restyle) is one plan: `docs/PLAN_UNIFIED.md`, which supersedes `docs/PLAN2.md` and `docs/PLAN3_UI.md`.
