"""Ring buffer of model call records plus a JSONL log."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass

from .config import TELEMETRY_PATH


@dataclass
class CallRecord:
    ts: float
    tab: str
    model: str
    runtime: str
    load_ms: float
    prompt_tokens: int
    eval_tokens: int
    tok_s: float
    wall_ms: float
    ok: bool
    error: str = ""


_RECORDS: deque[CallRecord] = deque(maxlen=500)
_LOCK = threading.Lock()


def record(rec: CallRecord) -> None:
    with _LOCK:
        _RECORDS.append(rec)
        try:
            with open(TELEMETRY_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        except OSError:
            pass


def recent(n: int = 50) -> list[CallRecord]:
    with _LOCK:
        items = list(_RECORDS)
    return items[-n:]


def as_rows(n: int = 50) -> list[list]:
    rows = []
    for r in reversed(recent(n)):
        rows.append([
            time.strftime("%H:%M:%S", time.localtime(r.ts)),
            r.tab,
            r.model,
            round(r.load_ms, 1),
            r.prompt_tokens,
            r.eval_tokens,
            round(r.tok_s, 1),
            round(r.wall_ms, 1),
            r.ok,
        ])
    return rows
