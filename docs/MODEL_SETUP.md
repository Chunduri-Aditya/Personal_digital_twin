# Model setup

This project needs two local model servers, **Ollama** and **LM Studio**, both listening on `127.0.0.1` only
(nothing is reachable from the network, and neither server has authentication). The model weights are **not in
this repository** (about 42 GB in total); you download them with the commands below. `app.py`, `./start.sh` and
the Docker image all work with neither server running (`TWIN_NO_WARM=1` mode: every tab renders, cached results
still show, but anything that needs a model shows an error until a server is up), so treat this guide as what
you need for the full, live twin, not as a hard prerequisite to open the app.

What has been run and what hasn't:

| Path | Status |
|---|---|
| Windows 11, native (section 2) | Verified 2026-09-13 on an RTX 2070 (8 GB VRAM), 32 GB RAM, Ollama 0.34.0, LM Studio 0.4.24 |
| Docker Desktop on Windows (section 4) | Verified 2026-09-15: image build, app boot, container reaching both host servers, GPU visible in containers |
| macOS (section 3) | Partly verified 2026-09-15 on an M3 Pro (18 GB unified memory), Ollama 0.34.0, LM Studio 0.4.24. Run live: `./start.sh` from a cold boot (it starts both servers), an index + digest rebuild across all three embedders, and the demo set end to end through Ask, Decide and Act — `l3-8b-stheno-v3.2`, `qwen3-8b-8k`, `hermes3:8b`, `llama3.2:1b`, `nomic-embed-text`, `text-embedding-nomic-embed-text-v1.5`, plus `qwen3:8b` and `embeddinggemma` during the build. **Not exercised:** the section 3 download commands (the models were already installed), the See tab's `qwen3.5:4b-q8_0`, and live Eval/Items judge runs (`llama3.1:8b`, `qwen2.5:7b` are installed, but the Eval tab was read from cache) |
| Linux (section 3) | **Not run.** Written from Ollama's and LM Studio's own docs, like `docs/REPLICATE_ON_MAC.md`. If you run it, please correct this file with what actually happened |

Run every command below from the project root (the folder that holds `app.py`).

## 1. The models

Every model the app can call, from the registry in `twin/config.py` (`MODELS`). The **demo set** is what the
eight tabs use in normal use. The **build**, **eval** and **optional** models are only needed for index builds,
the Q8 voice toggle and the Eval tab's bake-off and judge re-runs, so you can add them later.

| Role | Request this name | Runtime | Download | Needed for |
|---|---|---|---|---|
| Persona chat voice (fast) | `l3-8b-stheno-v3.2` (Q4_K_M) | LM Studio | 4.9 GB | Ask, Decide "Say it", See reaction, Act polish, Items open items: **demo set** |
| Retrieval embeddings, LM Studio side (768-dim) | `text-embedding-nomic-embed-text-v1.5` | LM Studio | 84 MB (usually bundled) | index `lms_nomic`: Act `search_profile`, Decide, Items: **demo set** |
| Twin decisions, structured JSON | `qwen3-8b-8k` | Ollama | none (reuses `qwen3:8b`) | Decide B1/B2, Items closed items: **demo set** |
| Base of `qwen3-8b-8k`; profile digest and reflections | `qwen3:8b` | Ollama | 5.2 GB | required to create `qwen3-8b-8k`; build-time digest: **demo set** |
| Retrieval embeddings (768-dim) | `nomic-embed-text` | Ollama | 274 MB | index `nomic`: Ask, See, Eval: **demo set** |
| Act tool agent | `hermes3:8b` | Ollama | 4.7 GB | Act's tool-calling loop: **demo set** |
| Follow-up rewrite, fallback voice | `llama3.2:3b` | Ollama | 2.0 GB | Ask: **demo set** |
| Router (intent JSON) | `llama3.2:1b` | Ollama | 1.3 GB | Ask: **demo set** |
| Image description | `qwen3.5:4b-q8_0` | Ollama | 5.3 GB | See: **demo set** |
| Persona chat voice (Q8_0, higher precision, slow) | `fluffy/l3-8b-stheno-v3.2:q8_0` | Ollama | 8.5 GB | Ask's Q8 toggle, Eval candidate: **eval** |
| Second retrieval index (bake-off) | `embeddinggemma:300m-qat-q4_0` | Ollama | 238 MB | index `gemma`: retrieval bake-off: **eval** |
| Consistency checker, second judge | `qwen2.5:7b` | Ollama | 4.7 GB | Ask checker, Eval judge, Items judge: **eval** |
| Primary judge | `llama3.1:8b` | Ollama | 4.9 GB | Eval judge, Items judge: **eval** |
| Eval ceiling reference (one run) | `claude-sonnet-5` / `claude-opus-5` | Anthropic API | none | Eval tab, only when `ANTHROPIC_API_KEY` is set: **optional** |

