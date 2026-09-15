"""Demo rehearsal tooling for PLAN_DEMO Session B (docs/PLAN_DEMO.md; beats in docs/demo/beats.json; run sheet
docs/DEMO.md). Python 3 standard library only; set PYTHONUTF8=1. Paths resolve from this file, so it runs from any
directory.

  python scripts/demo_rehearse.py --run N [--port P] [--beats docs/demo/beats.json] [--only ID,ID]
                                  [--include-optional] [--dry-run]
  python scripts/demo_rehearse.py --dry-run [--beats FILE] [--only ID,ID] [--include-optional]
  python scripts/demo_rehearse.py --check-profile
  python scripts/demo_rehearse.py --smoke [--models KEY,KEY]

--check-profile  TWIN_NO_WARM=1 in this process; loads the profile exactly like twin/ui/state.load_app_profile(),
                 runs the profile lint and the index/digest freshness checks the app shows (header warnings,
                 Onboarding step 3). Prints JSON; exit 0 only when fresh and lint-clean. No model or HTTP call, no
                 writes (bytecode writing is off too).
--smoke          calls every model the demo uses directly against Ollama / LM Studio (bypassing the app), one at a
                 time, with the request shape twin/clients.py uses (names, num_ctx, keep_alive, think and samplers
                 parsed from twin/config.py with ast, never imported). Writes scripts/dev/demo/model_smoke.json and
                 model_smoke.md, then unloads what it loaded. Exit 0 only when every model passes. Never touches data/.
--dry-run        validates the beats file against the contract and prints the steps that would run; no app contact.
--run N          runs the selected, non-forbidden steps in file order through scripts/dev/live_drive.py
                 subprocesses; per step: scripts/dev/demo/run<N>_<id>.txt (stdout, "=== label ===" lines
                 timestamped), one JSON line in rehearsal_run<N>.log as soon as the step ends (the log is truncated
                 at the start of a full run and appended to when --only is given), and after steps with an
                 expected_model the Ollama /api/ps and LM Studio /api/v0/models bodies. Afterwards data/act_answer.txt
                 is deleted and run<N>_summary.json is written. Exit 1 when a step failed or data/items/scores.json
                 changed. Every attempt uses a new N: a full run refuses when run<N>_summary.json or a non-empty
                 rehearsal_run<N>.log exists, --only refuses a step whose run<N>_<id>.txt exists, and an --only run
                 into an N that already has a summary writes run<N>_only_<stamp>_summary.json instead.

This runner never imports gradio_client or twin in --run, --smoke or --dry-run, and never calls a forbidden
endpoint (Items save/score, Run twin, Eval re-runs, Rebuild index/digest, the Q8 toggle, the consistency checker).
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "scripts" / "dev" / "demo"
DATA_DIR = ROOT / "data"
LIVE_DRIVE_REL = "scripts/dev/live_drive.py"
LIVE_DRIVE = ROOT / "scripts" / "dev" / "live_drive.py"
DEFAULT_BEATS = "docs/demo/beats.json"
SCORES_PATH = DATA_DIR / "items" / "scores.json"
ACT_ANSWER_PATH = DATA_DIR / "act_answer.txt"
TEST_PHOTO = ROOT / "scripts" / "dev" / "test_photo.jpg"
APP_PORT_FILE = DEMO_DIR / "app.port"
BASELINE_DATA_LIST = DEMO_DIR / "data_files_before.txt"
PRE_SNAPSHOT = DEMO_DIR / "pre_snapshot.json"
CONFIG_PY = ROOT / "twin" / "config.py"
PROMPTS_PY = ROOT / "twin" / "prompts.py"
STATE_PY = ROOT / "twin" / "ui" / "state.py"
DEFAULT_PORT = 7861
OLLAMA_URL = "http://127.0.0.1:11434"
LMS_URL = "http://127.0.0.1:1234"

# ---- beats.json contract ---------------------------------------------------------------------------------------
TOP_BEATS = ("B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "BX")
STEP_ID_RE = re.compile(r"^(B[0-8]|BX)\.(\d+)$")
TABS = ("onboarding", "decide", "ask", "act", "items", "eval", "status", "see")
FIELD_TYPES = {
    "id": "str", "beat": "str", "tab": "str", "title": "str", "live_drive_args": "list_str",
    "history_file": "str_or_null", "expected_model": "str_or_null", "budget_ms": "int", "fallback": "str",
    "forbidden": "bool", "optional": "bool", "in_cut": "bool", "expect": "obj_or_null",
}
OPTIONAL_FIELDS = ("expect",)
# contains_all / contains_any / not_contains scan the whole step output (trace included); answer_not_contains scans
# only the "=== answer ===" block of an act step, so a prose answer that restates tool instructions or dumps the tool
# JSON cannot pass as a draft just because the trace is clean.
EXPECT_TYPES = {"contains_all": "list_str", "contains_any": "list_str", "not_contains": "list_str",
                "reply_nonempty": "bool", "answer_not_contains": "list_str"}
LABEL_RE = re.compile(r"^=== (.*) ===\s*$")
NUMBER_RE = re.compile(r"^-\d+(\.\d+)?$")

FALLBACK_COMMANDS = ("view_api", "status", "warm", "free_gpu", "ask", "decide_b1", "decide_b2", "say_it",
                     "eval_live", "act", "polish", "see", "eval_show")
FALLBACK_WARM_CHOICES = ("active", "ask", "decide", "act", "see")
CONDITIONS = ("demographic", "persona", "interview")
POSITIONAL_COUNT = {"view_api": (0, 0), "status": (0, 0), "warm": (1, 1), "free_gpu": (0, 0), "ask": (1, 1),
                    "decide_b1": (1, 1), "decide_b2": (3, 3), "say_it": (0, 0), "eval_live": (0, 2),
                    "act": (1, 1), "polish": (1, 1), "see": (1, 1), "eval_show": (0, 0)}
VALUE_FLAGS = ("--save-history", "--condition", "--temp")
BOOL_FLAGS = ("--polish", "--say")
BANNED_FLAGS = {"--port": "rehearse appends --port itself", "--history-file": "use the history_file key instead"}
FORBIDDEN_FLAGS = {"--q8": "the Q8 toggle is forbidden live", "--checker": "the consistency checker is forbidden live"}
FORBIDDEN_COMMANDS = {"eval_live": "/eval_live runs the qwen2.5 consistency checker (forbidden live)"}
CMD_TAB = {"ask": "ask", "decide_b1": "decide", "decide_b2": "decide", "say_it": "decide", "act": "act",
           "polish": "act", "see": "see", "eval_show": "eval", "status": "status", "free_gpu": "status"}
DECIDE_COMMANDS = ("decide_b1", "decide_b2")

# ---- smoke test --------------------------------------------------------------------------------------------------
SMOKE_TIMEOUT_S = 300.0          # a cold 8B load can take 30-60 s; generous on purpose
# (config key, name the contract uses or None when it names only the role, role)
SMOKE_PLAN = (
    ("nomic_ollama", "nomic-embed-text", "Ollama retrieval embedder (Ask interview, See)"),
    ("llama32_1b", None, "llama3.2 router (Ask intent JSON)"),
    ("llama32_3b", None, "llama3.2 follow-up rewrite (Ask follow-up)"),
    ("qwen3_8k", "qwen3-8b-8k", "Decide B1 structured JSON"),
    ("hermes3", "hermes3:8b", "Act tool agent"),
    ("qwen35_vision", None, "See vision model"),
    ("stheno_q4", "l3-8b-stheno-v3.2", "voice: Ask reply, Say it, See reaction"),
    ("nomic_lms", "text-embedding-nomic-embed-text-v1.5", "LM Studio embedder (Act search_profile)"),
)
SMOKE_QUESTION = "What did you learn from quitting the agency job?"
FALLBACK_PROMPTS = {
    "ROUTER_SYSTEM": ("Classify the user's latest message into exactly one intent and answer with JSON only.\n"
                      'Output: {"intent": "<one of about_me|decide|tool|image|smalltalk>"}'),
    "ROUTER_SCHEMA": {"type": "object", "properties": {"intent": {"type": "string", "enum": [
        "about_me", "decide", "tool", "image", "smalltalk"]}}, "required": ["intent"]},
    "REWRITE_SYSTEM": ("Rewrite the user's latest follow-up message as one standalone search query that makes sense "
                       "without the conversation history. Output only the query, nothing else."),
    "VISION_PROMPT": "Describe this image factually in 5 sentences.",
    "AGENT_TOOLS": [{"type": "function", "function": {"name": "get_datetime",
                                                      "description": "Get the current local date and time.",
                                                      "parameters": {"type": "object", "properties": {},
                                                                     "required": []}}}],
}

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never route 127.0.0.1 through a proxy


# =================================================================================================================
# small helpers
# =================================================================================================================
def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _resolve(p: str) -> Path:
    return (ROOT / p).resolve()


def _normcase(p: Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _under_demo(p: str) -> bool:
    try:
        resolved = _normcase(_resolve(p))
    except (OSError, ValueError):
        return False
    base = _normcase(DEMO_DIR.resolve())
    return resolved.startswith(base + os.sep)


def _excerpt(text, n: int = 200) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 3] + "..."


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    except OSError:
        return None


def _data_files() -> list[str]:
    """data/ file list as Windows-style relative paths (the scripts/dev/demo/data_files_before.txt format)."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(DATA_DIR):
        dirnames.sort()
        for fn in filenames:
            rel = Path(dirpath, fn).relative_to(ROOT)
            out.append(str(rel).replace("/", "\\"))
    return sorted(out, key=str.lower)


