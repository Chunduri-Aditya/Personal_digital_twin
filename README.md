# Digital twin — for reviewers

A local "digital twin" web app: a small set of local language models that answer questions in one person's
voice and predict that person's decisions, grounded in a structured profile plus a redacted interview
transcript. It runs entirely on your own machine — the Gradio app talks only to two local model servers on
`127.0.0.1` (Ollama and LM Studio); nothing is sent to the network at request time.

**The active persona, Mara Ellison, is a synthetic example profile written to exercise every feature, and every
other registered persona (including Dana Kessler, a fictional CEO) is invented too — nothing shown here is a
real person's data.**
The app also has a persona switcher (Status tab) with those fictional personas registered, and an "import a new
persona from a .md file" control, if you want to see that in action.

## Demo

Decide, Ask and Act were recorded live on 2026-09-16 on a MacBook (M3 Pro, 18 GB) against the local models in
**LLM setup** below, using the inputs from `docs/demo/beats.json`. The GIFs shorten the model waits; the times
quoted are the app's own readings. Wording varies from run to run.

### Decide: would she do it?

![Decide tab: a verdict with cited past decisions, then the same answer in Mara's voice](docs/demo/decide.gif)

The situation: *"A former agency client offers me a three month contract at double my usual rate, but it means
pausing my own product work and going back into their office three days a week. Should I take it?"*

1. **B1: Would I do it?** sends the situation plus 12 retrieved profile chunks to `qwen3-8b-8k`, which returns
   strict JSON: a verdict (NO), a confidence (0.95), reasons, the past decisions it leaned on (D-01 "Quit the agency
   job", D-02 "Turned down the crypto client", and six more), and what would change her mind. That call took
   32.9 s.
2. **Say it in my voice** hands the same verdict to Stheno on LM Studio, which rewrites it as a text in her style.

### Ask: a question in her voice, with the evidence beside it

![Ask tab: a streamed reply in Mara's voice with the Trace of router, retrieval and voice steps](docs/demo/ask.gif)

The question: *"What did you learn from quitting the agency job?"* under the `interview` condition. The Trace
shows every step: the router (`llama3.2:1b`) tags it `about_me` in 1.51 s, retrieval over the `nomic` index returns
five chunks led by `Interview/T-004a` (score 0.859) in 0.55 s, and Stheno writes the reply in 14.76 s, trimmed
to its last full sentence at the 300 token cap. Total 16.84 s.

### Act: tools, then her voice

![Act tab: hermes3 looks up a past decision, drafts a text, and Stheno polishes it](docs/demo/act.gif)

The request: *"Look up what I decided about the crypto startup's branding offer, then draft a short text to my
mentor telling them what I did and why."* `hermes3:8b` calls `search_profile` (which finds D-02 "Turned down the
crypto client", score 0.7687, through LM Studio's embedder so hermes3 stays loaded), then `draft_message` for a
mentor, and writes the answer. **Polish with Stheno** rewrites it in her voice. The Trace lists each tool call
with its arguments and result.

### Items, Eval and Status

| Items: the twin against her questionnaire answers | Eval: voice and retrieval bake offs, boundary probes |
|---|---|
| ![Items tab scores table and decision line](docs/demo/items.png) | ![Eval tab voice bake off, retrieval bake off and boundary probes](docs/demo/eval.png) |

![Status tab: memory, loaded models, audit tail of hashed requests, redaction report](docs/demo/status.png)

- **Items** scores the twin under three conditions against a frozen 111 item bank. The decision line reads
  *partial*: the interview condition wins on IPIP-50 accuracy and correlation and on the gold judge score, not on
  the GSS items or the economic games.
- **Eval** shows the cached voice bake off (the `persona` condition scores 4.4 overall against 3.8 for
  `interview`), the retrieval bake off across the three indexes, and 3/3 boundary probes deflected.
- **Status** shows unified memory, what each server has loaded, and the audit tail, where the Decide, Ask and Act
  requests above appear as sha256 hashes, never as text.

The Items and Eval tables are cached results from the Windows laptop runs (the scores and the probes are stamped
2026-09-14); they were read, not rerun, on the Mac. The full five minute walkthrough (Onboarding, Decide, Ask, Items, Status) with measured
waits is in `docs/DEMO.md`.

## What's worth a look

If you only have a few minutes, these are the more interesting pieces:

- `twin/personas.py` — a persona registry (switch between profiles, import a new one from an uploaded `.md`,
  each with its own transcript/reflections settings so a switch never silently mixes another persona's data
  into the one you're building). Built end-to-end in one sitting; a good look at range beyond just the chat UI.
- `twin/index.py` — the retrieval/build pipeline: profile parsing, chunking, containment checks (a gold answer
  can never leak into what gets retrieved), three parallel embedding indexes.
- `twin/ui/status.py` — the "machine room" tab: live GPU/model state, an audit trail, a redaction report, and
  the persona controls, all wired to `gradio_client`-drivable `api_name`s (see `twin/ui/frame.py`'s docstring
  for the full endpoint list).

`docs/CONTRACTS.md` has the module-by-module API reference if you want to go deeper; `tests/` has 604 offline
tests (no network, no GPU) that run in under a minute.

## LLM setup

Every model runs locally on `127.0.0.1`, split across two servers, neither with authentication: **Ollama**
(`:11434`) and **LM Studio** (`:1234`). The app finds models only by the exact names below, which come from
`MODELS` in `twin/config.py`. Weights are not in this repository.

| Role | Request this name | Server | Download | Needed for |
|---|---|---|---|---|
| Persona voice | `l3-8b-stheno-v3.2` (Q4_K_M) | LM Studio | 4.9 GB | Ask, Decide "Say it", See, Act polish |
| Embeddings, LM Studio side | `text-embedding-nomic-embed-text-v1.5` | LM Studio | 84 MB | Act, Decide, Items retrieval |
| Decisions, strict JSON | `qwen3-8b-8k` | Ollama | none (built from `qwen3:8b`) | Decide, Items |
| Base model and profile digest | `qwen3:8b` | Ollama | 5.2 GB | building `qwen3-8b-8k`; index build |
| Embeddings | `nomic-embed-text` | Ollama | 274 MB | Ask, See, Eval retrieval |
| Tool agent | `hermes3:8b` | Ollama | 4.7 GB | Act |
| Follow up rewrite, fallback voice | `llama3.2:3b` | Ollama | 2.0 GB | Ask |
| Router (intent JSON) | `llama3.2:1b` | Ollama | 1.3 GB | Ask |
| Image description | `qwen3.5:4b-q8_0` | Ollama | 5.3 GB | See |
| *Eval only:* voice at Q8_0 | `fluffy/l3-8b-stheno-v3.2:q8_0` | Ollama | 8.5 GB | Ask's Q8 toggle, Eval |
| *Eval only:* second embedder | `embeddinggemma:300m-qat-q4_0` | Ollama | 238 MB | Eval retrieval bake off |
| *Eval only:* checker, second judge | `qwen2.5:7b` | Ollama | 4.7 GB | Ask consistency check, Eval, Items |
| *Eval only:* primary judge | `llama3.1:8b` | Ollama | 4.9 GB | Eval, Items |
| *Optional:* ceiling judge | `claude-sonnet-5` / `claude-opus-5` | Anthropic API | none | Eval, only when `ANTHROPIC_API_KEY` is set |

About 24 GB for the first nine rows, 42 GB for everything. All 13 local models were confirmed installed under
these names on the MacBook with `ollama list` and `lms ls` (2026-09-16).

### macOS / Linux

Install Ollama (https://ollama.com) and LM Studio (https://lmstudio.ai), then from the project root:

```zsh
# Ollama: the demo set, then the model the Decide tab requests
for m in nomic-embed-text llama3.2:1b llama3.2:3b qwen3:8b hermes3:8b qwen3.5:4b-q8_0; do ollama pull "$m"; done
ollama create qwen3-8b-8k -f modelfiles/qwen3-8b-8k.Modelfile
# eval extras
for m in llama3.1:8b qwen2.5:7b embeddinggemma:300m-qat-q4_0 fluffy/l3-8b-stheno-v3.2:q8_0; do ollama pull "$m"; done
ollama list   # `ollama pull` can print an error and still exit 0, so check the list, not the exit code
```

```zsh
# LM Studio: lms ships with the app but is not on PATH (macOS: ~/.lmstudio/bin/lms)
curl -L -o L3-8B-Stheno-v3.2-Q4_K_M.gguf https://huggingface.co/bartowski/L3-8B-Stheno-v3.2-GGUF/resolve/main/L3-8B-Stheno-v3.2-Q4_K_M.gguf
shasum -a 256 L3-8B-Stheno-v3.2-Q4_K_M.gguf   # 8e98c1953f9c04e060fd9640bbe866685c844363a2360f09099b79c6c9195fc4
echo y | lms import L3-8B-Stheno-v3.2-Q4_K_M.gguf   # can prompt Y/n even with --yes
lms ls   # must list l3-8b-stheno-v3.2 and text-embedding-nomic-embed-text-v1.5
```

Set Stheno's context length to 8192 in LM Studio's load settings; the app sends none. On the Mac the models were
already present, so these download commands have not been run there end to end; the model names and the running
app have. `./start.sh` starts either server if it is not answering (see below).

### Measured on the MacBook

Apple M3 Pro, 18 GB unified memory, Ollama 0.34.0, LM Studio 0.4.24. Readings from the app during the demo
recordings on 2026-09-16, single runs unless noted:

| Step | Model | Time |
|---|---|---|
| Decide tab pre-warm | `qwen3-8b-8k` | 3.3 s |
| Decide verdict, 12 chunks | `qwen3-8b-8k` | 32.9 s (17.0 s on a 2026-09-15 run of the same input) |
| Ask router | `llama3.2:1b` | 1.51 s |
| Ask retrieval, k=5 | `nomic-embed-text` | 0.55 s |
| Ask reply, 300 token cap | `l3-8b-stheno-v3.2` | 14.76 s (16.84 s for the whole turn) |
| Act tab pre-warm | `hermes3:8b` | 3.6 s and 2.1 s (two runs) |

Memory is shared with macOS and everything else running, so the app's GPU reading is the whole machine's unified
memory: 13.6 of 18 GB with Stheno loaded, and up to 15.6 GB with `hermes3:8b`, `llama3.2:1b` and
`nomic-embed-text` all loaded in Ollama at once. The Windows setup keeps one 8B model loaded at a time because of
its 8 GB card; on the Mac, Ollama held those three together at 100% GPU. See, the Eval judges (`llama3.1:8b`,
`qwen2.5:7b`) and the Q8 voice have not been run live on the Mac yet.

### Windows

The verified Windows commands (PowerShell, `ollama.exe` and `lms.exe` by full path) are in `docs/MODEL_SETUP.md`
section 2, and `docs/WINDOWS_SETUP.md` has the measured speeds and a troubleshooting table.

### Check it

```zsh
curl -s http://127.0.0.1:11434/api/tags   # Ollama: every pulled model
curl -s http://127.0.0.1:1234/v1/models   # LM Studio: loaded and loadable models
```

Then open the app's **Status** tab: it marks every registry model `loaded`, `on disk`, `not pulled` or
`not listed`, and has **Warm** and **Free GPU** buttons.

### Traps

- Request `qwen3-8b-8k`, not plain `qwen3:8b`. The Ollama app's default context of 65536 pushes an 8B model
  mostly onto the CPU on an 8 GB card, about 5x slower.
- Request LM Studio's voice as `l3-8b-stheno-v3.2`. The short id `stheno-8b` returns HTTP 400 once the model idles
  out.
- An interrupted `ollama pull` on macOS leaves `~/.ollama/models/blobs/sha256-<digest>-partial*` files, and every
  retry of that model then fails with `Error: EOF`. Delete that digest's `-partial*` files and pull again.
- Manual Ollama requests must send `options.num_ctx` and `keep_alive`, and Qwen3 requests must turn thinking off.
  The app already does both; `docs/MODEL_SETUP.md` section 5 has the values.

## Running it yourself

Two things are needed: the app itself (Python and Gradio) and the model servers from **LLM setup** above. Either
path below works.

### Option A: plain Python

```bash
# macOS/Linux
./start.sh --open   # creates .venv, installs requirements, starts the app, opens your browser
```

On macOS/Linux `start.sh` also starts whichever model server is not already answering (Ollama.app or
`ollama serve`, and `lms server start`) before it launches the app, so a cold boot needs no manual step. Use
`--no-warm` or `--dry-run` to skip that and leave the servers alone; `--test`, `--port` and `--open` are the
other flags.

```powershell
# Windows
$env:PYTHONUTF8=1; $env:GRADIO_ANALYTICS_ENABLED='False'; python app.py --port 7861
```

The app renders and opens even with no model server running (it just says so and disables model-backed
buttons); everything works once Ollama and/or LM Studio are up per `docs/MODEL_SETUP.md`.

### Option B: Docker

```bash
docker build -t twin-app .
docker run -p 7861:7861 twin-app
# on native Linux Docker (not Docker Desktop), also add: --add-host=host.docker.internal:host-gateway
```

Or with Docker Compose, which also binds the app to `127.0.0.1` only and keeps its data in a named volume
(`docker-compose.yml` lists the options, such as `TWIN_PORT` when 7861 is taken):

```bash
docker compose up --build -d
docker compose down
```

This gives you the exact pinned Python/Gradio environment without a manual venv setup. It does **not** remove
the need for the model servers: the container reaches them on the host via `host.docker.internal`, which is
already the image's default. One real constraint worth knowing before you try this: **LM Studio has no
official Docker or headless-server image**, so it always has to run natively on your machine (GUI app) even
if the twin app itself runs in a container — Docker only replaces the Python setup step, not the model-server
step. Ollama does have an official container if you'd rather not install its desktop app either
(`docker run -d -p 11434:11434 ollama/ollama`), but the app's default env points at a host-run Ollama by
default; override `TWIN_OLLAMA_URL`/`TWIN_LMS_URL` if you run either differently.

Then open `http://127.0.0.1:7861`. Onboarding opens first if there's no real profile; Ask/Decide/Act/See/Items
all read the active persona (Mara Ellison, unless you switch).

`docs/WINDOWS_SETUP.md` is the setup record of the Windows laptop the project was built on: measured model
speeds, GPU sharing on an 8 GB card, quick checks and a troubleshooting table. The one-model-at-a-time rule in
`twin/gpu.py` and the 8k context in `modelfiles/qwen3-8b-8k.Modelfile` are sized for that 8 GB card, not for a
machine with more memory to spend.