Disk space: about **24 GB** for the demo set, about **18 GB** more for the eval models, about **42 GB** for all of
them. Sizes are what `ollama list` and the downloaded GGUF files showed on the Windows laptop.

The app finds models only by these exact names. A model pulled or imported under a different name is reported as
`not pulled` / `not listed` on the Status tab, and every call to it fails until the name matches.

## 2. Windows (verified)

`docs/WINDOWS_SETUP.md` has the full record of the Windows laptop: measured cold-start and warm timings, the troubleshooting
table, and the `.ollama\models` junction that laptop uses to keep the weights inside the project's `models\`
folder. You don't need that junction: with default install locations, Ollama and LM Studio keep their models in
their own folders, and this repository's `models\` folder stays empty.

### 2.1 Ollama

Install from https://ollama.com (the desktop app starts the server on `127.0.0.1:11434` and at login).

```powershell
$ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
# demo set
foreach ($m in "nomic-embed-text","llama3.2:1b","llama3.2:3b","qwen3:8b","hermes3:8b","qwen3.5:4b-q8_0") { & $ollama pull $m }
& $ollama create qwen3-8b-8k -f modelfiles\qwen3-8b-8k.Modelfile
# eval extras
foreach ($m in "llama3.1:8b","qwen2.5:7b","embeddinggemma:300m-qat-q4_0","fluffy/l3-8b-stheno-v3.2:q8_0") { & $ollama pull $m }
& $ollama list
```

`modelfiles\qwen3-8b-8k.Modelfile` is `FROM qwen3:8b` plus `PARAMETER num_ctx 8192`, so pull `qwen3:8b` first.
Rebuild `qwen3-8b-8k` the same way after an `ollama pull qwen3:8b` updates the base.

Server settings the Windows numbers were measured with (user environment variables; quit and reopen the Ollama app
after setting them). They aren't required, but they keep an 8 GB GPU to one model at a time:

```powershell
foreach ($kv in @{ OLLAMA_MAX_LOADED_MODELS = "1"; OLLAMA_NUM_PARALLEL = "1"; OLLAMA_FLASH_ATTENTION = "1"; OLLAMA_KV_CACHE_TYPE = "q8_0" }.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, "User")
}
```

The Ollama desktop app ignores `OLLAMA_CONTEXT_LENGTH` (it forces 65536) and `OLLAMA_MODELS`. The app doesn't
depend on either: it sends a fixed `options.num_ctx` and `keep_alive` per model on every Ollama call
(`twin/clients.py`). Only your own manual requests need to send `num_ctx` (section 5).

### 2.2 LM Studio

Install from https://lmstudio.ai. Then:

1. In the app, search for and download **`bartowski/L3-8B-Stheno-v3.2-GGUF`**, quant **Q4_K_M**
   (`L3-8B-Stheno-v3.2-Q4_K_M.gguf`, 4,920,734,240 bytes, SHA256
   `8e98c1953f9c04e060fd9640bbe866685c844363a2360f09099b79c6c9195fc4`).
2. Set that model's context length to **8192** in its load settings. The app sends no context length to LM Studio.
3. Check that the embedder `text-embedding-nomic-embed-text-v1.5` is listed (`lms ls`, or the My Models page).
   It shipped with LM Studio on the Windows laptop. If it's missing, import a `nomic-embed-text-v1.5` GGUF (the
   macOS block in section 3 has the download link).
4. Optional, as on the Windows laptop: in Developer settings, set the idle auto-unload (JIT model TTL) to 600 s
   and turn on "run server on login". Leave "Require Authentication" off.
5. Start the server:

```powershell
$lms = "$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe"   # lms isn't on PATH by default
& $lms server start --port 1234 --bind 127.0.0.1
curl.exe -s http://127.0.0.1:1234/v1/models   # must list l3-8b-stheno-v3.2 and text-embedding-nomic-embed-text-v1.5
```