def _http(method: str, url: str, body=None, timeout: float = 5.0) -> dict:
    """{status, text, json, error, wall_ms}; never raises."""
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    status, text, err = None, "", ""
    t0 = time.perf_counter()
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            status = r.status
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            text = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            text = ""
        err = f"HTTP {e.code}: {_excerpt(text, 300)}"
    except Exception as e:  # noqa: BLE001  (URLError, timeout, connection refused)
        err = f"{type(e).__name__}: {e}"
    wall_ms = (time.perf_counter() - t0) * 1000.0
    parsed = None
    if text:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    return {"status": status, "text": text, "json": parsed, "error": err, "wall_ms": wall_ms}


def _module_literals(path: Path) -> dict:
    """Module-level NAME = <literal> assignments of a Python file, via ast (the file is never imported)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    env: dict = {}
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target, value = node.target.id, node.value
        if target is None:
            continue
        try:
            env[target] = ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError, RecursionError):
            pass
    return env


def live_drive_commands() -> tuple[str, ...]:
    """The command names live_drive.py dispatches on (parsed from its source), else the known list."""
    try:
        found = re.findall(r'a\.cmd == "([a-z0-9_]+)"', LIVE_DRIVE.read_text(encoding="utf-8"))
    except OSError:
        found = []
    return tuple(dict.fromkeys(found)) or FALLBACK_COMMANDS


def warm_choices() -> tuple[str, ...]:
    """Tab ids /warm accepts (twin/ui/state.py WARM_CHOICES, parsed, not imported)."""
    val = _module_literals(STATE_PY).get("WARM_CHOICES")
    if isinstance(val, list) and all(isinstance(v, str) for v in val) and val:
        return tuple(val)
    return FALLBACK_WARM_CHOICES


def load_config_models() -> dict[str, dict]:
    """twin/config.py MODELS as {key: {key, name, runtime, kind, vram, num_ctx, keep_alive, think, samplers, job}},
    parsed with ast so importing twin (and anything app-side) never happens."""
    fields = ["key", "name", "runtime", "kind", "vram", "num_ctx", "keep_alive", "think", "samplers", "job"]
    try:
        tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    env = _module_literals(CONFIG_PY)

    def val(node):
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            raise ValueError(f"unresolved name {node.id}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and node.args:
            return dict(val(node.args[0]))
        return ast.literal_eval(node)

    models: dict[str, dict] = {}
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target != "MODELS" or not isinstance(value, ast.Dict):
            continue
        for k_node, v_node in zip(value.keys, value.values):
            try:
                key = ast.literal_eval(k_node)
                if not isinstance(v_node, ast.Call):
                    continue
                spec = dict(zip(fields, [val(a) for a in v_node.args]))
                for kw in v_node.keywords:
                    spec[kw.arg] = val(kw.value)
                spec.setdefault("samplers", {})
                models[str(key)] = spec
            except (ValueError, TypeError, SyntaxError):
                continue
    return models


# =================================================================================================================
# beats.json validation (--dry-run, and the gate in front of --run)
# =================================================================================================================
def _type_ok(value, kind: str) -> bool:
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list_str":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if kind == "str_or_null":
        return value is None or isinstance(value, str)
    if kind == "obj_or_null":
        return value is None or isinstance(value, dict)
    return False


def parse_live_drive_args(args: list[str]) -> tuple[str | None, list[str], dict, list[str]]:
    """(command, positionals, flags, problems) for a live_drive argv (without --port / --history-file)."""
    problems: list[str] = []
    if not args:
        return None, [], {}, problems
    cmd = args[0]
    positionals: list[str] = []
    flags: dict = {}
    i = 1
    while i < len(args):
        tok = args[i]
        if tok.startswith("-") and tok != "-" and not NUMBER_RE.match(tok):
            name, eq, value = tok.partition("=")
            if name in VALUE_FLAGS:
                if eq:
                    flags[name] = value
                elif i + 1 < len(args):
                    flags[name] = args[i + 1]
                    i += 1
                else:
                    problems.append(f"{name} needs a value")
            else:
                flags[name] = value if eq else True
        else:
            positionals.append(tok)
        i += 1
    return cmd, positionals, flags, problems


def validate_beats(data, only: str | None = None, include_optional: bool = False):
    """(valid steps, selected steps, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, list):
        return [], [], ["top level must be a JSON array of step objects"], warnings
    commands = live_drive_commands()
    warm = warm_choices()
    known_models = {m.get("name") for m in load_config_models().values() if m.get("name")}
    steps: list[dict] = []
    seen: set[str] = set()
    saved_by: dict[str, str] = {}           # normcased history path -> first step id that saves it

    for i, step in enumerate(data):
        where = f"step[{i}]"
        if not isinstance(step, dict):
            errors.append(f"{where}: must be an object")
            continue
        sid = step.get("id")
        if isinstance(sid, str):
            where = f"{where} {sid}"
        bad = False
        for key, kind in FIELD_TYPES.items():
            if key not in step:
                if key not in OPTIONAL_FIELDS:
                    errors.append(f"{where}: missing key {key!r}")
                    bad = True
                continue
            if not _type_ok(step[key], kind):
                errors.append(f"{where}: {key!r} must be {kind.replace('_', ' ')}, got {type(step[key]).__name__}")
                bad = True
        extra = sorted(set(step) - set(FIELD_TYPES))
        if extra:
            warnings.append(f"{where}: unknown keys {extra} (ignored)")
        if bad:
            continue

        # id, beat, tab
        m = STEP_ID_RE.match(step["id"])
        if not m:
            errors.append(f"{where}: id must be <beat>.<n> with beat in {'/'.join(TOP_BEATS)} (e.g. B4.2), "
                          f"got {step['id']!r}")
        elif step["beat"] != m.group(1):
            errors.append(f"{where}: beat {step['beat']!r} does not match the id prefix {m.group(1)!r}")
        if step["beat"] not in TOP_BEATS:
            errors.append(f"{where}: beat must be one of {TOP_BEATS}, got {step['beat']!r}")
        if step["id"] in seen:
            errors.append(f"{where}: duplicate id {step['id']!r}")
        seen.add(step["id"])
        if step["tab"] not in TABS:
            errors.append(f"{where}: tab must be one of {TABS}, got {step['tab']!r}")
        # 0 is allowed for steps that never call the API (view-only rows record wall_ms 0; forbidden rows never run)
        if step["budget_ms"] < 0 or (step["budget_ms"] == 0 and step["live_drive_args"] and not step["forbidden"]):
            errors.append(f"{where}: budget_ms must be a positive integer for a step that calls live_drive.py "
                          f"(0 is allowed only for view-only or forbidden steps)")
        if step["forbidden"] and step["in_cut"]:
            warnings.append(f"{where}: forbidden step marked in_cut")
        em = step["expected_model"]
        if em and known_models and em not in known_models and em.removesuffix(":latest") not in known_models:
            warnings.append(f"{where}: expected_model {em!r} is not a model name in twin/config.py MODELS")

        # live_drive_args
        args = step["live_drive_args"]
        cmd, positionals, flags, problems = parse_live_drive_args(args)
        for p in problems:
            errors.append(f"{where}: live_drive_args: {p}")
        for flag, why in BANNED_FLAGS.items():
            if flag in flags:
                errors.append(f"{where}: live_drive_args must not contain {flag} ({why})")
        save = flags.get("--save-history")
        if isinstance(save, str):
            if not _under_demo(save):
                errors.append(f"{where}: --save-history {save!r} must be under scripts/dev/demo/")
        elif "--save-history" in flags:
            errors.append(f"{where}: --save-history needs a path")
        if cmd is not None:
            if step["forbidden"]:
                if cmd not in commands:
                    warnings.append(f"{where}: forbidden (documented-only) step names unknown command {cmd!r}")
            else:
                if cmd.startswith("-") or cmd not in commands:
                    errors.append(f"{where}: live_drive_args[0] must be a live_drive.py command {commands}, "
                                  f"got {cmd!r}")
                if cmd in FORBIDDEN_COMMANDS:
                    errors.append(f"{where}: {FORBIDDEN_COMMANDS[cmd]}; mark the step forbidden")
                for flag, why in FORBIDDEN_FLAGS.items():
                    if flag in flags:
                        errors.append(f"{where}: {flag}: {why}; mark the step forbidden")
                unknown = [f for f in flags if f not in VALUE_FLAGS and f not in BOOL_FLAGS
                           and f not in BANNED_FLAGS and f not in FORBIDDEN_FLAGS]
                if unknown:
                    errors.append(f"{where}: unknown live_drive flags {unknown}")
                lo, hi = POSITIONAL_COUNT.get(cmd, (0, 99))
                if not lo <= len(positionals) <= hi:
                    errors.append(f"{where}: {cmd} takes {lo}..{hi} positional argument(s), got {len(positionals)}"
                                  f" {positionals}")
                if cmd == "warm" and positionals and positionals[0] not in warm:
                    errors.append(f"{where}: warm tab {positionals[0]!r} is not accepted by /warm {warm}")
                if cmd == "warm" and positionals and positionals[0] != step["tab"]:
                    warnings.append(f"{where}: warms {positionals[0]!r} but tab is {step['tab']!r}")
                if cmd == "see" and positionals and not _resolve(positionals[0]).is_file():
                    errors.append(f"{where}: see image {positionals[0]!r} does not exist")
                if cmd in CMD_TAB and CMD_TAB[cmd] != step["tab"]:
                    warnings.append(f"{where}: command {cmd} usually belongs to tab {CMD_TAB[cmd]!r}, "
                                    f"not {step['tab']!r}")
                cond = flags.get("--condition")
                if "--condition" in flags and cond not in CONDITIONS:
                    errors.append(f"{where}: --condition must be one of {CONDITIONS}, got {cond!r}")
                if "--condition" in flags and cmd not in ("ask", "decide_b1", "decide_b2"):
                    warnings.append(f"{where}: --condition has no effect on {cmd}")
                if "--temp" in flags:
                    try:
                        float(flags["--temp"])
                    except (TypeError, ValueError):
                        errors.append(f"{where}: --temp must be a number")
                if "--say" in flags and cmd not in DECIDE_COMMANDS:
                    errors.append(f"{where}: --say only works with decide_b1/decide_b2")
                if "--polish" in flags and cmd != "act":
                    warnings.append(f"{where}: --polish has no effect on {cmd}")
                if save is not None and cmd != "ask":
                    warnings.append(f"{where}: --save-history has no effect on {cmd}")
                if cmd == "say_it":
                    warnings.append(f"{where}: say_it in a new process has no decision session; use "
                                    "decide_b1 --say instead")
        elif step.get("expect"):
            warnings.append(f"{where}: expect is ignored on a view-only step (no API call)")

        # history_file
        hf = step["history_file"]
        if hf is not None:
            if not _under_demo(hf):
                errors.append(f"{where}: history_file {hf!r} must be under scripts/dev/demo/")
            elif not step["forbidden"]:
                key = _normcase(_resolve(hf))
                if key not in saved_by and not _resolve(hf).is_file():
                    errors.append(f"{where}: history_file {hf!r} is not saved by an earlier step's --save-history "
                                  "and does not exist on disk")
            if cmd is not None and cmd != "ask":
                warnings.append(f"{where}: history_file has no effect on {cmd}")
        if isinstance(save, str) and _under_demo(save) and not step["forbidden"]:
            saved_by.setdefault(_normcase(_resolve(save)), step["id"])

        # expect
        exp = step.get("expect")
        if exp:
            for k, v in exp.items():
                if k not in EXPECT_TYPES:
                    errors.append(f"{where}: expect has unknown key {k!r} (allowed: {list(EXPECT_TYPES)})")
                elif not _type_ok(v, EXPECT_TYPES[k]):
                    errors.append(f"{where}: expect.{k} must be {EXPECT_TYPES[k].replace('_', ' ')}")
            if exp.get("reply_nonempty") and cmd != "ask":
                warnings.append(f"{where}: expect.reply_nonempty only applies to ask steps")
            if exp.get("answer_not_contains") and cmd != "act":
                warnings.append(f"{where}: expect.answer_not_contains only applies to act steps")
        steps.append(step)

    # selection
    selected: list[dict] = []
    by_id = {s["id"]: s for s in steps}
    if only:
        wanted = [x.strip() for x in only.split(",") if x.strip()]
        for w in wanted:
            if w not in by_id:
                errors.append(f"--only: unknown step id {w!r}")
            elif by_id[w]["forbidden"]:
                errors.append(f"--only: {w} is forbidden (documented only, never executed)")
        wanted_set = set(wanted)
        selected = [s for s in steps if s["id"] in wanted_set and not s["forbidden"]]
    else:
        selected = [s for s in steps if not s["forbidden"] and (include_optional or not s["optional"])]
    if any(s["forbidden"] for s in selected):   # defence in depth: never reachable
        errors.append("internal: a forbidden step was selected")
    produced: set[str] = set()
    for s in selected:
        hf = s["history_file"]
        if hf and _under_demo(hf):
            key = _normcase(_resolve(hf))
            if key not in produced and not _resolve(hf).is_file():
                warnings.append(f"{s['id']}: history_file {hf!r} is not produced by an earlier selected step and "
                                "is not on disk yet (the step will fail unless its producer runs first)")
        _, _, fl, _ = parse_live_drive_args(s["live_drive_args"])
        if isinstance(fl.get("--save-history"), str):
            produced.add(_normcase(_resolve(fl["--save-history"])))
    return steps, selected, errors, warnings


