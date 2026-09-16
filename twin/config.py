"""Model registry, endpoints, CLI paths and data paths for the twin package."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

PROFILE_PATH = DATA_DIR / "twin_profile.md"
EXAMPLE_PROFILE_PATH = DATA_DIR / "twin_profile.example.md"          # phase-1 example ("Ari"), schema v1
EXAMPLE_PROFILE_V2_PATH = DATA_DIR / "twin_profile.example.v2.md"    # schema v2 example ("Mara Ellison")
DIGEST_PATH = DATA_DIR / "digest.md"
CHUNKS_PATH = DATA_DIR / "chunks.json"
EVAL_RESULTS_PATH = DATA_DIR / "eval_results.json"
TELEMETRY_PATH = DATA_DIR / "telemetry.jsonl"

# v2 (docs/PLAN_UNIFIED.md): interview transcript, redaction, reflections, audit, item bank, probes.
TRANSCRIPT_PATH = DATA_DIR / "interview_transcript.md"                       # real (user-supplied)
REDACTED_TRANSCRIPT_PATH = DATA_DIR / "interview_transcript.redacted.md"     # what the index reads
EXAMPLE_TRANSCRIPT_PATH = DATA_DIR / "interview_transcript.example.md"       # Mara, synthetic
EXAMPLE_REDACTED_TRANSCRIPT_PATH = DATA_DIR / "interview_transcript.example.redacted.md"
REDACTION_REPORT_PATH = DATA_DIR / "redaction_report.json"
REFLECTIONS_PATH = DATA_DIR / "reflections.md"                               # reflect.py draft (## <lens> blocks)
AUDIT_PATH = DATA_DIR / "audit.jsonl"
ITEMS_DIR = DATA_DIR / "items"
BANK_PATH = ITEMS_DIR / "bank.json"
SELF_ANSWERS_PATH = ITEMS_DIR / "self_answers.json"                          # wave 1 (real)
SELF_ANSWERS_RETEST_PATH = ITEMS_DIR / "self_answers_retest.json"            # wave 2 (real)
EXAMPLE_SELF_ANSWERS_PATH = ITEMS_DIR / "self_answers.example.json"          # Mara wave 1
EXAMPLE_SELF_ANSWERS_RETEST_PATH = ITEMS_DIR / "self_answers_retest.example.json"  # Mara wave 2
TWIN_ANSWERS_PATH = ITEMS_DIR / "twin_answers.json"                          # [sha][condition][item_id]
ITEM_SCORES_PATH = ITEMS_DIR / "scores.json"
PROBES_PATH = DATA_DIR / "probes.json"
DESIGN_TOKENS_PATH = PROJECT_ROOT / "docs" / "design" / "tokens.md"          # user-supplied Claude Design export
DEFAULT_DESIGN_TOKENS_PATH = PROJECT_ROOT / "docs" / "design" / "tokens.default.md"
STATIC_DIR = PROJECT_ROOT / "static"

NO_WARM_ENV = "TWIN_NO_WARM"
THEME_ENV = "TWIN_THEME"


def no_warm() -> bool:
    """True when TWIN_NO_WARM is set to anything but ''/'0'/'false'/'no'. Read at CALL time (never cached) so
    tests can toggle it; gates every warm path (tab-select pre-warm, heartbeat, /warm, /rebuild_*)."""
    return os.environ.get(NO_WARM_ENV, "").strip().lower() not in ("", "0", "false", "no")


def theme_pref() -> str:
    """'light' | 'dark' | '' from TWIN_THEME (anything else is '')."""
    v = os.environ.get(THEME_ENV, "").strip().lower()
    return v if v in ("light", "dark") else ""

OLLAMA_URL = os.environ.get("TWIN_OLLAMA_URL", "http://127.0.0.1:11434")
LMS_URL = os.environ.get("TWIN_LMS_URL", "http://127.0.0.1:1234")  # OpenAI base is LMS_URL + "/v1"

_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))


def _cli_path(env_var: str, windows: Path, unix_name: str, unix_default: Path) -> Path:
    """Where a vendor CLI lives: `env_var` wins, then the Windows installer path, then `unix_name` on PATH,
    then `unix_default`. Windows puts both CLIs under LOCALAPPDATA; macOS and Linux do not."""
    override = os.environ.get(env_var, "").strip()
    if override:
        return Path(override)
    if sys.platform == "win32":
        return windows
    found = shutil.which(unix_name)
    return Path(found) if found else unix_default


# LM Studio's CLI is the only one the code runs (LMSClient.unload_all). On macOS and Linux the app bootstraps
# it into ~/.lmstudio/bin, which is not on PATH by default.
LMS_CLI: Path = _cli_path(
    "TWIN_LMS_CLI",
    _LOCALAPPDATA / "Programs" / "LM Studio" / "resources" / "app" / ".webpack" / "lms.exe",
    "lms",
    Path.home() / ".lmstudio" / "bin" / "lms",
)
OLLAMA_CLI: Path = _cli_path(
    "TWIN_OLLAMA_CLI",
    _LOCALAPPDATA / "Programs" / "Ollama" / "ollama.exe",
    "ollama",
    Path("/usr/local/bin/ollama"),
)

ANTHROPIC_MODEL = "claude-sonnet-5"
STHENO_SAMPLERS = {"temperature": 1.15, "min_p": 0.075, "top_k": 50, "repeat_penalty": 1.1}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    runtime: str            # "ollama" | "lms" | "anthropic"
    kind: str               # "chat" | "embed" | "vision"
    vram: str               # "small" | "big" | "huge" | "none"
    num_ctx: int | None
    keep_alive: str | int | None
    think: bool | None
    samplers: dict = field(default_factory=dict)
    job: str = ""


def _m(key, name, runtime, kind, vram, num_ctx, keep_alive, think, samplers, job):
    return ModelSpec(key, name, runtime, kind, vram, num_ctx, keep_alive, think, dict(samplers), job)


MODELS: dict[str, ModelSpec] = {
    "stheno_q4": _m("stheno_q4", "l3-8b-stheno-v3.2", "lms", "chat", "big", None, None, None, STHENO_SAMPLERS,
                    "Voice: the twin's reply in Ask, Decide say-it, See reaction, Act polish"),
    "stheno_q8": _m("stheno_q8", "fluffy/l3-8b-stheno-v3.2:q8_0", "ollama", "chat", "huge", 8192, "10m", None,
                    STHENO_SAMPLERS, "Voice high-precision toggle (Q8_0, spills to CPU)"),
    "qwen3_8k": _m("qwen3_8k", "qwen3-8b-8k", "ollama", "chat", "big", 8192, "10m", False, {"temperature": 0.2},
                   "Decide B1/B2 structured JSON decisions"),
    "qwen3_long": _m("qwen3_long", "qwen3:8b", "ollama", "chat", "huge", 40960, 0, False, {"temperature": 0.3},
                     "One-shot profile digest at index build (40960 ctx)"),
    "hermes3": _m("hermes3", "hermes3:8b", "ollama", "chat", "big", 8192, "10m", None, {"temperature": 0.3},
                  "Act tab: native tool calling"),
    "qwen25": _m("qwen25", "qwen2.5:7b", "ollama", "chat", "big", 8192, "10m", None, {"temperature": 0.0},
                 "Consistency checker and second judge"),
    "llama31": _m("llama31", "llama3.1:8b", "ollama", "chat", "big", 8192, "10m", None, {"temperature": 0.0},
                  "Primary LLM judge for the voice bake-off"),
    "qwen35_vision": _m("qwen35_vision", "qwen3.5:4b-q8_0", "ollama", "vision", "big", 8192, "10m", False,
                        {"temperature": 0.7}, "See tab: image description"),
    "llama32_3b": _m("llama32_3b", "llama3.2:3b", "ollama", "chat", "small", 4096, "30m", None, {"temperature": 0.0},
                     "Follow-up query rewrite; fallback voice"),
    "llama32_1b": _m("llama32_1b", "llama3.2:1b", "ollama", "chat", "small", 4096, "30m", None, {"temperature": 0.0},
                     "Router: intent JSON"),
    "nomic_ollama": _m("nomic_ollama", "nomic-embed-text", "ollama", "embed", "small", 2048, "30m", None, {},
                       "Primary retrieval index"),
    "embeddinggemma": _m("embeddinggemma", "embeddinggemma:300m-qat-q4_0", "ollama", "embed", "small", 2048, "30m",
                         None, {}, "Second index for the retrieval bake-off"),
    "nomic_lms": _m("nomic_lms", "text-embedding-nomic-embed-text-v1.5", "lms", "embed", "small", None, None, None, {},
                    "Act tab search_profile embedder; third index"),
    "claude": _m("claude", ANTHROPIC_MODEL, "anthropic", "chat", "none", None, None, None, {"temperature": 0.0},
                 "Optional ceiling judge when ANTHROPIC_API_KEY is set"),
}


def spec(key: str) -> ModelSpec:
    return MODELS[key]


def by_name(name: str) -> ModelSpec | None:
    """Look up a spec by runtime model name. Ollama /api/ps and /api/tags report untagged
    models with a ':latest' suffix (e.g. 'nomic-embed-text:latest'), so that form matches too."""
    if not name:
        return None
    n = name.removesuffix(":latest")
    for s in MODELS.values():
        if s.name in (name, n):
            return s
    return None