Some `lms` commands (for example `lms import`) show a one-time Y/n prompt even with `--yes`; pipe `y` into them
or they hang.

### 2.3 Run

Check both servers with `powershell -File scripts\check_servers.ps1` (section 6), then:

```powershell
$env:PYTHONUTF8=1; $env:GRADIO_ANALYTICS_ENABLED='False'; python app.py --port 7861
```

## 3. macOS / Linux (not run; a starting point, not a guarantee)

```zsh
# untested. Ollama for macOS: https://docs.ollama.com/macos (Sonoma 14+; Apple Silicon or x86)
for m in nomic-embed-text llama3.2:1b llama3.2:3b qwen3:8b hermes3:8b qwen3.5:4b-q8_0; do ollama pull "$m"; done
ollama create qwen3-8b-8k -f modelfiles/qwen3-8b-8k.Modelfile
# eval extras:
for m in llama3.1:8b qwen2.5:7b embeddinggemma:300m-qat-q4_0 fluffy/l3-8b-stheno-v3.2:q8_0; do ollama pull "$m"; done
ollama list
# suggested, to mirror the Windows setup (only one Ollama model loaded at a time):
launchctl setenv OLLAMA_MAX_LOADED_MODELS 1   # then quit and reopen the Ollama app
```

```zsh
# untested. LM Studio for Mac: https://lmstudio.ai/docs/cli (`lms` ships with the app)
mkdir -p ~/gguf && cd ~/gguf
curl -L -o L3-8B-Stheno-v3.2-Q4_K_M.gguf https://huggingface.co/bartowski/L3-8B-Stheno-v3.2-GGUF/resolve/main/L3-8B-Stheno-v3.2-Q4_K_M.gguf
shasum -a 256 L3-8B-Stheno-v3.2-Q4_K_M.gguf   # compare: 8e98c1953f9c04e060fd9640bbe866685c844363a2360f09099b79c6c9195fc4
echo y | lms import L3-8B-Stheno-v3.2-Q4_K_M.gguf   # `lms import` can prompt Y/n even with --yes
lms ls                                                # is text-embedding-nomic-embed-text-v1.5 listed?
# only if it is not:
curl -L -o nomic-embed-text-v1.5.Q4_K_M.gguf https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf
echo y | lms import nomic-embed-text-v1.5.Q4_K_M.gguf
lms server start --port 1234 --bind 127.0.0.1
curl -s http://127.0.0.1:1234/v1/models   # must list l3-8b-stheno-v3.2 and text-embedding-nomic-embed-text-v1.5
```

The served LM Studio ids must match `twin/config.py` exactly (`l3-8b-stheno-v3.2`,
`text-embedding-nomic-embed-text-v1.5`). Set Stheno's context to 8192 in LM Studio's model load settings.

**Memory:** the numbers below are per model on a dedicated 8 GB GPU. On Apple Silicon these share unified memory
with macOS and everything else running; plan for one big model loaded at a time.

| Model | VRAM on the RTX 2070 |
|---|---|
| Stheno Q4_K_M | about 5.6 GB |
| `qwen3-8b-8k` at context 8192 | 5.6 GB |
| Stheno Q8_0 at context 8192 | 9.3 GB total (partly CPU) |
| `qwen3:8b` at context 40960 | 8.8 GB |

Run: `PYTHONUTF8=1 GRADIO_ANALYTICS_ENABLED=False python app.py --port 7861`, or `./start.sh` (it checks both
servers itself and falls back to `TWIN_NO_WARM=1` if neither answers). **Rebuild the indexes once** if your
embedders differ from the ones the shipped `data/index_*.npz` files were built with (index staleness compares only
content shas, never which embedder built them):

```zsh
PYTHONUTF8=1 python -m twin.index --build nomic --force
PYTHONUTF8=1 python -m twin.index --build lms_nomic --force
PYTHONUTF8=1 python -m twin.index --build gemma --force
```

## 4. Docker (verified on Windows with Docker Desktop)

The image replaces only the Python and Gradio setup. **The models still run in Ollama and LM Studio on the host**,
set up as in section 2 or 3. LM Studio has no official container image, so it always runs natively.

