#!/usr/bin/env bash
# start.sh: set up and start the digital twin app on macOS or Linux.
# (On Windows use the PowerShell commands in README.md, section "Run".)
#
# Usage:
#   ./start.sh              first run: create .venv and install requirements.txt, then start the app
#   ./start.sh --port 7862  first port to try (the app tries the next 9 when a port is busy)
#   ./start.sh --no-warm    never load a model (sets TWIN_NO_WARM=1)
#   ./start.sh --warm       allow model loading even when no model server answers yet
#   ./start.sh --test       run the test suite before starting (the tests never call a model)
#   ./start.sh --open       open the app in the default browser once it answers
#   ./start.sh --dry-run    show what would happen without changing anything
#   ./start.sh --help
#
# Model servers are optional: Ollama on http://127.0.0.1:11434 and LM Studio on http://127.0.0.1:1234.
# When neither answers, the app starts with TWIN_NO_WARM=1: every tab renders, Eval and Items show cached results,
# and buttons that need a model fail or say "skipped" until you start a model server and rerun ./start.sh.
# Needs Python 3.10 or newer (Gradio 6) and curl. Stop the app with Ctrl+C.
# If ./start.sh says "permission denied", run: chmod +x start.sh   (or start it with: bash start.sh)

set -eu

PORT=7861
WARM=auto
RUN_TESTS=0
OPEN_BROWSER=0
DRY_RUN=0

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port)
      if [ $# -lt 2 ]; then echo "start.sh: --port needs a number" >&2; exit 2; fi
      PORT="$2"
      shift 2
      ;;
    --port=*)
      PORT="${1#--port=}"
      shift
      ;;
    --no-warm) WARM=off; shift ;;
    --warm) WARM=on; shift ;;
    --test) RUN_TESTS=1; shift ;;
    --open) OPEN_BROWSER=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "start.sh: unknown option '$1' (see ./start.sh --help)" >&2; exit 2 ;;
  esac
done

case "$PORT" in
  ''|*[!0-9]*) echo "start.sh: --port must be a number, got '$PORT'" >&2; exit 2 ;;
esac
PORT=$((10#$PORT))
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65526 ]; then
  echo "start.sh: --port must be between 1 and 65526 (the app also tries the next 9 ports)" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")" >/dev/null && pwd)"
cd "$ROOT"
if [ ! -f app.py ] || [ ! -f requirements.txt ]; then
  echo "start.sh: app.py and requirements.txt not found in $ROOT; keep start.sh in the project folder" >&2
  exit 1
fi

say() { printf '%s\n' "$*"; }

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    say "  (dry run) $*"
  else
    "$@"
  fi
}

http_ok() {
  # Returns 0 when the URL answers HTTP 200 within 2 seconds (proxies bypassed: these are local servers).
  command -v curl >/dev/null 2>&1 || return 1
  code="$(curl -s --noproxy '*' -m 2 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || true)"
  [ "$code" = "200" ]
}

# 1. Python 3.10 or newer
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PY="$(command -v "$candidate")"
      break
    fi
  fi
done
if [ -z "$PY" ]; then
  say "start.sh: Python 3.10 or newer is required. On macOS: brew install python@3.12, or the installer from python.org."
  exit 1
fi
say "Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# 2. Virtual environment (.venv) and requirements.txt
#    A .venv whose Python is gone, older than 3.10, or without pip (an interrupted first run, a uv venv) is recreated.
VENV="$ROOT/.venv"
VPY=""
for cand in "$VENV/bin/python" "$VENV/Scripts/python.exe"; do
  if [ -x "$cand" ] && "$cand" -c 'import sys, pip; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    VPY="$cand"
    break
  fi
done
if [ -z "$VPY" ]; then
  if [ -e "$VENV" ]; then
    say "Recreating .venv (its Python is gone, older than 3.10, or has no pip) ..."
  else
    say "Creating the virtual environment in .venv ..."
  fi
  run "$PY" -m venv --clear "$VENV"
  if [ -x "$VENV/Scripts/python.exe" ]; then
    VPY="$VENV/Scripts/python.exe"
  else
    VPY="$VENV/bin/python"
  fi
fi

REQ_SHA="$("$PY" -c 'import hashlib; print(hashlib.sha256(open("requirements.txt", "rb").read()).hexdigest())')"
STAMP="$VENV/.requirements.sha256"
OLD_SHA=""
if [ -f "$STAMP" ]; then OLD_SHA="$(cat "$STAMP")"; fi
if [ "$OLD_SHA" != "$REQ_SHA" ]; then
  say "Installing requirements.txt into .venv (first run, or requirements.txt changed) ..."
  run "$VPY" -m pip install --upgrade pip
  run "$VPY" -m pip install -r requirements.txt
  if [ "$DRY_RUN" -eq 0 ]; then printf '%s\n' "$REQ_SHA" > "$STAMP"; fi
