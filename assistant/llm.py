"""
Chat client for any OpenAI-compatible endpoint with tool calling (default: Groq,
llama-3.3-70b-versatile), with a SQLite response cache so eval runs are
reproducible and resumable under free-tier rate limits.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from . import config


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[dict], tools: list[dict]) -> dict: ...


class _Cache:
    def __init__(self, path: str):
        self.enabled = bool(path) and path != "0"
        self._lock = threading.Lock()
        if self.enabled:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.path = path
            with sqlite3.connect(path) as c:
                c.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT)")

    def get(self, key: str):
        if not self.enabled:
            return None
        with self._lock, sqlite3.connect(self.path) as c:
            row = c.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        if self.enabled:
            with self._lock, sqlite3.connect(self.path) as c:
                c.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(value)))


class OpenAICompatClient:
    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None,
                 cache_path: str | None = None, temperature: float = 0.0, http_client=None):
        from openai import OpenAI
        self.model = model or config.LLM_MODEL
        self.temperature = temperature
        self._client = OpenAI(base_url=base_url or config.LLM_BASE_URL,
                              api_key=api_key or config.LLM_API_KEY or "missing-key", max_retries=0,
                              http_client=http_client)
        self._cache = _Cache(config.LLM_CACHE if cache_path is None else cache_path)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Returns {"content", "tool_calls": [{"id","name","arguments"}], "usage": {...}, "cached"}."""
        req = {"model": self.model, "messages": messages, "tools": tools, "temperature": self.temperature}
        key = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
        hit = self._cache.get(key)
        if hit:
            return {**hit, "cached": True}
        resp = self._call_with_backoff(req)
        msg = resp.choices[0].message
        out = {
            "content": msg.content or "",
            "tool_calls": [{"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments or "{}"}
                           for tc in (msg.tool_calls or [])],
            "usage": {"prompt_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
                      "completion_tokens": getattr(resp.usage, "completion_tokens", 0) or 0},
        }
        self._cache.put(key, out)
        return {**out, "cached": False}

    def _call_with_backoff(self, req: dict, attempts: int = 7) -> Any:
        """Rate limits: back off (honouring Retry-After) up to `attempts` times.
        Connection errors: 2 quick retries. Auth / bad-request errors: raise immediately."""
        import openai
        conn_failures = 0
        for i in range(attempts):
            try:
                return self._client.chat.completions.create(**req, tool_choice="auto")
            except openai.RateLimitError as e:
                time.sleep(_retry_after(e) or min(120, 5 * 2**i))
            except openai.APIConnectionError:
                conn_failures += 1
                if conn_failures > 2:
                    raise
                time.sleep(2 * conn_failures)
        return self._client.chat.completions.create(**req, tool_choice="auto")


def _retry_after(e) -> float | None:
    try:
        v = e.response.headers.get("retry-after")
        return float(v) + 1 if v else None
    except Exception:
        return None
