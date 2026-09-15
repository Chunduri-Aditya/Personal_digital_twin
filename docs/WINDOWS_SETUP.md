# Personal_digital_twin: local model setup

Set up on 2026-09-13 on this laptop: Windows 11, RTX 2070 (8 GB VRAM), 32 GB RAM.
Everything runs on this laptop only. Both servers listen on `127.0.0.1`, so nothing is reachable from the network.

**Setting up on another machine?** The model weights aren't in this repository. `docs/MODEL_SETUP.md` has the download commands, sizes and server settings for Windows, macOS/Linux and Docker.

## Models

| Role | Model | Runtime | Name to request | Endpoint |
|---|---|---|---|---|
| Persona chat voice (fast) | L3-8B-Stheno-v3.2 Q4_K_M | LM Studio | `l3-8b-stheno-v3.2` | `http://127.0.0.1:1234/v1` (OpenAI compatible) |
| Persona chat voice (higher precision, slow) | L3-8B-Stheno-v3.2 Q8_0 | Ollama | `fluffy/l3-8b-stheno-v3.2:q8_0` | `http://127.0.0.1:11434/api/chat` (or `/v1`) |
| Twin decisions (B1/B2), structured output | qwen3:8b with context fixed at 8192 | Ollama | `qwen3-8b-8k` | `http://127.0.0.1:11434/api/chat` (or `/v1`) |
| Retrieval embeddings (768 dims) | nomic-embed-text | Ollama | `nomic-embed-text` | `http://127.0.0.1:11434/api/embed` |
| Eval ceiling reference (one run) | Claude Sonnet 5 / Opus 5 | Anthropic API | `claude-sonnet-5` / `claude-opus-5` | Anthropic API, needs `ANTHROPIC_API_KEY` |

Measured on 2026-09-13, each model with the GPU otherwise empty:

| Model | Cold start (includes load) | Warm | GPU |
|---|---|---|---|
| Stheno 8B Q4_K_M (LM Studio) | about 4 to 5 s | 0.1 to 0.6 s for a short reply, about 49 tokens/s | 100%, about 5.6 GB |
| Stheno 8B Q8_0 (Ollama) | about 13 to 15 s | 8 to 11 tokens/s | only 67% on the GPU, 9.3 GB total, context 8192 |
| `qwen3-8b-8k` (Ollama) | 4.6 s | 50.9 tokens/s | 100%, 5.6 GB, context 8192 |
| `qwen3:8b` (Ollama app default) | 11.7 s | 9.9 tokens/s | only 71% on the GPU, 8.8 GB, context 40960 |
| nomic-embed-text | 1.3 to 1.8 s | | small |

Stheno Q4_K_M model file SHA256: `8e98c1953f9c04e060fd9640bbe866685c844363a2360f09099b79c6c9195fc4` (4920734240 bytes).

## Important details

- **Stheno Q4_K_M or Q8_0?** The Q8_0 weights (about 8 GB) are bigger than the 8 GB GPU, so a third of the model runs on the CPU and it is about 5× slower. Use Q4_K_M for live chat. Use Q8_0 when you want the higher-precision weights and can wait.
- **Always send your own system prompt to the Q8_0.** `fluffy/l3-8b-stheno-v3.2:q8_0` has a built-in default system prompt, `Write {{char}}'s next reply in this fictional roleplay with {{user}}.` Ollama doesn't fill in `{{char}}`/`{{user}}`, and this default is used only when a request has no system message, so your persona system message replaces it. The model uses the correct Llama 3 Instruct prompt format.
- **Use `qwen3-8b-8k`, not `qwen3:8b`.** The Ollama app sets its default context to 65536 (`OLLAMA_CONTEXT_LENGTH`), so plain `qwen3:8b` loads with its 40960 maximum. That doesn't fit in 8 GB, runs partly on the CPU, and is about 5× slower. `qwen3-8b-8k` reuses the same weights (only 286 bytes extra) with `num_ctx 8192` saved in the model, so every client gets 8192 without sending anything. Its recipe is `modelfiles\qwen3-8b-8k.Modelfile`.
- **Turn off Qwen3 thinking for fast answers.** Without this, thinking can use up all of `max_tokens` and the reply text comes back **empty**.
  - Native `/api/chat`: send `"think": false`.
  - OpenAI-style `/v1/chat/completions`: send `"reasoning_effort": "none"`. `think` is ignored on `/v1`.