def _step_command(step: dict, port: int) -> list[str]:
    cmd = [sys.executable, LIVE_DRIVE_REL, *step["live_drive_args"], "--port", str(port)]
    if step.get("history_file"):
        cmd += ["--history-file", step["history_file"]]
    return cmd


def _load_beats(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    except ValueError as e:
        return None, f"{path} is not valid JSON: {e}"


def _resolve_port(port: int | None) -> int:
    if port:
        return int(port)
    try:
        return int(APP_PORT_FILE.read_text(encoding="utf-8-sig").strip())
    except (OSError, ValueError):
        return DEFAULT_PORT


def dry_run_mode(a) -> int:
    beats_path = _resolve(a.beats)
    data, err = _load_beats(beats_path)
    print(f"beats: {_rel(beats_path)}")
    if err:
        print(f"ERROR {err}")
        print("dry-run: FAILED (1 error)")
        return 1
    steps, selected, errors, warnings = validate_beats(data, a.only, a.include_optional)
    port = _resolve_port(a.port)
    n_forbidden = sum(1 for s in steps if s["forbidden"])
    n_optional = sum(1 for s in steps if s["optional"] and not s["forbidden"])
    print(f"steps: {len(data) if isinstance(data, list) else 0} in file, {len(steps)} well-formed, "
          f"{n_forbidden} forbidden (never run), {n_optional} optional")
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR {e}")
    sel_note = f"--only {a.only}" if a.only else ("default + optional" if a.include_optional else "default")
    print(f"would run ({len(selected)} steps, selection: {sel_note}, port {port}):")
    for s in selected:
        tags = [t for t, on in (("optional", s["optional"]), ("in_cut", s["in_cut"])) if on]
        head = f"  {s['id']:<6} {s['tab']:<10} budget {s['budget_ms'] / 1000:.0f} s" + (f" [{', '.join(tags)}]" if tags else "")
        if s["live_drive_args"]:
            print(head + "  " + subprocess.list2cmdline(["python", *_step_command(s, port)[1:]]))
        else:
            print(head + "  (view-only: no API call)")
    skipped = [s["id"] for s in steps if s not in selected]
    if skipped:
        print(f"not run: {', '.join(skipped)}")
    if errors:
        print(f"dry-run: FAILED ({len(errors)} error{'s' if len(errors) != 1 else ''})")
        return 1
    print("dry-run: OK")
    return 0


# =================================================================================================================
# --run
# =================================================================================================================
def _section(lines: list[str], label: str) -> str | None:
    """Text printed under '=== label ===' up to the next '=== ... ===' line; None when the label is absent."""
    out: list[str] = []
    inside = False
    found = False
    for ln in lines:
        m = LABEL_RE.match(ln)
        if m:
            if inside:
                break
            if m.group(1) == label:
                inside = found = True
            continue
        if inside:
            out.append(ln)
    return "\n".join(out) if found else None


def _attempts(lines: list[str]) -> tuple[int | None, dict | None, str]:
    raw = _section(lines, "result_json")
    if raw is None:
        return None, None, "no result_json block"
    try:
        js = json.loads(raw)
    except ValueError as e:
        return None, None, f"result_json not parseable ({e})"
    if not isinstance(js, dict):
        return None, None, "result_json is not an object"
    att = js.get("attempts")
    if isinstance(att, bool):
        att = None
    if isinstance(att, list):
        return len(att), js, ""
    if isinstance(att, (int, float)):
        return int(att), js, ""
    return None, js, "result_json has no attempts"


def _evaluate_expect(expect: dict | None, text: str, lines: list[str]) -> tuple[bool, list[str]]:
    if not expect:
        return True, []
    notes: list[str] = []
    for s in expect.get("contains_all") or []:
        if s not in text:
            notes.append(f"contains_all: missing {s!r}")
    any_of = expect.get("contains_any") or []
    if any_of and not any(s in text for s in any_of):
        notes.append(f"contains_any: none of {any_of!r}")
    for s in expect.get("not_contains") or []:
        if s in text:
            notes.append(f"not_contains: found {s!r}")
    if expect.get("reply_nonempty"):
        reply = _section(lines, "reply_text")
        if reply is None:
            notes.append("reply_nonempty: no reply_text block")
        elif not reply.strip():
            notes.append("reply_nonempty: reply_text is empty")
    answer_bans = expect.get("answer_not_contains") or []
    if answer_bans:
        answer = _section(lines, "answer")
        if answer is None:
            notes.append("answer_not_contains: no answer block")
        else:
            for s in answer_bans:
                if s in answer:
                    notes.append(f"answer_not_contains: found {s!r} in the answer")
    return not notes, notes


def _loaded_names(ps_json, lms_json) -> tuple[list[str], list[str]]:
    oll: list[str] = []
    if isinstance(ps_json, dict):
        for m in ps_json.get("models") or []:
            if isinstance(m, dict):
                oll.append(str(m.get("name") or m.get("model") or "?"))
    lms: list[str] = []
    if isinstance(lms_json, dict):
        for m in lms_json.get("data") or []:
            if isinstance(m, dict) and m.get("state") == "loaded":
                lms.append(str(m.get("id") or "?"))
    return oll, lms


def _save_api_bodies(n: int, sid: str, expected_model: str) -> str:
    """Write run<N>_<id>_api_ps.json and run<N>_<id>_lms_models.json; return a note on the expected model."""
    ps = _http("GET", OLLAMA_URL + "/api/ps", timeout=5.0)
    lm = _http("GET", LMS_URL + "/api/v0/models", timeout=5.0)
    for resp, url, suffix in ((ps, OLLAMA_URL + "/api/ps", "api_ps"), (lm, LMS_URL + "/api/v0/models", "lms_models")):
        path = DEMO_DIR / f"run{n}_{sid}_{suffix}.json"
        if resp["status"] == 200 and resp["text"]:
            body = resp["text"]
        else:
            body = json.dumps({"error": resp["error"] or f"HTTP {resp['status']}", "url": url,
                               "body": resp["text"][:2000]}, ensure_ascii=False, indent=1)
        path.write_text(body, encoding="utf-8")
    oll, lms = _loaded_names(ps["json"], lm["json"])
    want = expected_model.removesuffix(":latest")
    if any(x.removesuffix(":latest") == want for x in oll) or expected_model in lms:
        return f"expected_model {expected_model} loaded"
    return (f"expected_model {expected_model} NOT loaded (ollama: {oll or 'none'}"
            f"{'' if ps['status'] == 200 else ' [' + ps['error'] + ']'}; lms loaded: {lms or 'none'}"
            f"{'' if lm['status'] == 200 else ' [' + lm['error'] + ']'})")


def _prepare_histories(selected: list[dict]) -> list[str]:
    """Delete stale history files whose first reference in this run is a --save-history write (they are recreated
    by that step), so a later step never reads a previous run's chat when its producer failed."""
    first: dict[str, tuple[str, str]] = {}
    for s in selected:
        hf = s.get("history_file")
        if hf:
            first.setdefault(_normcase(_resolve(hf)), ("read", hf))
        _, _, flags, _ = parse_live_drive_args(s["live_drive_args"])
        sh = flags.get("--save-history")
        if isinstance(sh, str):
            first.setdefault(_normcase(_resolve(sh)), ("write", sh))
    removed = []
    for kind, p in first.values():
        path = _resolve(p)
        if kind == "write" and _under_demo(p) and path.is_file():
            try:
                path.unlink()
                removed.append(p)
            except OSError:
                pass
    return removed


def run_step(n: int, step: dict, port: int, produced: set[str]) -> dict:
    sid = step["id"]
    budget = int(step["budget_ms"])
    out_path = DEMO_DIR / f"run{n}_{sid}.txt"
    notes: list[str] = []
    segments: list[dict] = []
    attempts = None

    if not step["live_drive_args"]:
        out_path.write_text(f"# run {n} step {sid} at {_now_iso()}\n(view-only step: no API call)\n", encoding="utf-8")
        rec = {"run": n, "beat_id": sid, "wall_ms": 0, "budget_ms": budget, "over_budget": False, "attempts": None,
               "ok": True, "expect_ok": True, "expect_notes": [], "note": "view-only step: no API call",
               "segments": []}
        if step.get("expected_model"):
            rec["note"] += "; " + _save_api_bodies(n, sid, step["expected_model"])
        return rec

    cmd = _step_command(step, port)
    hf = step.get("history_file")
    if hf:
        notes.append("history from this run" if _normcase(_resolve(hf)) in produced
                     else "history_file from an earlier run (on disk)")
    hard_ms = max(3 * budget, 120000)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    lines: list[str] = []
    lock = threading.Lock()
    timed_out = False
    rc = None
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# run {n} step {sid} started {_now_iso()}\n# cmd: {subprocess.list2cmdline(cmd)}\n"
                f"# budget {budget} ms, hard timeout {hard_ms} ms\n")
        f.flush()
        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as e:
            f.write(f"# could not start: {e}\n")
            return {"run": n, "beat_id": sid, "wall_ms": 0, "budget_ms": budget, "over_budget": False,
                    "attempts": None, "ok": False, "expect_ok": False, "expect_notes": ["step did not start"],
                    "note": f"could not start live_drive.py: {e}", "segments": []}

        def reader() -> None:
            try:
                for line in proc.stdout:
                    t_ms = int((time.perf_counter() - t0) * 1000)
                    text = line.rstrip("\r\n")
                    with lock:
                        lines.append(text)
                        m = LABEL_RE.match(text)
                        if m:
                            segments.append({"label": m.group(1), "t_ms": t_ms})
                            f.write(f"[+{t_ms / 1000:.3f} s] {text}\n")
                        else:
                            f.write(text + "\n")
                        f.flush()
            except (ValueError, OSError):
                pass

        th = threading.Thread(target=reader, name=f"rehearse-{sid}", daemon=True)
        th.start()
        try:
            rc = proc.wait(timeout=hard_ms / 1000.0)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()                       # only this child
            try:
                rc = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                rc = None
        except KeyboardInterrupt:
            proc.kill()
            raise
        wall_ms = int((time.perf_counter() - t0) * 1000)
        th.join(timeout=15)
        with lock:
            f.write(f"# ended {_now_iso()}: exit {rc}, wall {wall_ms} ms{', TIMED OUT (killed)' if timed_out else ''}\n")
            snapshot = list(lines)

    text = "\n".join(snapshot)
    has_tb = "Traceback" in text
    ok = (not timed_out) and rc == 0 and not has_tb
    if timed_out:
        notes.append(f"hard timeout after {hard_ms} ms: killed PID {proc.pid}")
    elif rc != 0:
        notes.append(f"exit code {rc}")
    if has_tb:
        tail = [ln for ln in snapshot if ln.strip()]
        notes.append("Traceback in output: " + _excerpt(tail[-1] if tail else "", 200))
    cmd_name = step["live_drive_args"][0]
    if cmd_name in DECIDE_COMMANDS:
        attempts, js, why = _attempts(snapshot)
        if why:
            notes.append(why)
        if isinstance(js, dict):
            if js.get("error"):
                notes.append("decide error: " + _excerpt(js.get("error"), 160))
            verdict = js.get("verdict") or js.get("choice")
            if verdict is not None:
                notes.append(f"verdict {verdict}, confidence {js.get('confidence')}, "
                             f"cited {js.get('cited_decisions') or js.get('chunk_ids') or []}")
        say = _section(snapshot, "say_it")
        if "--say" in step["live_drive_args"]:
            if say is None:
                notes.append("no say_it block")
            elif say.strip().startswith(("Error:", "(run B1")):
                notes.append("say_it failed: " + _excerpt(say, 160))
    if cmd_name == "ask":
        reply = _section(snapshot, "reply_text")
        if reply is not None:
            notes.append(f"reply {len(reply.strip())} chars")
    if "**Error:**" in text:
        err_line = next((ln for ln in snapshot if "**Error:**" in ln), "")
        notes.append("app reported an error: " + _excerpt(err_line, 200))
    if "skipped: TWIN_NO_WARM=1" in text:
        notes.append("app runs with TWIN_NO_WARM=1 (warm skipped)")
    expect_ok, expect_notes = _evaluate_expect(step.get("expect"), text, snapshot)
    if step.get("expected_model"):
        notes.append(_save_api_bodies(n, sid, step["expected_model"]))
    return {"run": n, "beat_id": sid, "wall_ms": wall_ms, "budget_ms": budget, "over_budget": wall_ms > budget,
            "attempts": attempts, "ok": ok, "expect_ok": expect_ok, "expect_notes": expect_notes,
            "note": "; ".join(notes), "segments": segments}


