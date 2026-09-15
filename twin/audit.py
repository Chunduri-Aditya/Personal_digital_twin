"""Audit log (docs/PLAN_UNIFIED.md 3.6): one JSON line per model-backed request in data/audit.jsonl.

The request TEXT is never written: only its sha256, the tab, the condition, the chunk ids retrieved, the model
keys that ran and whether the call succeeded (callers must not put request text into `extra` either). Status
shows `tail()` and `counts_per_day()`; `scripts/delete_twin.ps1` removes the file. AUDIT_PATH is read at call
time through this module's name so tests can monkeypatch `twin.audit.AUDIT_PATH`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import AUDIT_PATH


def _path() -> Path:
    return Path(AUDIT_PATH)


def request_sha(request_text: str | None) -> str:
    return hashlib.sha256((request_text or "").encode("utf-8")).hexdigest()


def record(tab: str, condition: str, request_text: str | None, chunk_ids, model_keys, ok: bool,
           extra: dict | None = None) -> dict:
    """Append one line and return the entry written (the text itself is reduced to its sha256)."""
    now = datetime.now().astimezone()
    entry = {
        "ts": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "tab": str(tab or ""),
        "condition": str(condition or ""),
        "request_sha": request_sha(request_text),
        "chunk_ids": [str(c) for c in (chunk_ids or [])],
        "model_keys": [str(k) for k in (model_keys or [])],
        "ok": bool(ok),
        "extra": dict(extra or {}),
    }
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return entry


def _entries() -> list[dict]:
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def tail(n: int = 50) -> list[dict]:
    """The last `n` entries, oldest first (newest last)."""
    if n <= 0:
        return []
    return _entries()[-n:]


def counts_per_day(days: int = 14) -> list[tuple[str, int]]:
    """(date, count) for each day in the last `days` days (today included) that has entries, ascending."""
    start = date.today() - timedelta(days=max(int(days), 1) - 1)
    counts: dict[str, int] = {}
    for e in _entries():
        d = str(e.get("date") or str(e.get("ts") or "")[:10])
        try:
            when = date.fromisoformat(d)
        except ValueError:
            continue
        if when < start:
            continue
        counts[d] = counts.get(d, 0) + 1
    return sorted(counts.items())


def clear() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