else
  say "Requirements: up to date in .venv"
fi

# 3. Environment the app expects
export PYTHONUTF8=1
export GRADIO_ANALYTICS_ENABLED=False

# 4. Model servers and model loading
if ! command -v curl >/dev/null 2>&1; then
  say "start.sh: curl not found, so the model-server check and --open can't work (install curl, or pass --warm)."
fi
OLLAMA_UP=0
LMS_UP=0
if http_ok "http://127.0.0.1:11434/api/tags"; then OLLAMA_UP=1; fi
if http_ok "http://127.0.0.1:1234/api/v0/models"; then LMS_UP=1; fi
if [ "$OLLAMA_UP" -eq 1 ]; then say "Ollama (127.0.0.1:11434): up"; else say "Ollama (127.0.0.1:11434): not answering"; fi
if [ "$LMS_UP" -eq 1 ]; then say "LM Studio (127.0.0.1:1234): up"; else say "LM Studio (127.0.0.1:1234): not answering"; fi

case "$WARM" in
  off)
    export TWIN_NO_WARM=1
    say "Model loading: off (--no-warm)"
    ;;
  on)
    unset TWIN_NO_WARM
    say "Model loading: on (--warm)"
    ;;
  *)
    if [ -n "${TWIN_NO_WARM:-}" ]; then
      nw="$(printf '%s' "$TWIN_NO_WARM" | tr '[:upper:]' '[:lower:]' | tr -d ' \t')"
      case "$nw" in
        ''|0|false|no) say "Model loading: on (TWIN_NO_WARM=$TWIN_NO_WARM from your environment)" ;;
        *) say "Model loading: off (TWIN_NO_WARM=$TWIN_NO_WARM from your environment)" ;;
      esac
    elif [ "$OLLAMA_UP" -eq 0 ] && [ "$LMS_UP" -eq 0 ]; then
      export TWIN_NO_WARM=1
      say "Model loading: off, because no model server answered (start Ollama or LM Studio and rerun, or pass --warm)"
    else
      say "Model loading: on (each model tab pre-warms its model when you select it)"
    fi
    ;;
esac

# 5. Optional test run
if [ "$RUN_TESTS" -eq 1 ]; then
  say "Running the test suite ..."
  if [ "$DRY_RUN" -eq 1 ]; then
    say "  (dry run) TWIN_NO_WARM=1 $VPY -m pytest -q -p no:cacheprovider"
  elif ! TWIN_NO_WARM=1 "$VPY" -m pytest -q -p no:cacheprovider; then
    say "start.sh: the tests failed, so the app was not started."
    exit 1
  fi
fi

# 6. Optional: open the browser once the app answers (runs in the background)
open_when_ready() {
  last=$((PORT + 9))
  already=" "
  p=$PORT
  while [ "$p" -le "$last" ]; do
    if http_ok "http://127.0.0.1:$p/"; then already="$already$p "; fi
    p=$((p + 1))
  done
  (
    tries=0
    while [ "$tries" -lt 120 ]; do
      # $$ is this script's PID, which becomes the app's after exec; stop when the app is gone (Ctrl+C).
      kill -0 "$$" 2>/dev/null || exit 0
      p=$PORT
      while [ "$p" -le "$last" ]; do
        case "$already" in
          *" $p "*)
            ;;
          *)
            if http_ok "http://127.0.0.1:$p/"; then
              url="http://127.0.0.1:$p/"
              if [ "$(uname -s)" = "Darwin" ]; then
                open "$url" || echo "Open $url in your browser."
              elif command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$url" >/dev/null 2>&1 || echo "Open $url in your browser."
              else
                echo "Open $url in your browser."
              fi
              exit 0
            fi
            ;;
        esac
        p=$((p + 1))
      done
      sleep 1
      tries=$((tries + 1))
    done
  ) &
}

# 7. Start the app (127.0.0.1 only)
say ""
say "Starting: $VPY app.py --port $PORT"
say "The app prints the URL it binds; if port $PORT is busy it tries the next 9. Stop it with Ctrl+C."
if [ "$DRY_RUN" -eq 1 ]; then
  say "  (dry run) exec $VPY app.py --port $PORT"
  exit 0
fi
if [ "$OPEN_BROWSER" -eq 1 ]; then open_when_ready; fi
exec "$VPY" app.py --port "$PORT"