def run_mode(a) -> int:
    beats_path = _resolve(a.beats)
    data, err = _load_beats(beats_path)
    if err:
        print(f"ERROR {err}")
        return 1
    steps, selected, errors, warnings = validate_beats(data, a.only, a.include_optional)
    for w in warnings:
        print(f"WARNING {w}")
    if errors:
        for e in errors:
            print(f"ERROR {e}")
        print(f"run refused: {len(errors)} validation error(s); fix the beats file (see --dry-run)")
        return 1
    n = int(a.run)
    if n < 1:
        print("ERROR --run N must be >= 1")
        return 1
    port = _resolve_port(a.port)
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DEMO_DIR / f"rehearsal_run{n}.log"
    summary_path = DEMO_DIR / f"run{n}_summary.json"
    # Never overwrite the evidence of an earlier attempt: every retry uses a new N.
    if not a.only:
        log_has_lines = log_path.is_file() and log_path.stat().st_size > 0
        if summary_path.exists() or log_has_lines:
            print(f"ERROR run {n} already has evidence ({_rel(summary_path) if summary_path.exists() else _rel(log_path)}); "
                  f"a full run would overwrite it. Use a new run number (--run {n + 1} or higher).")
            return 1
    else:
        clash = [s["id"] for s in selected if (DEMO_DIR / f"run{n}_{s['id']}.txt").exists()]
        if clash:
            print(f"ERROR run {n} already has output for {', '.join(clash)} (run{n}_<id>.txt); re-running would "
                  f"overwrite it. Use a new run number (--run {n + 1} or higher).")
            return 1
        if summary_path.exists():
            summary_path = DEMO_DIR / f"run{n}_only_{datetime.now().strftime('%Y%m%d-%H%M%S')}_summary.json"
    if not a.only:
        log_path.write_text("", encoding="utf-8")
    removed = _prepare_histories(selected)
    started = _now_iso()
    scores_before = _sha256(SCORES_PATH)
    files_before = _data_files()
    app = _http("GET", f"http://127.0.0.1:{port}/", timeout=5.0)
    app_ok = app["status"] == 200
    print(f"[run {n}] {len(selected)} steps from {_rel(beats_path)} on port {port}; app "
          f"{'reachable (HTTP 200)' if app_ok else 'NOT reachable: ' + (app['error'] or str(app['status']))}"
          + (f"; removed stale history files {removed}" if removed else ""))
    sys.stdout.flush()

    records: list[dict] = []
    produced: set[str] = set()
    t_run = time.perf_counter()
    for step in selected:
        if step["forbidden"]:        # never reachable: validate_beats never selects one
            continue
        rec = run_step(n, step, port, produced)
        with open(log_path, "a", encoding="utf-8", newline="\n") as lf:
            lf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            lf.flush()
        records.append(rec)
        _, _, flags, _ = parse_live_drive_args(step["live_drive_args"])
        if rec["ok"] and isinstance(flags.get("--save-history"), str):
            produced.add(_normcase(_resolve(flags["--save-history"])))
        line = (f"[run {n}] {rec['beat_id']} {'ok' if rec['ok'] else 'FAIL'} "
                f"{'expect_ok' if rec['expect_ok'] else 'expect_FAIL'} {rec['wall_ms'] / 1000:.1f} s / budget "
                f"{rec['budget_ms'] / 1000:.0f} s" + (" OVER BUDGET" if rec["over_budget"] else "")
                + (f" attempts {rec['attempts']}" if rec["attempts"] is not None else ""))
        if rec["note"]:
            line += f" | {_excerpt(rec['note'], 240)}"
        if rec["expect_notes"]:
            line += f" | expect: {_excerpt('; '.join(rec['expect_notes']), 240)}"
        print(line)
        sys.stdout.flush()
    elapsed_ms = int((time.perf_counter() - t_run) * 1000)

    act_deleted = False
    act_note = ""
    if ACT_ANSWER_PATH.exists():
        try:
            ACT_ANSWER_PATH.unlink()
            act_deleted = True
        except OSError as e:
            act_note = f"could not delete data/act_answer.txt: {e}"
    scores_after = _sha256(SCORES_PATH)
    files_after = _data_files()
    new_files = [p for p in files_after if p not in set(files_before)]
    baseline_new = None
    try:
        baseline = set(BASELINE_DATA_LIST.read_text(encoding="utf-8-sig").split())
        baseline_new = [p for p in files_after if p not in baseline]
    except OSError:
        pass
    pre_sha = None
    try:
        pre_sha = json.loads(PRE_SNAPSHOT.read_text(encoding="utf-8-sig")).get("scores_json_sha256")
    except (OSError, ValueError, AttributeError):
        pass
    scores_unchanged = scores_before is not None and scores_before == scores_after
    summary = {
        "run": n,
        "steps": len(records),
        "total_ms": sum(r["wall_ms"] for r in records),
        "ok_count": sum(1 for r in records if r["ok"]),
        "expect_ok_count": sum(1 for r in records if r["expect_ok"]),
        "scores_unchanged": scores_unchanged,
        "act_answer_deleted": act_deleted,
        "new_data_files": new_files,
        # extras for the Rehearse / Review stages
        "act_answer_absent": not ACT_ANSWER_PATH.exists(),
        "act_answer_note": act_note,
        "new_data_files_vs_baseline": baseline_new,
        "scores_sha256_before": scores_before,
        "scores_sha256_after": scores_after,
        "scores_matches_pre_snapshot": (None if pre_sha is None else str(pre_sha).upper() == (scores_after or "")),
        "step_ids": [r["beat_id"] for r in records],
        "failed_steps": [r["beat_id"] for r in records if not r["ok"]],
        "expect_failed_steps": [r["beat_id"] for r in records if not r["expect_ok"]],
        "over_budget_steps": [r["beat_id"] for r in records if r["over_budget"]],
        "elapsed_ms": elapsed_ms,
        "port": port,
        "app_reachable_at_start": app_ok,
        "beats": _rel(beats_path),
        "selection": {"only": a.only, "include_optional": bool(a.include_optional)},
        "removed_stale_history": removed,
        "log": _rel(log_path),
        "started_at": started,
        "finished_at": _now_iso(),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[run {n}] done: ok {summary['ok_count']}/{summary['steps']}, expect_ok "
          f"{summary['expect_ok_count']}/{summary['steps']}, total {summary['total_ms'] / 1000:.1f} s "
          f"(elapsed {elapsed_ms / 1000:.1f} s), scores.json {'unchanged' if scores_unchanged else 'CHANGED'}, "
          f"act_answer.txt {'deleted' if act_deleted else 'not present'}, new data files: {new_files or 'none'}")
    if new_files:
        print(f"WARNING new files in data/: {new_files}")
    print(f"[run {n}] summary: {_rel(summary_path)}; log: {_rel(log_path)}")
    return 0 if (summary["ok_count"] == summary["steps"] and scores_unchanged) else 1