- **For structured output** on `/api/chat`, pass a JSON schema in `"format"`.
- **Request the LM Studio Stheno as `l3-8b-stheno-v3.2`, not `stheno-8b`.** The name `stheno-8b` only exists while the model is loaded under that identifier. When it is unloaded, requests for it fail with HTTP 400. Requesting the model key loads it on demand, which takes about 4 s.
- **Stheno samplers** from its model card (both quants): temperature 1.12 to 1.22, min_p 0.075, top_k 50, repeat penalty 1.1.

## GPU sharing (8 GB)

Only one of these fits fully on the GPU at a time. Each one unloads itself when idle:

- **Ollama models** (Qwen, Stheno Q8_0) unload after 5 idle minutes (Ollama default). When you request a different Ollama model, Ollama swaps the old one out as needed.
- **LM Studio's Stheno Q4_K_M** unloads after 10 idle minutes (LM Studio on-demand unload time set to 600 s).

LM Studio and Ollama don't coordinate. When both have a model loaded, the GPU is almost full (measured 7880 of 8192 MiB with Qwen at context 8192 plus Stheno Q4_K_M), and part of the second model runs on the CPU. Short replies stay fast (about 49 tokens/s), but long replies can slow down. To free the GPU right away:

```powershell
$ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
& $ollama stop qwen3-8b-8k
& $ollama stop fluffy/l3-8b-stheno-v3.2:q8_0
& "$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe" unload --all
```

## Folder layout

```
Personal_digital_twin\
  docs/WINDOWS_SETUP.md
  modelfiles\
    qwen3-8b-8k.Modelfile   recipe for qwen3-8b-8k
  models\
    lmstudio\   LM Studio models folder (setting downloadsFolder points here)
      bartowski\L3-8B-Stheno-v3.2-GGUF\L3-8B-Stheno-v3.2-Q4_K_M.gguf
    ollama\     Ollama models: blobs\ and manifests\
                (fluffy/l3-8b-stheno-v3.2:q8_0, qwen3:8b, qwen3-8b-8k, nomic-embed-text,
                 hermes3:8b (added by you, role not set up),
                 plus older ones: llama3.1:8b, qwen2.5:7b, qwen3.5:4b-q8_0,
                 llama3.2:1b, llama3.2:3b, embeddinggemma)
```

**Don't delete `C:\Users\Adity\.ollama\models`.** It is a junction (a folder link) that points to `Personal_digital_twin\models\ollama`. The Ollama desktop app ignores `OLLAMA_MODELS` and always uses its own saved folder, so the link is what makes it find these models at login.

## Start and stop

Both are set to start at login:

- **Ollama:** `Ollama.lnk` in the Startup folder. This was checked by starting the app the same way login does; all models listed.
- **LM Studio:** "run server on login", ticked in the app settings (Ctrl+,). This hasn't been checked with a reboot yet.

To start them manually:

```powershell
$lms = "$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe"
& $lms server start --port 1234 --bind 127.0.0.1
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
```

To rebuild `qwen3-8b-8k` (for example after `ollama pull qwen3:8b` updates it):

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" create qwen3-8b-8k -f "$env:USERPROFILE\Personal_digital_twin\modelfiles\qwen3-8b-8k.Modelfile"
```

## Quick checks

```powershell
# LM Studio: list models
curl.exe -s http://127.0.0.1:1234/v1/models

