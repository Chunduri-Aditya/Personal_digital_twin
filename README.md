# Digital twin — for reviewers

A local "digital twin" web app: a small set of local language models that answer questions in one person's
voice and predict that person's decisions, grounded in a structured profile plus a redacted interview
transcript. It runs entirely on your own machine — the Gradio app talks only to two local model servers on
`127.0.0.1` (Ollama and LM Studio); nothing is sent to the network at request time.

**The active persona, Dana Kessler, is a fictional CEO profile, and every other registered persona (including
Mara Ellison, the synthetic example profile) is invented too — nothing shown here is a real person's data.**
The app also has a persona switcher (Status tab) with those fictional personas registered, and an "import a new
persona from a .md file" control, if you want to see that in action.

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

## Running it yourself

Two things are needed: the app itself (Python + Gradio), and at least one local model server with a few
models pulled. Full model instructions are in `docs/MODEL_SETUP.md` — the short version, either path below:

### Option A: plain Python

```bash
# macOS/Linux
./start.sh --open   # creates .venv, installs requirements, starts the app, opens your browser
```

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
all read the active persona (Dana Kessler, unless you switch).

`docs/WINDOWS_SETUP.md` is the setup record of the Windows laptop the project was built on: measured model
speeds, GPU sharing on an 8 GB card, quick checks and a troubleshooting table.
