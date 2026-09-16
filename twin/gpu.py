"""ModelManager: sequences GPU loads between LM Studio and Ollama (plan section 4 rules 1-3)."""
from __future__ import annotations

import contextlib
import re
import subprocess
import sys
import threading

from . import clients, config
from .config import by_name, spec

TAB_MODEL = {"ask": "stheno_q4", "decide": "qwen3_8k", "act": "hermes3", "see": "qwen35_vision"}


def _darwin_memory_line() -> str:
    """`<used> MiB, <total> MiB, unified` from sysctl and vm_stat. Apple Silicon has no separate VRAM: models
    live in the same memory the OS reports, and used is active + wired + compressor pages (Activity Monitor's
    "Memory Used"). Returns '' when either command fails."""
    try:
        total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                   timeout=10, check=True).stdout.strip())
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10, check=True).stdout
    except Exception:  # noqa: BLE001
        return ""
    page_match = re.search(r"page size of (\d+) bytes", out)
    page = int(page_match.group(1)) if page_match else 4096
    pages = 0
    for label in ("Pages active", "Pages wired down", "Pages occupied by compressor"):
        m = re.search(rf"{label}:\s+(\d+)", out)
        pages += int(m.group(1)) if m else 0
    return f"{pages * page // 1048576} MiB, {total // 1048576} MiB, unified"


def gpu_line() -> str:
    """One-line accelerator reading for the Status tab: nvidia-smi's `used, total, utilization` where that
    exists, the unified-memory equivalent on macOS, '' when neither can be read."""
    if sys.platform == "darwin":
        return _darwin_memory_line()
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _is_big_ollama(entry: dict) -> bool:
    name = entry.get("name") or entry.get("model") or ""
    s = by_name(name) or by_name(entry.get("model") or "")
    if s is None:
        return True  # unknown names are treated as big
    return s.vram in ("big", "huge")


class ModelManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.active_tab: str | None = None
        self.last_model_tab: str | None = None      # last active tab that has a model (for "warm active")
        self.tab_overrides: dict[str, str] = {}      # per-tab model override, e.g. ask -> stheno_q8 (Q8 toggle)
        self._heartbeat: threading.Thread | None = None
        self.busy: bool = False                      # True while session() or warm() holds the GPU
        self.busy_key: str | None = None             # the model key of that session/warm
        self._busy_stack: list[str] = []             # nested session/warm keys (RLock re-entry)

    # ---- busy flag (status strip) ------------------------------------------------------
    def _enter_busy(self, key: str) -> None:
        self._busy_stack.append(key)
        self.busy = True
        self.busy_key = key

    def _exit_busy(self) -> None:
        if self._busy_stack:
            self._busy_stack.pop()
        self.busy = bool(self._busy_stack)
        self.busy_key = self._busy_stack[-1] if self._busy_stack else None

    # ---- rules ------------------------------------------------------------
    def ensure(self, key: str) -> None:
        s = spec(key)
        if s.runtime == "lms" and s.vram in ("big", "huge"):
            try:
                entries = clients.ollama.ps()
            except Exception:  # noqa: BLE001
                entries = []
            for e in entries:
                if _is_big_ollama(e):
                    name = e.get("name") or e.get("model")
                    try:
                        clients.ollama.stop(name)
                    except Exception:  # noqa: BLE001
                        pass
        elif s.runtime == "ollama" and s.vram in ("big", "huge"):
            try:
                loaded = clients.lms.loaded()
            except Exception:  # noqa: BLE001
                loaded = []
            chat_loaded = False
            for mid in loaded:
                ms = by_name(mid)
                if ms is None or ms.kind != "embed":
                    chat_loaded = True
            if chat_loaded:
                try:
                    clients.lms.unload_all()
                except Exception:  # noqa: BLE001
                    pass
        # small ollama, lms embed, anthropic: nothing

    def warm(self, key: str) -> None:
        s = spec(key)
        with self.lock:
            self._enter_busy(key)
            try:
                self.ensure(key)
                if s.runtime == "ollama":
                    clients.ollama.warm(key)
                elif s.runtime == "lms" and s.kind == "embed":
                    clients.lms.embed(key, ["warm"], tab="warm")
                elif s.runtime == "lms":
                    clients.lms.chat(key, [{"role": "user", "content": "hi"}], max_tokens=1, tab="warm")
            finally:
                self._exit_busy()

    @contextlib.contextmanager
    def session(self, key: str, tab: str = ""):
        self.lock.acquire()
        self._enter_busy(key)
        try:
            self.ensure(key)
            yield
        finally:
            self._exit_busy()
            self.lock.release()

    def free_all(self) -> list[str]:
        done = []
        with self.lock:
            try:
                for e in clients.ollama.ps():
                    name = e.get("name") or e.get("model")
                    try:
                        clients.ollama.stop(name)
                        done.append(f"ollama stop {name}")
                    except Exception as ex:  # noqa: BLE001
                        done.append(f"ollama stop {name} failed: {ex}")
            except Exception as ex:  # noqa: BLE001
                done.append(f"ollama ps failed: {ex}")
            try:
                out = clients.lms.unload_all()
                done.append("lms unload --all: " + " ".join(out.split())[:200])
            except Exception as ex:  # noqa: BLE001
                done.append(f"lms unload failed: {ex}")
        return done

    def set_active_tab(self, tab: str) -> None:
        self.active_tab = (tab or "").lower()
        if self.active_tab in TAB_MODEL:
            self.last_model_tab = self.active_tab

    def set_tab_model(self, tab: str, key: str | None) -> None:
        """Override the model a tab uses (the Ask Q8 toggle); None or the default restores TAB_MODEL."""
        tab = (tab or "").lower()
        if key and key != TAB_MODEL.get(tab):
            self.tab_overrides[tab] = key
        else:
            self.tab_overrides.pop(tab, None)

    def tab_key(self, tab: str | None) -> str | None:
        """Model key for a tab: the override when set, else TAB_MODEL."""
        tab = (tab or "").lower()
        return self.tab_overrides.get(tab) or TAB_MODEL.get(tab)

    def active_key(self) -> str | None:
        return self.tab_key(self.active_tab)

    def heartbeat_tick(self) -> str | None:
        """One heartbeat: re-warm the active tab's model (override-aware); returns the key warmed or None.
        Does nothing (returns None) while TWIN_NO_WARM is set."""
        if config.no_warm():
            return None
        key = self.active_key()
        if not key:
            return None
        if not self.lock.acquire(blocking=False):
            return None
        try:
            self.warm(key)
            return key
        except Exception:  # noqa: BLE001
            return None
        finally:
            self.lock.release()

    def start_heartbeat(self, interval_s: int = 240) -> None:
        """Start the re-warm thread once; with TWIN_NO_WARM set no thread is created at all."""
        if config.no_warm():
            return
        if self._heartbeat is not None and self._heartbeat.is_alive():
            return

        def loop():
            while True:
                threading.Event().wait(interval_s)
                self.heartbeat_tick()

        self._heartbeat = threading.Thread(target=loop, name="twin-heartbeat", daemon=True)
        self._heartbeat.start()

    def status(self) -> dict:
        try:
            ps = clients.ollama.ps()
        except Exception as ex:  # noqa: BLE001
            ps = [{"error": str(ex)}]
        try:
            tags = clients.ollama.tags()
        except Exception as ex:  # noqa: BLE001
            tags = [{"error": str(ex)}]
        try:
            lm = clients.lms.models_v0()
        except Exception as ex:  # noqa: BLE001
            lm = [{"error": str(ex)}]
        try:
            lm_v1 = clients.lms.models_v1()
        except Exception as ex:  # noqa: BLE001
            lm_v1 = [f"error: {ex}"]
        return {"ollama_ps": ps, "ollama_tags": tags, "lms_models": lm, "lms_v1_ids": lm_v1,
                "gpu": gpu_line(), "active_tab": self.active_tab, "active_key": self.active_key(),
                "tab_overrides": dict(self.tab_overrides), "busy": self.busy, "busy_key": self.busy_key}


MANAGER = ModelManager()