# Stheno Q4_K_M chat (LM Studio)
$b = @{ model = "l3-8b-stheno-v3.2"; messages = @(@{ role = "user"; content = "Long night?" }); max_tokens = 40 } | ConvertTo-Json -Depth 5
(Invoke-RestMethod -Method Post http://127.0.0.1:1234/v1/chat/completions -ContentType "application/json" -Body $b).choices[0].message.content

# Stheno Q8_0 chat (Ollama), always with a system prompt
$b = @{ model = "fluffy/l3-8b-stheno-v3.2:q8_0"; stream = $false; messages = @(@{ role = "system"; content = "You are Dana, a tired night shift nurse. Answer in one short sentence." }, @{ role = "user"; content = "Long night?" }); options = @{ temperature = 1.15; min_p = 0.075; top_k = 50; repeat_penalty = 1.1 } } | ConvertTo-Json -Depth 5
(Invoke-RestMethod -Method Post http://127.0.0.1:11434/api/chat -ContentType "application/json" -Body $b).message.content

# Ollama: list models
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list

# Qwen, native API, no thinking (expect "100% GPU" and context 8192 in `ollama ps`)
$b = @{ model = "qwen3-8b-8k"; stream = $false; think = $false; messages = @(@{ role = "user"; content = "Say hi in five words." }) } | ConvertTo-Json -Depth 5
(Invoke-RestMethod -Method Post http://127.0.0.1:11434/api/chat -ContentType "application/json" -Body $b).message.content
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" ps

# Qwen, OpenAI-style API, no thinking
$b = @{ model = "qwen3-8b-8k"; reasoning_effort = "none"; messages = @(@{ role = "user"; content = "Say hi in five words." }) } | ConvertTo-Json -Depth 5
(Invoke-RestMethod -Method Post http://127.0.0.1:11434/v1/chat/completions -ContentType "application/json" -Body $b).choices[0].message.content

# Embedding size (expect 768)
(Invoke-RestMethod -Method Post http://127.0.0.1:11434/api/embed -ContentType "application/json" -Body '{"model":"nomic-embed-text","input":"hello"}').embeddings[0].Count
```

Python (OpenAI-compatible clients work for both local servers):

```python
from openai import OpenAI
stheno = OpenAI(base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")  # auth is off, any string works
ollama = OpenAI(base_url="http://127.0.0.1:11434/v1", api_key="ollama")

reply = ollama.chat.completions.create(
    model="qwen3-8b-8k",
    reasoning_effort="none",  # without this, thinking can eat max_tokens and content is empty
    messages=[{"role": "user", "content": "Say hi in five words."}],
)
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ollama list` is empty | The `.ollama\models` junction is missing | Recreate it: `New-Item -ItemType Junction -Path "$env:USERPROFILE\.ollama\models" -Target "$env:USERPROFILE\Personal_digital_twin\models\ollama"`, then restart Ollama |
| Stheno Q8_0 slow (about 8 to 11 tokens/s) | Expected: it doesn't fit in 8 GB and a third runs on the CPU | Use the Q4_K_M in LM Studio for live chat |
| Stheno Q8_0 replies mention `{{char}}` or ignore the persona | Request had no system message, so the built-in default was used | Always send the persona as the system message |
| Qwen slow, `ollama ps` shows CPU/GPU split and context 40960 | Requested `qwen3:8b` instead of `qwen3-8b-8k` | Request `qwen3-8b-8k` |
| Qwen reply text empty, `finish_reason` = `length` | Thinking used up `max_tokens` | Send `reasoning_effort: "none"` (`/v1`) or `think: false` (`/api/chat`) |
| HTTP 400 when requesting `stheno-8b` | That identifier only exists while loaded | Request `l3-8b-stheno-v3.2` instead |
| Connection refused on port 1234 | LM Studio server not running | Run the `lms server start` line above |
| Slow replies with both apps in use | LM Studio and Ollama both have a model loaded, so one is partly on the CPU | Wait for the idle unload, or free the GPU with the commands above |
| `401` from LM Studio | "Require Authentication" was turned on | Turn it off in Developer, then Server Settings (local-only setup) |

## Extra facts from the 2026-09-13 audit

- Six `OLLAMA_*` user environment variables are set: `OLLAMA_MODELS=C:/Users/Adity/Personal_digital_twin/models/ollama`, `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_MAX_LOADED_MODELS=1`.
- The Ollama desktop app honours all of them **except** `OLLAMA_MODELS` (it uses its own saved folder via the junction) and `OLLAMA_CONTEXT_LENGTH` (it forces 65536). So every plain Ollama model (anything other than `qwen3-8b-8k`, which has `num_ctx` baked in) needs a per-request `options.num_ctx` (8192 for 8B models, 4096 for llama3.2, 2048 for embedders) or it loads at 65536 context and spills to the CPU.
- LM Studio also serves an embedder, `text-embedding-nomic-embed-text-v1.5` (768 dims) at `POST /v1/embeddings`. `GET http://127.0.0.1:1234/api/v0/models` lists every LM Studio model with its `state` (`loaded` / `not-loaded`) without triggering a load.
- The twin app lives in `app.py` with its code in the `twin\` package; the build plan is `docs\PLAN.md` and the module API is `docs\CONTRACTS.md`. Run: `$env:PYTHONUTF8=1; python app.py --port 7861`.

## Run

From the project root (Windows PowerShell 5.1), with both model servers up:

```powershell
$env:PYTHONUTF8=1; $env:GRADIO_ANALYTICS_ENABLED='False'; python app.py --port 7861
```

On macOS or Linux, `./start.sh` does the same from a fresh unzip:

- It creates `.venv` and installs `requirements.txt`, again only when that file changes. A broken `.venv` is recreated.
- It sets `PYTHONUTF8` and `GRADIO_ANALYTICS_ENABLED`.
- It checks Ollama (127.0.0.1:11434) and LM Studio (127.0.0.1:1234). When neither answers, it sets `TWIN_NO_WARM=1`.
- It launches `app.py`.

Flags: `--port N`, `--no-warm`, `--warm`, `--test` (runs pytest first), `--open`, `--dry-run` and `--help`. If the unzip lost the executable bit, use `chmod +x start.sh` or `bash start.sh`.

It was reviewed but not yet run: this Windows laptop has no bash. See `docs/REPLICATE_ON_MAC.md` for the full Mac setup.

Then open `http://127.0.0.1:7861` (the app binds to 127.0.0.1 only; `--host` and `--port` are the only flags; when `--port` is busy the next nine ports are probed and the chosen URL is printed). Booting loads no model: each tab pre-warms its own model when you select it, and a heartbeat re-warms the active tab's model every 4 minutes. `?tab=<onboarding|ask|decide|act|see|items|eval|status>` opens a tab directly (for example `http://127.0.0.1:7861/?tab=status` in a second window during a demo); `__theme=dark` or `__theme=light` picks the theme and `nomotion=1` turns off CSS transitions (screenshots). `scripts\screenshot_tabs.ps1 -Port <p> [-Theme light|dark] [-Width 1440] [-Tabs ask,status] [-VirtualTimeMs 20000] [-OutDir scripts\dev\shots]` captures one headless-Chrome screenshot per tab as `<OutDir>\<theme>_<width>_<tab>.png` while the app is running; opening a model tab that way fires its pre-warm unless the app runs with `TWIN_NO_WARM=1`.

| Tab | What it does | Model(s) |
|---|---|---|
| Ask | Chat as the twin: router, follow-up rewrite, retrieval, streamed reply; Q8 toggle, optional consistency check, trace accordion | llama3.2:1b, llama3.2:3b, nomic, Stheno Q4 (or Q8), qwen2.5:7b |
| Decide | B1 "Would I do it?" and B2 "A or B?" as JSON with reasons and cited decisions; "Say it in my voice" | qwen3-8b-8k, then Stheno Q4 on click |
| Act | Tool-calling agent: search_profile, get_datetime, calculator, draft_message; "Polish with Stheno" | hermes3:8b, LM Studio nomic, Stheno Q4 |
| See | Upload an image: factual description, then a reaction in the twin's voice | qwen3.5:4b-q8_0, Stheno Q4 |
| Eval | Cached voice and retrieval bake-off tables (replay, no model load); re-run buttons; live one-candidate check | all six candidates, llama3.1 and qwen2.5 judges |
| Status | `ollama ps`, LM Studio model states, nvidia-smi, active tab, heartbeat, telemetry; Free GPU, Warm, Refresh, Rebuild index + digest; refreshes every 5 s | none (GETs only) |

Every button has an `api_name` (listed in the docstring of `app.py`), so `gradio_client` can drive the app: `Client("http://127.0.0.1:7861").view_api()`.

The Onboarding tab (four-step walkthrough with file checks, no model) opens first while `data\twin_profile.md` is missing. The Items tab holds the self-report form, saves answer waves, and has "Run twin" (qwen3-8b-8k, Stheno Q4, the two judges) and "Score" (no model); both rewrite `data\items\scores.json`.

### How the UI is styled

- **Token sheet.** `docs\design\tokens.md` when a Claude Design export exists, else `docs\design\tokens.default.md`. It is a `| token | light | dark | note |` table plus `font-body:`, `font-serif:`, `font-mono:`, `radius:` and `default_theme:` lines. Its section 7 is the frame contract: the CSS variables and shared classes every tab uses.
- **`twin\ui\theme.py`** turns the sheet into the Gradio theme (`TwinTheme`) and re-declares every colour, font, radius and shadow `--twin-*` variable from it, so a new sheet restyles the app without CSS edits. `css_text()` joins `static\twin.css` and then `static\tabs\*.css` in sorted order; `app.py` passes both to `demo.launch`. `python -m twin.ui.theme` prints the contrast table and exits 1 when a body-text pair is under 4.5:1.
- **`static\twin.css`** holds the default token values (pinned to the default sheet by `tests\test_theme.py`), the spacing, type and motion scales, base rules, and the shared classes (`twin-panel`, `twin-card`, `twin-result`, `twin-actions`, `twin-quiet`, `twin-caution`, `twin-table`, `trace`, `quote-card`, `verdict-card` and the rest), all written under `#twin-tabs`.
- **`static\tabs\frame.css`** styles the frame: masthead and monogram (`#twin-masthead`, `#twin-avatar`, `#twin-header`), `#gpu-note`, the `#status-strip` sidebar and the `#twin-tabs` strip. **`static\tabs\<tab>.css`** (onboarding, ask, decide, act, see, items, eval, status) styles one tab. Every selector in a tab file starts with `#tab-<id>`, colours come only from `var(--twin-*)`, and no file names a Gradio-internal class (`svelte-`, `.block`, `.gradio-container`, `.prose`, `.wrap`, `.gr-`). `tests\test_theme.py` enforces all three. The full rules and per-tab ids are in `docs\CONTRACTS.md`, section "UI styling".
- **Theme choice.** `?__theme=dark` or `?__theme=light` per page. `$env:TWIN_THEME='dark'` (or `light`) forces the theme when the URL has no `__theme`.
- **Checks without the GPU.** `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\finish\ui_check.ps1 -Port 7871 -OutDir scripts\dev\shots\x -Themes light,dark -Narrow -Measure -ViewApi` does the following, then always stops the app:
  - boots the app with `TWIN_NO_WARM=1` on a UI port (7871-7879)
  - screenshots every tab through `scripts\screenshot_tabs.ps1`
  - shoots Ask at a true 400 px and requires `scrollWidth` 400 or less
  - checks `view_api` against the baseline
  - confirms `/api/ps` is unchanged

  `scripts\screenshot_tabs.ps1` alone (see above) needs an app that is already running.

## Settings changed during setup

- LM Studio `C:\Users\Adity\.lmstudio\settings.json`: `downloadsFolder` changed to `Personal_digital_twin\models\lmstudio`, and `jitModelTTL.ttlSeconds` from 3600 to 600.
- User environment variable `OLLAMA_MODELS` set to `Personal_digital_twin\models\ollama`. The Ollama app ignores it, but it's used if you run `ollama serve` by hand.
- Junction `C:\Users\Adity\.ollama\models` points to `Personal_digital_twin\models\ollama`.
- Ollama model `qwen3-8b-8k` created from `modelfiles\qwen3-8b-8k.Modelfile`.
- Ollama model `fluffy/l3-8b-stheno-v3.2:q8_0` pulled. A second Q8_0 copy (`hf.co/bartowski/L3-8B-Stheno-v3.2-GGUF:Q8_0`) was pulled and then removed, because Ollama gave it the ChatML prompt format instead of Llama 3.
- Ollama upgraded to 0.34.0; LM Studio 0.4.24 installed.