# =================================================================================================================
# --check-profile (imports twin with TWIN_NO_WARM=1; file reads only)
# =================================================================================================================
def check_profile_mode() -> int:
    os.environ["TWIN_NO_WARM"] = "1"
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    sys.dont_write_bytecode = True
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    result = {"profile_path": None, "profile_sha": None, "profile_name": None, "using_example_profile": None,
              "lint_ok": False, "lint_issues": [], "lint_warnings": [], "lint_summary": [], "stale_indexes": [],
              "stale_sources": [], "digest_state": "unknown", "header_warnings": [], "ok": False}

    def emit(code: int) -> int:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return code

    import contextlib
    try:
        with contextlib.redirect_stdout(sys.stderr):     # keep stdout pure JSON
            from twin import config, index
            from twin import profile as profile_mod
            from twin.ui import state
    except Exception as e:  # noqa: BLE001
        result["lint_issues"].append(f"import failed: {type(e).__name__}: {e}")
        return emit(1)

    with contextlib.redirect_stdout(sys.stderr):
        state.load_app_profile()                          # exactly what the app does at build time
        prof = state.PROFILE
        result["using_example_profile"] = not config.PROFILE_PATH.exists()
        if prof is None:
            result["lint_issues"].append(f"profile could not be loaded: {state.PROFILE_ERROR}")
            result["header_warnings"] = state._profile_warnings()
            ok_code = 1
        else:
            ok_code = None
            result["profile_path"] = str(prof.path)
            result["profile_sha"] = prof.sha
            result["profile_name"] = prof.name
            digest_text, digest_lint_state = profile_mod._digest_for(prof)
            report = profile_mod.lint(prof, digest_text)
            lines = profile_mod.lint_lines(prof, report, digest_lint_state)
            issues: list[str] = []
            if report["eval_chunks"]:
                issues.append(f"{report['eval_chunks']} Eval chunk(s) would be indexed (gold answers retrievable)")
            if report["changelog_chunks"]:
                issues.append(f"{report['changelog_chunks']} Changelog chunk(s) would be indexed")
            if report["missing_sections"]:
                issues.append("missing sections: " + ", ".join(report["missing_sections"]))
            if report["prefix_tokens"] > report["prefix_budget"]:
                issues.append(f"static prefix {report['prefix_tokens']} tokens exceeds the "
                              f"{report['prefix_budget']} budget")
            result["lint_issues"] = issues
            result["lint_warnings"] = list(report["warnings"])     # informational (politics gap, word band, ...)
            result["lint_summary"] = [ln for ln in lines if not ln.startswith(("chunks under", "WARNING"))]
            result["lint_ok"] = not issues
            result["stale_indexes"] = state._stale_indexes()
            stale_src: list[str] = []
            for key in index.INDEX_KEYS:
                try:
                    if index.is_stale_sources(key, prof):
                        stale_src.append(key)
                except Exception as e:  # noqa: BLE001
                    stale_src.append(f"{key} ({type(e).__name__})")
            result["stale_sources"] = stale_src
            n_chars, _dsha, fresh = state._digest_state()
            result["digest_state"] = "fresh" if fresh else ("missing" if not n_chars else "stale")
            result["header_warnings"] = state._profile_warnings()
    if ok_code is not None:
        return emit(ok_code)
    result["ok"] = bool(result["lint_ok"] and not result["stale_indexes"] and not result["stale_sources"]
                        and result["digest_state"] == "fresh")
    return emit(0 if result["ok"] else 1)


