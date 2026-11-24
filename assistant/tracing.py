"""
Lightweight tracing: nested spans with timings and attributes, persisted to
Postgres (obs.traces / obs.spans, written by the cx_obs role) with a JSONL
fallback. Every agent run produces one trace:

    agent.run
    ├── llm.chat               model, tokens in/out, cached?, tool calls requested
    ├── tool.search_docs       query, retrieved chunk ids + scores, mode
    ├── tool.run_sql
    │   ├── sql.guard          verdict, tables, LIMIT added, rejection reason
    │   └── db.query           role, rows, ms, SQLSTATE on error
    └── llm.chat               final answer

The schema mirrors OpenTelemetry's span model (trace_id / span_id / parent_id /
attributes), so exporting to Langfuse, Jaeger or Honeycomb is a mapping, not a
redesign.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import config

FALLBACK = config.ROOT / ".traces" / "traces.jsonl"


class Span:
    def __init__(self, tracer: "Tracer", name: str, parent: "Span | None", attrs: dict):
        self.tracer, self.name, self.parent = tracer, name, parent
        self.span_id = uuid.uuid4()
        self.attrs = dict(attrs)
        self.status = "ok"
        self.started_at = datetime.now(timezone.utc)
        self._t0 = time.perf_counter()
        self.duration_ms = 0.0

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)

    def error(self, msg: str) -> None:
        self.status = "error"
        self.attrs["error"] = msg[:500]


class Tracer:
    def __init__(self, app_user: str, db_role: str, question: str, model: str | None = None):
        self.trace_id = uuid.uuid4()
        self.app_user, self.db_role, self.question, self.model = app_user, db_role, question, model
        self.spans: list[Span] = []
        self._stack: list[Span] = []
        self.started_at = datetime.now(timezone.utc)
        self._t0 = time.perf_counter()

    @contextlib.contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Span]:
        s = Span(self, name, self._stack[-1] if self._stack else None, attrs)
        self._stack.append(s)
        try:
            yield s
        except Exception as e:
            s.error(f"{type(e).__name__}: {e}")
            raise
        finally:
            s.duration_ms = round((time.perf_counter() - s._t0) * 1000, 2)
            self._stack.pop()
            self.spans.append(s)

    # ── aggregates ──
    def totals(self) -> dict:
        llm = [s for s in self.spans if s.name == "llm.chat"]
        return {
            "llm_calls": len(llm),
            "tool_calls": sum(1 for s in self.spans if s.name.startswith("tool.")),
            "tokens_in": sum(int(s.attrs.get("prompt_tokens", 0)) for s in llm),
            "tokens_out": sum(int(s.attrs.get("completion_tokens", 0)) for s in llm),
            "duration_ms": round((time.perf_counter() - self._t0) * 1000),
        }

    def to_dict(self, answer: str = "", status: str = "ok") -> dict:
        return {
            "trace_id": str(self.trace_id), "started_at": self.started_at.isoformat(),
            "app_user": self.app_user, "db_role": self.db_role, "question": self.question,
            "answer": answer, "status": status, "model": self.model, **self.totals(),
            "spans": [{"span_id": str(s.span_id), "parent_id": str(s.parent.span_id) if s.parent else None,
                       "name": s.name, "started_at": s.started_at.isoformat(), "duration_ms": s.duration_ms,
                       "status": s.status, "attrs": s.attrs} for s in sorted(self.spans, key=lambda x: x.started_at)],
        }

    def persist(self, answer: str, status: str, tags: dict | None = None) -> None:
        d = self.to_dict(answer, status)
        try:
            import psycopg
            with psycopg.connect(config.dsn("cx_obs"), autocommit=True, connect_timeout=3) as c:
                c.execute(
                    "INSERT INTO obs.traces (trace_id, started_at, app_user, db_role, question, answer, status, "
                    "duration_ms, llm_calls, tool_calls, tokens_in, tokens_out, model, tags) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self.trace_id, self.started_at, self.app_user, self.db_role, self.question, answer, status,
                     d["duration_ms"], d["llm_calls"], d["tool_calls"], d["tokens_in"], d["tokens_out"],
                     self.model, json.dumps(tags or {})))
                with c.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO obs.spans VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(s.span_id, self.trace_id, s.parent.span_id if s.parent else None, s.name,
                          s.started_at, s.duration_ms, s.status, json.dumps(s.attrs, default=str))
                         for s in self.spans])
        except Exception:
            FALLBACK.parent.mkdir(parents=True, exist_ok=True)
            with FALLBACK.open("a") as f:
                f.write(json.dumps({**d, "tags": tags or {}}, default=str) + "\n")


def render_tree(trace: dict) -> str:
    """Plain-text tree of a trace dict, for the CLI and logs."""
    kids: dict = {}
    for s in trace["spans"]:
        kids.setdefault(s["parent_id"], []).append(s)
    lines: list[str] = []

    def walk(pid, depth):
        for s in kids.get(pid, []):
            a = s["attrs"]
            info = ", ".join(f"{k}={str(v)[:60]}" for k, v in a.items()
                             if k in ("prompt_tokens", "completion_tokens", "rows", "verdict", "query",
                                      "chunks", "sqlstate", "error", "tool_calls", "cached", "tables"))
            mark = "✗" if s["status"] == "error" else "·"
            lines.append(f"{'  ' * depth}{mark} {s['name']:<18} {s['duration_ms']:>8.1f} ms  {info}")
            walk(s["span_id"], depth + 1)

    walk(None, 0)
    return "\n".join(lines)
