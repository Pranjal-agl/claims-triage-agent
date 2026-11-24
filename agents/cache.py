"""
agents/cache.py

Minimal SQLite-backed LangChain LLM cache (no langchain-community dependency).
Keyed on (prompt, llm_string) — llm_string includes model, temperature and any
bound tools/structured-output schema, so changing a prompt or schema is a miss.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional, Sequence

from langchain_core.caches import BaseCache
from langchain_core.load import dumps, loads
from langchain_core.outputs import Generation

RETURN_VAL_TYPE = Sequence[Generation]


class SQLiteLLMCache(BaseCache):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS llm_cache (k TEXT PRIMARY KEY, v TEXT NOT NULL)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def _key(prompt: str, llm_string: str) -> str:
        return hashlib.sha256(f"{llm_string}\x00{prompt}".encode()).hexdigest()

    def lookup(self, prompt: str, llm_string: str) -> Optional[RETURN_VAL_TYPE]:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT v FROM llm_cache WHERE k=?", (self._key(prompt, llm_string),)).fetchone()
        if not row:
            return None
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return loads(row[0])
        except Exception:
            return None

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?)",
                      (self._key(prompt, llm_string), dumps(list(return_val))))

    def clear(self, **kwargs: Any) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM llm_cache")