# =================================================================================================================
# --smoke (urllib only; twin is parsed, never imported)
# =================================================================================================================
def _ollama_chat_body(spec: dict, messages: list[dict], *, options=None, fmt=None, tools=None, num_predict=None,
                      images=None) -> dict:
    """The body twin/clients.py OllamaClient._chat_body builds (num_ctx fixed per model, keep_alive per model)."""
    msgs = [dict(m) for m in messages]
    if images:
        for m in reversed(msgs):
            if m.get("role") == "user":
                m["images"] = list(images)
                break
    opts = {**(spec.get("samplers") or {}), **(options or {}), "num_ctx": spec.get("num_ctx")}
    if num_predict is not None:
        opts["num_predict"] = num_predict
    body = {"model": spec["name"], "messages": msgs, "stream": False, "options": opts,
            "keep_alive": spec.get("keep_alive")}
    if spec.get("think") is False:
        body["think"] = False
    if fmt is not None:
        body["format"] = fmt
    if tools is not None:
        body["tools"] = tools
    return body


def _request_summary(body: dict) -> dict:
    out = {k: body[k] for k in ("model", "options", "keep_alive", "think", "stream", "temperature", "max_tokens",
                                "min_p", "top_k", "repeat_penalty") if k in body}
    if "format" in body:
        out["format"] = "json schema"
    if "tools" in body:
        out["tools"] = [((t.get("function") or {}).get("name")) for t in body["tools"]]
    if "input" in body:
        out["input"] = body["input"]
    msgs = body.get("messages") or []
    out["messages"] = [{"role": m.get("role"), "chars": len(str(m.get("content") or "")),
                        **({"images": len(m["images"])} if m.get("images") else {})} for m in msgs]
    return out


def _ollama_stats(res: dict, data) -> None:
    if not isinstance(data, dict):
        return
    if data.get("load_duration") is not None:
        res["load_duration_ms"] = round((data.get("load_duration") or 0) / 1e6, 1)
    if data.get("total_duration") is not None:
        res["server_total_ms"] = round((data.get("total_duration") or 0) / 1e6, 1)
    ec, ed = data.get("eval_count"), data.get("eval_duration")
    if ec:
        res["eval_tokens"] = ec
    if ec and ed:
        res["tokens_per_s"] = round(ec / (ed / 1e9), 1)


def _lms_state() -> tuple[dict | None, str]:
    r = _http("GET", LMS_URL + "/api/v0/models", timeout=5.0)
    if r["status"] != 200 or not isinstance(r["json"], dict):
        return None, r["error"] or f"HTTP {r['status']}"
    return r["json"], ""


def _lms_loaded(models: dict, lms_json: dict | None) -> tuple[list[str], list[str]]:
    """(chat ids loaded, embedding ids loaded) in LM Studio; unknown ids count as chat (like gpu.ensure)."""
    embed_names = {m["name"] for m in models.values() if m.get("runtime") == "lms" and m.get("kind") == "embed"}
    chat, emb = [], []
    for m in (lms_json or {}).get("data") or []:
        if isinstance(m, dict) and m.get("state") == "loaded":
            mid = str(m.get("id") or "")
            (emb if (mid in embed_names or m.get("type") == "embeddings") else chat).append(mid)
    return chat, emb


def _lms_unload_all() -> str:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    cli = base / "Programs" / "LM Studio" / "resources" / "app" / ".webpack" / "lms.exe"
    if not cli.exists():
        return f"lms CLI not found at {cli}"
    try:
        p = subprocess.run([str(cli), "unload", "--all"], input="y\n", text=True, capture_output=True, timeout=60,
                           encoding="utf-8", errors="replace")
        return f"lms unload --all: exit {p.returncode}: " + _excerpt((p.stdout or "") + " " + (p.stderr or ""), 200)
    except Exception as e:  # noqa: BLE001
        return f"lms unload --all failed: {type(e).__name__}: {e}"


def _ollama_ps_names() -> tuple[list[str] | None, str]:
    r = _http("GET", OLLAMA_URL + "/api/ps", timeout=5.0)
    if r["status"] != 200 or not isinstance(r["json"], dict):
        return None, r["error"] or f"HTTP {r['status']}"
    return [str(m.get("name") or m.get("model") or "") for m in r["json"].get("models") or [] if isinstance(m, dict)], ""


def _ollama_stop(name: str) -> str:
    r = _http("POST", OLLAMA_URL + "/api/generate", {"model": name, "keep_alive": 0}, timeout=60.0)
    return f"ollama keep_alive 0 {name}: " + ("ok" if r["status"] == 200 else (r["error"] or f"HTTP {r['status']}"))


def _is_big(models: dict, name: str) -> bool:
    n = name.removesuffix(":latest")
    for m in models.values():
        if m.get("name") in (name, n):
            return m.get("vram") in ("big", "huge")
    return True