Verified on 2026-09-15 on the Windows laptop: Docker Desktop 29.8.0 with the WSL2 backend, Compose v5.5.1.

- `docker build -t twin-app .` took 42 s and produced a 682 MB image with the pinned versions (gradio 6.27.0,
  gradio_client 2.7.0).
- The app booted in the container and served the UI (HTTP 200, persona list present).
- From a container, `http://host.docker.internal:11434/api/tags` listed all 11 Ollama models and
  `http://host.docker.internal:1234/v1/models` listed both LM Studio models. That works even though both servers
  bind `127.0.0.1` on the host. Those are the URLs the image sets by default (`TWIN_OLLAMA_URL`, `TWIN_LMS_URL`).
- `docker run --gpus all` exposed the RTX 2070 inside a container (`nvidia-smi -L`).
- `docker compose up --build -d` with `docker-compose.yml` (Compose v5.5.1) served the app on `127.0.0.1` only,
  reached both host servers with its `host-gateway` line in place, and kept a file written to its named volume
  across `docker compose down` and `up`. `docker compose down -v` removed the volume.

Not yet checked: a model call made through the containerized app's UI, and the `-v` bind mount of the project's
`data` folder in section 4.1.

### 4.1 Build and run

```powershell
# from the project root, with Docker Desktop running
docker build -t twin-app .
docker run --rm --name twin-app -p 7861:7861 twin-app
# then open http://127.0.0.1:7861
```

Or with Docker Compose (`docker-compose.yml`), which publishes the app on `127.0.0.1` only, adds the
`host.docker.internal` mapping native Linux Docker needs, and keeps the app's data in a named volume
(`digital-twin_twin-data`) that survives `docker compose down`:

```powershell
docker compose up --build -d            # open http://127.0.0.1:7861
docker compose logs -f app              # follow the app log
docker compose down                     # stop; `docker compose down -v` also deletes the data volume
# options, set before `up` (or put them in a .env file next to docker-compose.yml):
$env:TWIN_PORT = "7899"                 # host port when 7861 is taken (macOS/Linux: TWIN_PORT=7899 docker compose up -d)
$env:TWIN_NO_WARM = "1"                 # UI only, never loads a model
```

The volume is seeded from the image's `data/` on first start, so rebuild the image and remove the volume
(`docker compose down -v`) when you want a changed `data/` folder to reach the container.

- **Port already in use?** If the native app is running on 7861, publish another host port, for example
  `-p 7899:7861`, and open `http://127.0.0.1:7899`. The container always listens on 7861 inside.
- **UI only, no model loads:** add `-e TWIN_NO_WARM=1`.
- **Keep your data:** anything the app writes (`data/audit.jsonl`, `data/telemetry.jsonl`, persona switches,
  rebuilt indexes) is lost when the container is removed. To write into your project's `data` folder instead,
  add `-v "${PWD}\data:/app/data"` (PowerShell) or `-v "$PWD/data:/app/data"` (macOS/Linux). Not yet tested.
- **Anthropic ceiling judge:** pass the key through without writing it into a file: `-e ANTHROPIC_API_KEY`.
- **Native Linux Docker** (not Docker Desktop) also needs `--add-host=host.docker.internal:host-gateway`, and the
  host servers must accept connections from the Docker bridge, which a `127.0.0.1` bind does not. Untested.

### 4.2 What behaves differently in the container

- **Free GPU can't unload LM Studio.** That button runs the Windows `lms.exe` (`twin/clients.py`, `unload_all`),
  which doesn't exist in a Linux container. Unload Stheno in LM Studio on the host (or `lms unload --all` there).
  Ollama models still stop, because that goes over HTTP.
- **GPU reading shows n/a** on the Status tab: the container has no `nvidia-smi`. Adding `--gpus all` makes it
  available (verified in a plain container, not with the app). The models don't need it, because they run on the
  host.

### 4.3 Docker troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker : The term 'docker' is not recognized` right after installing Docker Desktop | The terminal was opened before the install, so it has the old PATH | Open a new terminal |
| `error getting credentials - err: exec: "docker-credential-desktop": executable file not found` | Same cause: Docker's `resources\bin` folder isn't on this terminal's PATH | Open a new terminal, or `$env:Path = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:Path"` (per-user install; a machine-wide install uses `C:\Program Files\Docker\Docker\resources\bin`) |
| `docker run` fails with `port is already allocated` | Another app (often the native twin app) owns that host port | Use `-p 7899:7861` |
| Every model call errors, Status shows servers down | Ollama or LM Studio isn't running on the host | Start them (section 2); check from the host with `scripts\check_servers.ps1` |

