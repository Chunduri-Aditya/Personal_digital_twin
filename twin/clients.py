"""Synchronous clients for Ollama, LM Studio and Anthropic. Every call records telemetry."""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Iterator

import httpx
import numpy as np

from . import telemetry
from .config import ANTHROPIC_MODEL, LMS_CLI, LMS_URL, OLLAMA_URL, spec
from .telemetry import CallRecord

_BATCH = 32


class OllamaError(RuntimeError):
    pass


def _rec(tab, model, runtime, t0, ok, error="", load_ms=0.0, prompt_tokens=0, eval_tokens=0, tok_s=0.0):
    telemetry.record(CallRecord(
        ts=time.time(), tab=tab, model=model, runtime=runtime, load_ms=float(load_ms),
        prompt_tokens=int(prompt_tokens), eval_tokens=int(eval_tokens), tok_s=float(tok_s),
        wall_ms=(time.perf_counter() - t0) * 1000.0, ok=ok, error=str(error)[:300],
    ))


def _ollama_stats(data: dict) -> dict:
    load_ms = data.get("load_duration", 0) / 1e6
    p = data.get("prompt_eval_count", 0) or 0
    e = data.get("eval_count", 0) or 0
    ed = data.get("eval_duration", 0) or 0
    tok_s = (e / (ed / 1e9)) if ed else 0.0
    return dict(load_ms=load_ms, prompt_tokens=p, eval_tokens=e, tok_s=tok_s)


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ---- chat -------------------------------------------------------------
    def _chat_body(self, key, messages, options, format, tools, num_predict, stream, images_on_last_user):
        s = spec(key)
        if s.runtime != "ollama":
            raise ValueError(f"{key!r} is a {s.runtime} model, not an Ollama model")
        msgs = [dict(m) for m in messages]
        if key == "stheno_q8" and not any(m.get("role") == "system" for m in msgs):
            raise ValueError("stheno_q8 requires a system message (built-in default has unfilled {{char}} placeholders)")
        if images_on_last_user:
            for m in reversed(msgs):
                if m.get("role") == "user":
                    m["images"] = list(images_on_last_user)
                    break
        # Rule 4: num_ctx is fixed per model; callers' options can never change it.
        opts = {**s.samplers, **(options or {}), "num_ctx": s.num_ctx}
        if num_predict is not None:
            opts["num_predict"] = num_predict
        body = {
            "model": s.name,
            "messages": msgs,
            "stream": bool(stream),
            "options": opts,
            "keep_alive": s.keep_alive,
        }
        if s.think is False:
            body["think"] = False
        if format is not None:
            body["format"] = format
        if tools is not None:
            body["tools"] = tools
        return s, body

    def chat(self, key, messages, *, options=None, format=None, tools=None, num_predict=None,
             stream=False, images_on_last_user=None, tab="") -> dict | Iterator[dict]:
        """Chat via /api/chat. `key` must be an Ollama registry key. `num_ctx` in `options` is ignored
        (rule 4: never vary num_ctx per model). `stheno_q8` MUST be given a system message: its built-in
        default system prompt contains unfilled {{char}}/{{user}} placeholders (ValueError otherwise)."""
        s, body = self._chat_body(key, messages, options, format, tools, num_predict, stream, images_on_last_user)
        if stream:
            return self._chat_stream(s, body, tab)
        t0 = time.perf_counter()
        try:
            r = self._http.post("/api/chat", json=body)
            if r.status_code >= 400:
                raise OllamaError(f"HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
        except OllamaError as e:
            _rec(tab, s.name, "ollama", t0, False, error=e)
            raise
        except Exception as e:  # noqa: BLE001
            _rec(tab, s.name, "ollama", t0, False, error=e)
            raise OllamaError(str(e)) from e
        _rec(tab, s.name, "ollama", t0, True, **_ollama_stats(data))
        return data

    def _chat_stream(self, s, body, tab) -> Iterator[dict]:
        t0 = time.perf_counter()
        final = None
        recorded = False
        try:
            try:
                with self._http.stream("POST", "/api/chat", json=body) as r:
                    if r.status_code >= 400:
                        r.read()
                        raise OllamaError(f"HTTP {r.status_code}: {r.text[:500]}")
                    for line in r.iter_lines():
                        if not line or not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("done"):
                            final = chunk
                        yield chunk
            except OllamaError as e:
                recorded = True
                _rec(tab, s.name, "ollama", t0, False, error=e)
                raise
            except Exception as e:  # noqa: BLE001
                recorded = True
                _rec(tab, s.name, "ollama", t0, False, error=e)
                raise OllamaError(str(e)) from e
            recorded = True
            _rec(tab, s.name, "ollama", t0, True, **(_ollama_stats(final) if final else {}))
        finally:
            if not recorded:  # consumer stopped iterating early (GeneratorExit)
                _rec(tab, s.name, "ollama", t0, False, error="stream abandoned",
                     **(_ollama_stats(final) if final else {}))

    # ---- embed ------------------------------------------------------------
    def embed(self, key, inputs: list[str], tab="") -> np.ndarray:
        s = spec(key)
        if s.runtime != "ollama":
            raise ValueError(f"{key!r} is a {s.runtime} model, not an Ollama model")
        out = []
        for i in range(0, len(inputs), _BATCH):
            batch = list(inputs[i:i + _BATCH])
            body = {
                "model": s.name,
                "input": batch,
                "options": {"num_ctx": s.num_ctx},
                "keep_alive": s.keep_alive,
            }
            t0 = time.perf_counter()
            try:
                r = self._http.post("/api/embed", json=body, timeout=120.0)
                if r.status_code >= 400:
                    raise OllamaError(f"HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
            except OllamaError as e:
                _rec(tab, s.name, "ollama", t0, False, error=e)
                raise
            except Exception as e:  # noqa: BLE001
                _rec(tab, s.name, "ollama", t0, False, error=e)
                raise OllamaError(str(e)) from e
            _rec(tab, s.name, "ollama", t0, True, load_ms=data.get("load_duration", 0) / 1e6,
                 prompt_tokens=data.get("prompt_eval_count", 0) or 0)
            out.extend(data.get("embeddings", []))
        if not out:
            return np.zeros((0, 0), dtype=np.float32)
        return np.asarray(out, dtype=np.float32)

    # ---- housekeeping -----------------------------------------------------
    def warm(self, key) -> None:
        s = spec(key)
        if s.runtime != "ollama":
            raise ValueError(f"{key!r} is a {s.runtime} model, not an Ollama model")
        body = {"model": s.name, "keep_alive": s.keep_alive, "options": {"num_ctx": s.num_ctx}}
        t0 = time.perf_counter()
        try:
            r = self._http.post("/api/generate", json=body)
            if r.status_code >= 400:
                raise OllamaError(f"HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
        except Exception as e:  # noqa: BLE001
            _rec("warm", s.name, "ollama", t0, False, error=e)
            raise OllamaError(str(e)) from e
        _rec("warm", s.name, "ollama", t0, True, load_ms=data.get("load_duration", 0) / 1e6)

    def stop(self, name: str) -> None:
        t0 = time.perf_counter()
        try:
            r = self._http.post("/api/generate", json={"model": name, "keep_alive": 0})
            if r.status_code >= 400:
                raise OllamaError(f"HTTP {r.status_code}: {r.text[:500]}")
        except Exception as e:  # noqa: BLE001
            _rec("stop", name, "ollama", t0, False, error=e)
            raise OllamaError(str(e)) from e
        _rec("stop", name, "ollama", t0, True)

    def ps(self) -> list[dict]:
        r = self._http.get("/api/ps")
        r.raise_for_status()
        return r.json().get("models", []) or []

    def tags(self) -> list[dict]:
        r = self._http.get("/api/tags")
        r.raise_for_status()
        return r.json().get("models", []) or []

    def show(self, name) -> dict:
        r = self._http.post("/api/show", json={"model": name})
        r.raise_for_status()
        return r.json()

    def alive(self) -> bool:
        try:
            r = httpx.get(self.base_url + "/", timeout=2.0)
            return r.status_code < 500
        except Exception:  # noqa: BLE001
            return False


class LMSClient:
    def __init__(self, base_url: str = LMS_URL, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url + "/v1", api_key="lm-studio", timeout=self.timeout)
        return self._client

    def _is_loaded(self, name: str) -> bool:
        """True when GET /api/v0/models reports `name` as loaded. LM Studio's /v1 responses carry no load
        time, so the client asks the (read-only) state endpoint before a call; any failure counts as loaded so
        a wall time is never attributed to a load by mistake."""
        try:
            r = httpx.get(self.base_url + "/api/v0/models", timeout=2.0)
            if r.status_code != 200:
                return True
            for m in r.json().get("data", []) or []:
                if isinstance(m, dict) and m.get("id") == name:
                    return m.get("state") == "loaded"
            return True
        except Exception:  # noqa: BLE001
            return True

    def chat(self, key, messages, *, temperature=None, max_tokens=300, stream=False, extra=None, tab=""):
        s = spec(key)
        if s.runtime != "lms":
            raise ValueError(f"{key!r} is a {s.runtime} model, not an LM Studio model")
        extra_body = {k: v for k, v in s.samplers.items() if k in ("min_p", "top_k", "repeat_penalty")}
        extra_body.update(extra or {})
        if temperature is None:
            temperature = s.samplers.get("temperature", 1.0)
        was_loaded = self._is_loaded(s.name)
        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(
                model=s.name, messages=messages, temperature=temperature, max_tokens=max_tokens,
                stream=stream, extra_body=extra_body,
            )
        except Exception as e:  # noqa: BLE001
            _rec(tab, s.name, "lms", t0, False, error=e)
            raise
        # LM Studio reports no load_duration: when the model was not loaded before this call, the call's wall
        # time (for a stream: the time until the stream opened) is the JIT load and is recorded as load_ms.
        load_ms = 0.0 if was_loaded else (time.perf_counter() - t0) * 1000.0
        if stream:
            _rec(tab, s.name, "lms", t0, True, load_ms=load_ms)
            return resp
        u = getattr(resp, "usage", None)
        pt = getattr(u, "prompt_tokens", 0) or 0
        ct = getattr(u, "completion_tokens", 0) or 0
        wall = time.perf_counter() - t0
        _rec(tab, s.name, "lms", t0, True, load_ms=load_ms, prompt_tokens=pt, eval_tokens=ct,
             tok_s=(ct / wall) if wall else 0.0)
        return resp

    def embed(self, key, inputs: list[str], tab="") -> np.ndarray:
        s = spec(key)
        if s.runtime != "lms":
            raise ValueError(f"{key!r} is a {s.runtime} model, not an LM Studio model")
        out = []
        was_loaded = self._is_loaded(s.name) if inputs else True
        for i in range(0, len(inputs), _BATCH):
            batch = list(inputs[i:i + _BATCH])
            t0 = time.perf_counter()
            try:
                resp = self.client.embeddings.create(model=s.name, input=batch)
            except Exception as e:  # noqa: BLE001
                _rec(tab, s.name, "lms", t0, False, error=e)
                raise
            load_ms = 0.0 if was_loaded else (time.perf_counter() - t0) * 1000.0
            was_loaded = True  # only the first batch can carry the load
            _rec(tab, s.name, "lms", t0, True, load_ms=load_ms,
                 prompt_tokens=getattr(getattr(resp, "usage", None), "prompt_tokens", 0) or 0)
            out.extend(d.embedding for d in resp.data)
        if not out:
            return np.zeros((0, 0), dtype=np.float32)
        return np.asarray(out, dtype=np.float32)

    def models_v0(self) -> list[dict]:
        r = httpx.get(self.base_url + "/api/v0/models", timeout=10.0)
        r.raise_for_status()
        return r.json().get("data", []) or []

    def models_v1(self) -> list[str]:
        """Model ids from the OpenAI-compatible GET /v1/models (what a /v1 chat request may name)."""
        r = httpx.get(self.base_url + "/v1/models", timeout=10.0)
        r.raise_for_status()
        return [str(m.get("id", "")) for m in (r.json().get("data", []) or []) if isinstance(m, dict)]

    def loaded(self) -> list[str]:
        return [m.get("id", "") for m in self.models_v0() if m.get("state") == "loaded"]

    def unload_all(self) -> str:
        p = subprocess.run([str(LMS_CLI), "unload", "--all"], input="y\n", text=True,
                           capture_output=True, timeout=60)
        return (p.stdout or "") + (p.stderr or "")

    def alive(self) -> bool:
        try:
            r = httpx.get(self.base_url + "/api/v0/models", timeout=2.0)
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False


class AnthropicClient:
    def available(self) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def chat(self, system, messages, *, max_tokens=600, temperature=0.0, tab="") -> str:
        import anthropic
        t0 = time.perf_counter()
        try:
            # Key is read implicitly from ANTHROPIC_API_KEY; never pass or log it.
            client = anthropic.Anthropic(timeout=120.0, max_retries=2)
            resp = client.messages.create(
                model=ANTHROPIC_MODEL, system=system, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
        except Exception as e:  # noqa: BLE001
            _rec(tab, ANTHROPIC_MODEL, "anthropic", t0, False, error=type(e).__name__)
            raise
        text = "".join(getattr(b, "text", "") for b in resp.content)
        u = getattr(resp, "usage", None)
        _rec(tab, ANTHROPIC_MODEL, "anthropic", t0, True,
             prompt_tokens=getattr(u, "input_tokens", 0) or 0, eval_tokens=getattr(u, "output_tokens", 0) or 0)
        return text


ollama = OllamaClient()
lms = LMSClient()
anthropic_client = AnthropicClient()