def _smoke_one(key: str, spec: dict, prompts: dict) -> dict:
    res = {"key": key, "name": spec.get("name"), "runtime": spec.get("runtime"), "kind": spec.get("kind"),
           "num_ctx": spec.get("num_ctx"), "keep_alive": spec.get("keep_alive"), "think": spec.get("think"),
           "endpoint": None, "http_status": None, "load_duration_ms": None, "server_total_ms": None,
           "total_ms": None, "eval_tokens": None, "tokens_per_s": None, "excerpt": "", "dims": None,
           "pass": False, "note": "", "request": None}
    runtime, kind = spec.get("runtime"), spec.get("kind")
    notes: list[str] = []

    if runtime == "ollama" and kind == "embed":
        res["endpoint"] = OLLAMA_URL + "/api/embed"
        body = {"model": spec["name"], "input": ["search_query: " + SMOKE_QUESTION],
                "options": {"num_ctx": spec.get("num_ctx")}, "keep_alive": spec.get("keep_alive")}
        res["request"] = _request_summary(body)
        r = _http("POST", res["endpoint"], body, timeout=SMOKE_TIMEOUT_S)
        res["http_status"], res["total_ms"] = r["status"], round(r["wall_ms"], 1)
        data = r["json"] if isinstance(r["json"], dict) else {}
        _ollama_stats(res, data)
        emb = (data.get("embeddings") or [[]])
        res["dims"] = len(emb[0]) if emb and isinstance(emb[0], list) else 0
        res["pass"] = r["status"] == 200 and res["dims"] == 768
        if r["error"]:
            notes.append(r["error"])
        elif res["dims"] != 768:
            notes.append(f"expected 768 dims, got {res['dims']}")

    elif runtime == "ollama":
        res["endpoint"] = OLLAMA_URL + "/api/chat"
        kw: dict = {}
        if key == "llama32_1b":
            messages = [{"role": "system", "content": prompts["ROUTER_SYSTEM"]},
                        {"role": "user", "content": SMOKE_QUESTION}]
            kw = {"fmt": prompts["ROUTER_SCHEMA"], "options": {"temperature": 0}, "num_predict": 40}
        elif key == "llama32_3b":
            messages = [{"role": "system", "content": prompts["REWRITE_SYSTEM"]},
                        {"role": "user", "content": f"user: {SMOKE_QUESTION}\nassistant: That I work best when I "
                                                    "answer to myself.\nlatest: and do you regret it?"}]
            kw = {"options": {"temperature": 0}, "num_predict": 60}
        elif key == "qwen3_8k":
            schema = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["yes", "no"]},
                                                       "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
                      "required": ["verdict", "confidence"]}
            messages = [{"role": "system", "content": "Answer with JSON matching the schema and nothing else."},
                        {"role": "user", "content": "Would you take a three-month contract at double your usual rate "
                                                    "if it pauses your own product work? Answer yes or no with a "
                                                    "confidence from 0 to 1."}]
            kw = {"fmt": schema, "options": {"temperature": 0.2}, "num_predict": 100}
        elif key == "hermes3":
            tools = [t for t in prompts["AGENT_TOOLS"] if (t.get("function") or {}).get("name") == "get_datetime"]
            tools = tools or FALLBACK_PROMPTS["AGENT_TOOLS"]
            messages = [{"role": "user", "content": "What is the current local date and time? "
                                                    "Call the get_datetime tool."}]
            kw = {"tools": tools, "options": {"temperature": 0.3}, "num_predict": 200}
        elif kind == "vision":
            try:
                b64 = base64.b64encode(TEST_PHOTO.read_bytes()).decode("ascii")
            except OSError as e:
                res["note"] = f"cannot read {_rel(TEST_PHOTO)}: {e}"
                return res
            messages = [{"role": "user", "content": prompts["VISION_PROMPT"]}]
            kw = {"images": [b64], "options": {"temperature": 0.7}, "num_predict": 300}
            notes.append(f"image {_rel(TEST_PHOTO)} sent as-is ({TEST_PHOTO.stat().st_size} bytes; the app resizes "
                         "to <= 1024 px first)")
        else:
            messages = [{"role": "system", "content": "Reply in one short sentence."},
                        {"role": "user", "content": "Say hi."}]
            kw = {"num_predict": 40}
        body = _ollama_chat_body(spec, messages, **kw)
        res["request"] = _request_summary(body)
        r = _http("POST", res["endpoint"], body, timeout=SMOKE_TIMEOUT_S)
        res["http_status"], res["total_ms"] = r["status"], round(r["wall_ms"], 1)
        data = r["json"] if isinstance(r["json"], dict) else {}
        _ollama_stats(res, data)
        msg = data.get("message") or {}
        content = str(msg.get("content") or "")
        if r["error"]:
            notes.append(r["error"])
        if key == "hermes3":
            calls = msg.get("tool_calls") or []
            names = [((c.get("function") or {}).get("name")) for c in calls if isinstance(c, dict)]
            res["excerpt"] = _excerpt(("tool_calls: " + ", ".join(str(x) for x in names)) if calls else content)
            res["pass"] = r["status"] == 200 and bool(calls)
            if r["status"] == 200 and not calls:
                notes.append("no tool call")
        else:
            res["excerpt"] = _excerpt(content)
            res["pass"] = r["status"] == 200 and bool(content.strip())
            if r["status"] == 200 and not content.strip():
                notes.append(f"empty content (done_reason {data.get('done_reason')})")
            if key == "llama32_1b" and content.strip():
                try:
                    notes.append(f"intent {json.loads(content).get('intent')!r}")
                except (ValueError, AttributeError):
                    notes.append("router output is not JSON (the app would default to about_me)")
            if key == "qwen3_8k" and content.strip():
                try:
                    json.loads(content)
                    notes.append(f"valid JSON, done_reason {data.get('done_reason')}")
                except ValueError:
                    notes.append(f"content is not valid JSON (done_reason {data.get('done_reason')})")

    elif runtime == "lms" and kind == "embed":
        res["endpoint"] = LMS_URL + "/v1/embeddings"
        body = {"model": spec["name"], "input": ["search_query: how I talk to my mentor"]}
        res["request"] = _request_summary(body)
        r = _http("POST", res["endpoint"], body, timeout=SMOKE_TIMEOUT_S)
        res["http_status"], res["total_ms"] = r["status"], round(r["wall_ms"], 1)
        data = r["json"] if isinstance(r["json"], dict) else {}
        rows = data.get("data") or []
        vec = rows[0].get("embedding") if rows and isinstance(rows[0], dict) else None
        res["dims"] = len(vec) if isinstance(vec, list) else 0
        res["pass"] = r["status"] == 200 and res["dims"] == 768
        if r["error"]:
            notes.append(r["error"])
        elif res["dims"] != 768:
            notes.append(f"expected 768 dims, got {res['dims']}")

    elif runtime == "lms":
        res["endpoint"] = LMS_URL + "/v1/chat/completions"
        sam = spec.get("samplers") or {}
        body = {"model": spec["name"],
                "messages": [{"role": "system", "content": "You are Mara Ellison (a synthetic demo persona), replying "
                                                           "as yourself in a text chat. Output only your message, "
                                                           "first person, one or two sentences."},
                             {"role": "user", "content": "Long week?"}],
                "temperature": sam.get("temperature", 1.15), "max_tokens": 60, "stream": False}
        for k in ("min_p", "top_k", "repeat_penalty"):
            if k in sam:
                body[k] = sam[k]
        res["request"] = _request_summary(body)
        r = _http("POST", res["endpoint"], body, timeout=SMOKE_TIMEOUT_S)
        res["http_status"], res["total_ms"] = r["status"], round(r["wall_ms"], 1)
        data = r["json"] if isinstance(r["json"], dict) else {}
        choices = data.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = str((choices[0].get("message") or {}).get("content") or "")
        usage = data.get("usage") or {}
        ct = usage.get("completion_tokens")
        if ct:
            res["eval_tokens"] = ct
            if r["wall_ms"] > 0:
                res["tokens_per_s"] = round(ct / (r["wall_ms"] / 1000.0), 1)
                notes.append("tok/s from wall time (LM Studio /v1 reports no eval timing; includes any load)")
        res["excerpt"] = _excerpt(content)
        res["pass"] = r["status"] == 200 and bool(content.strip())
        if r["error"]:
            notes.append(r["error"])
        elif not content.strip():
            notes.append("empty content")
    else:
        notes.append(f"runtime {runtime!r} is not tested by the smoke test")
    res["note"] = "; ".join(notes)
    return res