## 5. Rules that apply on every platform

- **Request `qwen3-8b-8k`, never plain `qwen3:8b`, for anything but the digest and reflections build.** Ollama's
  default context (65536 in the Windows desktop app) doesn't fit an 8B model in 8 GB and pushes it partly onto the
  CPU, about 5x slower.
- **Manual Ollama requests must send `options.num_ctx` and `keep_alive`** for every model except `qwen3-8b-8k`
  (8192 for 8B models, 4096 for llama3.2, 2048 for embedders), or the model loads at 65536 context. The app already
  does this.
- **Turn off Qwen3 thinking**, or a reply can come back empty. Native `/api/chat`: `"think": false`. OpenAI-style
  `/v1/chat/completions`: `"reasoning_effort": "none"` (`think` is ignored there). The app already sends this.
- **Always send a system message to Stheno Q8_0** (`fluffy/l3-8b-stheno-v3.2:q8_0`). Its built-in default
  contains unfilled `{{char}}`/`{{user}}` placeholders and is only used when a request has no system message.
- **Request LM Studio's Stheno as `l3-8b-stheno-v3.2`, not `stheno-8b`.** The short id only exists while the
  model happens to be loaded under it; once it idles out, requests for it return HTTP 400.
- **Stheno samplers** (both quants, from its model card): temperature 1.12-1.22, min_p 0.075, top_k 50, repeat
  penalty 1.1.
- **Only one 8B-class model fits fully in 8 GB.** Both servers unload idle models on their own. Free the GPU
  immediately with the Status tab's **Free GPU** button, or:

  ```powershell
  # Windows
  & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" stop qwen3-8b-8k
  & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" stop fluffy/l3-8b-stheno-v3.2:q8_0
  & "$env:LOCALAPPDATA\Programs\LM Studio\resources\app\.webpack\lms.exe" unload --all
  ```

  ```zsh
  # macOS/Linux, untested
  ollama stop qwen3-8b-8k
  ollama stop fluffy/l3-8b-stheno-v3.2:q8_0
  lms unload --all
  ```

## 6. Verify it's working

```powershell
# Windows: both servers answer JSON AND the GPU is idle (<= 200 MiB used); prints PASS/FAIL, sets the exit code
powershell -File scripts\check_servers.ps1
```

```
curl -s http://127.0.0.1:1234/v1/models      # LM Studio: lists loaded and loadable models
curl -s http://127.0.0.1:11434/api/tags       # Ollama: lists every pulled model
```

Then open the app and check the **Status** tab. It shows every registry model's state (`loaded` / `on disk` /
`not pulled` / `not listed`) and the GPU reading, and lets you **Warm** or **Free GPU** without leaving the page.
`docs/WINDOWS_SETUP.md` sections "Quick checks" and "Troubleshooting" have one-line requests for each model plus a
symptom-to-fix table (empty replies, HTTP 400, slow Q8_0, `qwen3:8b` vs `qwen3-8b-8k`, port refused, 401).

## 7. Settings the app reads

| Variable | Default | What it does |
|---|---|---|
| `TWIN_OLLAMA_URL` | `http://127.0.0.1:11434` (image: `http://host.docker.internal:11434`) | Ollama server |
| `TWIN_LMS_URL` | `http://127.0.0.1:1234` (image: `http://host.docker.internal:1234`) | LM Studio server; the OpenAI base is this plus `/v1` |
| `TWIN_NO_WARM` | unset | `1` = never pre-warm or load a model (UI checks, tests) |
| `ANTHROPIC_API_KEY` | unset | Enables the optional Claude ceiling judge on the Eval tab |

## 8. Where this comes from

`twin/config.py` (`MODELS`, exact names and per-model request settings) is the source of truth in code.
`docs/WINDOWS_SETUP.md` has the Windows laptop's full setup with measured timings and a troubleshooting table.
`docs/CONTRACTS.md` "twin/config.py" documents the registry's fields. `docs/REPLICATE_ON_MAC.md` section 8 has the
per-model request-settings table and section 9.5 has the macOS commands section 3 is drawn from.