def smoke_mode(a) -> int:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    models = load_config_models()
    lit = _module_literals(PROMPTS_PY)
    prompts = {k: lit.get(k, v) for k, v in FALLBACK_PROMPTS.items()}
    md_notes: list[str] = []
    if not models:
        md_notes.append(f"could not parse MODELS from {_rel(CONFIG_PY)}")
    for k in FALLBACK_PROMPTS:
        if k not in lit:
            md_notes.append(f"{k} not parsed from {_rel(PROMPTS_PY)}; used a built-in fallback")

    plan = list(SMOKE_PLAN)
    if a.models:
        wanted = [x.strip() for x in a.models.split(",") if x.strip()]
        known = [k for k, _, _ in SMOKE_PLAN]
        unknown = [w for w in wanted if w not in known]
        if unknown:
            print(f"ERROR unknown --models keys {unknown}; choose from {known}")
            return 1
        plan = [p for p in SMOKE_PLAN if p[0] in wanted]

    results: list[dict] = []
    actions: list[str] = []
    ollama_names_tested: list[str] = []
    started = _now_iso()
    ps_before = _http("GET", OLLAMA_URL + "/api/ps", timeout=5.0)
    lms_before, lms_err = _lms_state()
    print(f"[smoke] {len(plan)} models; Ollama /api/ps: "
          f"{ps_before['text'].strip() if ps_before['status'] == 200 else ps_before['error']}; LM Studio: "
          f"{'up' if lms_before is not None else 'DOWN (' + lms_err + ')'}")
    sys.stdout.flush()

    for key, contract_name, role in plan:
        spec = models.get(key)
        mapping_note = ""
        if spec is None and contract_name:
            alt = next((m for m in models.values() if m.get("name") == contract_name), None)
            if alt is not None:
                spec = alt
                mapping_note = f"contract key {key} not in twin/config.py MODELS; used entry {alt['key']}"
        if spec is None:
            res = {"key": key, "name": contract_name, "role": role, "pass": False, "http_status": None,
                   "note": f"{key} ({contract_name or role}) is not in twin/config.py MODELS", "excerpt": "",
                   "dims": None, "load_duration_ms": None, "total_ms": None, "tokens_per_s": None,
                   "runtime": None, "num_ctx": None, "keep_alive": None}
            results.append(res)
            md_notes.append(res["note"])
            print(f"[smoke] {key} FAIL: {res['note']}")
            continue
        if contract_name and spec.get("name") != contract_name:
            mapping_note = (mapping_note + "; " if mapping_note else "") + \
                f"contract names {contract_name!r}; twin/config.py has {spec.get('name')!r} (used the config entry)"
        if mapping_note:
            md_notes.append(f"{key}: {mapping_note}")

        # the swaps gpu.MANAGER.ensure would make before this model (one big model on the 8 GB GPU)
        if spec.get("vram") in ("big", "huge"):
            if spec.get("runtime") == "ollama":
                lms_json, _ = _lms_state()
                chat, _emb = _lms_loaded(models, lms_json)
                if chat:
                    actions.append(f"before {key}: LM Studio had {chat} loaded; " + _lms_unload_all())
            elif spec.get("runtime") == "lms":
                names, _ = _ollama_ps_names()
                for nm in names or []:
                    if _is_big(models, nm):
                        actions.append(f"before {key}: " + _ollama_stop(nm))
        if spec.get("runtime") == "lms":
            lms_json, err = _lms_state()
            if lms_json is None:
                res = {"key": key, "name": spec.get("name"), "role": role, "runtime": "lms",
                       "num_ctx": spec.get("num_ctx"), "keep_alive": spec.get("keep_alive"), "pass": False,
                       "http_status": None, "excerpt": "", "dims": None, "load_duration_ms": None, "total_ms": None,
                       "tokens_per_s": None,
                       "note": f"LM Studio server down ({err}); run scripts/demo_prep.ps1 (it starts the server)"}
                results.append(res)
                print(f"[smoke] {key} FAIL: {res['note']}")
                continue
            was_loaded = any(isinstance(m, dict) and m.get("id") == spec.get("name") and m.get("state") == "loaded"
                             for m in lms_json.get("data") or [])
        print(f"[smoke] {key} ({spec.get('name')}) ...", end=" ")
        sys.stdout.flush()
        res = _smoke_one(key, spec, prompts)
        res["role"] = role
        if spec.get("runtime") == "lms":
            res["note"] = ((res["note"] + "; ") if res["note"] else "") + \
                f"{'already loaded' if was_loaded else 'not loaded before the call (JIT load included)'}"
        if spec.get("runtime") == "ollama":
            ollama_names_tested.append(spec["name"])
        if mapping_note:
            res["note"] = ((res["note"] + "; ") if res["note"] else "") + mapping_note
        results.append(res)
        print(f"{'PASS' if res['pass'] else 'FAIL'} HTTP {res.get('http_status')} {res.get('total_ms')} ms"
              + (f", load {res['load_duration_ms']} ms" if res.get("load_duration_ms") is not None else "")
              + (f", {res['tokens_per_s']} tok/s" if res.get("tokens_per_s") else "")
              + (f", {res['dims']} dims" if res.get("dims") else "")
              + (f" | {res['excerpt'][:80]}" if res.get("excerpt") else "")
              + (f" | {res['note'][:160]}" if res.get("note") else ""))
        sys.stdout.flush()

    # leave the GPU free: unload what the smoke test loaded
    names, err = _ollama_ps_names()
    tested = {n.removesuffix(":latest") for n in ollama_names_tested}
    if names is None:
        for nm in ollama_names_tested:
            actions.append("cleanup: " + _ollama_stop(nm))
    else:
        for nm in names:
            if nm.removesuffix(":latest") in tested:
                actions.append("cleanup: " + _ollama_stop(nm))
    if any(p[0] in ("stheno_q4", "nomic_lms") for p in plan):
        lms_json, _ = _lms_state()
        chat, emb = _lms_loaded(models, lms_json)
        if chat or emb:
            actions.append(f"cleanup: LM Studio had {chat + emb} loaded; " + _lms_unload_all())
    ps_after = _http("GET", OLLAMA_URL + "/api/ps", timeout=5.0)
    lms_after, _ = _lms_state()
    all_pass = bool(results) and all(r.get("pass") for r in results)

    payload = {"run_at": started, "finished_at": _now_iso(), "all_pass": all_pass,
               "passed": sum(1 for r in results if r.get("pass")), "total": len(results),
               "ollama_url": OLLAMA_URL, "lms_url": LMS_URL,
               "config_source": f"{_rel(CONFIG_PY)} MODELS and {_rel(PROMPTS_PY)} literals, parsed with ast "
                                "(not imported)",
               "results": results, "actions": actions, "notes": md_notes,
               "api_ps_before": ps_before["text"] if ps_before["status"] == 200 else ps_before["error"],
               "api_ps_after": ps_after["text"] if ps_after["status"] == 200 else ps_after["error"],
               "lms_loaded_after": _lms_loaded(models, lms_after) if lms_after is not None else "LM Studio down"}
    (DEMO_DIR / "model_smoke.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def cell(v) -> str:
        return "" if v is None else str(v).replace("|", "\\|").replace("\n", " ")

    md = [f"# Model smoke test ({started})", "",
          "Direct calls to the local servers, bypassing the app: `python scripts/demo_rehearse.py --smoke`. "
          f"Model names, num_ctx, keep_alive, think and samplers are parsed from `{_rel(CONFIG_PY)}` (not imported); "
          "each request has the shape `twin/clients.py` sends for that model.", "",
          f"Result: **{'PASS' if all_pass else 'FAIL'}** ({payload['passed']}/{payload['total']} models)", "",
          "| # | key | model | runtime | role | num_ctx | keep_alive | HTTP | load ms | total ms | tok/s | "
          "reply excerpt / dims | pass | note |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        shown = f"{r['dims']} dims" if r.get("dims") else r.get("excerpt")
        md.append(f"| {i} | `{cell(r.get('key'))}` | `{cell(r.get('name'))}` | {cell(r.get('runtime'))} | "
                  f"{cell(r.get('role'))} | {cell(r.get('num_ctx'))} | {cell(r.get('keep_alive'))} | "
                  f"{cell(r.get('http_status'))} | {cell(r.get('load_duration_ms'))} | {cell(r.get('total_ms'))} | "
                  f"{cell(r.get('tokens_per_s'))} | {cell(shown)} | {'PASS' if r.get('pass') else 'FAIL'} | "
                  f"{cell(r.get('note'))} |")
    md += ["", "## Notes", "",
           "- The contract's \"llama3.2 router model\" is `llama32_1b` (`llama3.2:1b`) in twin/config.py; "
           "`llama32_3b` (`llama3.2:3b`, the follow-up rewrite in B4.2) is tested too. The See tab's vision model "
           "is `qwen35_vision`.",
           "- load ms is Ollama's load_duration; LM Studio reports none (the note says whether the model was "
           "already loaded). tok/s is eval_count / eval_duration for Ollama.",
           "- Before each big model the test makes the swap gpu.MANAGER.ensure makes (Ollama big model: unload "
           "LM Studio chat models; LM Studio chat model: stop big Ollama models); at the end it unloads what it "
           "loaded (keep_alive 0 on the same Ollama names, `lms unload --all`)."]
    md += [f"- {n}" for n in md_notes]
    if actions:
        md += ["", "## Swap and cleanup actions", ""] + [f"- {cell(x)}" for x in actions]
    md += ["", f"Ollama /api/ps after: `{cell(payload['api_ps_after']).strip()}`", ""]
    (DEMO_DIR / "model_smoke.md").write_text("\n".join(md), encoding="utf-8")
    print(f"[smoke] {'PASS' if all_pass else 'FAIL'} {payload['passed']}/{payload['total']}; wrote "
          f"{_rel(DEMO_DIR / 'model_smoke.json')} and {_rel(DEMO_DIR / 'model_smoke.md')}")
    return 0 if all_pass else 1


# =================================================================================================================
# CLI
# =================================================================================================================
def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(prog="python scripts/demo_rehearse.py",
                                 description="PLAN_DEMO Session B: rehearse beats, check the profile, smoke-test models.")
    ap.add_argument("--run", type=int, metavar="N", help="rehearsal run number: run the selected steps")
    ap.add_argument("--check-profile", action="store_true", help="profile lint + index/digest freshness (no models)")
    ap.add_argument("--smoke", action="store_true", help="test every demo model directly against the local servers")
    ap.add_argument("--dry-run", action="store_true", help="validate the beats file and list the steps; no app contact")
    ap.add_argument("--port", type=int, help="app port (default: scripts/dev/demo/app.port, else 7861)")
    ap.add_argument("--beats", default=DEFAULT_BEATS, help=f"beats file (default {DEFAULT_BEATS})")
    ap.add_argument("--only", metavar="ID,ID", help="run exactly these step ids in file order (optional ones too)")
    ap.add_argument("--include-optional", action="store_true", help="also run optional steps")
    ap.add_argument("--models", metavar="KEY,KEY", help="--smoke: only these twin/config.py keys")
    a = ap.parse_args(argv)

    modes = [m for m, on in (("--check-profile", a.check_profile), ("--smoke", a.smoke),
                             ("--run/--dry-run", a.run is not None or a.dry_run)) if on]
    if len(modes) != 1:
        ap.print_usage()
        print("choose exactly one of --run N, --dry-run, --check-profile, --smoke" +
              (f" (got {', '.join(modes)})" if modes else ""))
        return 2
    if a.check_profile:
        return check_profile_mode()
    if a.smoke:
        return smoke_mode(a)
    if a.dry_run:
        return dry_run_mode(a)
    return run_mode(a)


if __name__ == "__main__":
    raise SystemExit(main())
