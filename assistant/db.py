"""
Database access for the claims analytics assistant. Every query runs on a connection that is LOGGED IN as the
user's database role. The role's grants, column privileges and row-level
security policies are what actually enforce access; the SQL guard in front of
this is defense in depth, not the boundary.
"""

from __future__ import annotations

import decimal
import threading
import time
from datetime import date, datetime
from typing import Any

import psycopg

from . import config

_local = threading.local()


def _conn(role: str) -> psycopg.Connection:
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    c = cache.get(role)
    if c is None or c.closed or c.broken:
        c = psycopg.connect(config.dsn(role), autocommit=False, connect_timeout=5)
        cache[role] = c
    return c


def _jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (bytes, memoryview)):
        return "<binary>"
    return v


class QueryError(Exception):
    def __init__(self, message: str, sqlstate: str | None = None):
        super().__init__(message)
        self.sqlstate = sqlstate

    @property
    def permission_denied(self) -> bool:
        return self.sqlstate == "42501"


def run_query(role: str, sql: str, params: tuple | dict | None = None, max_rows: int = 1000) -> dict:
    """
    Execute one statement in a READ ONLY transaction as `role`.
    Returns {"columns", "rows", "row_count", "truncated", "ms"}.
    Raises QueryError with the Postgres SQLSTATE (42501 = permission denied).
    """
    conn = _conn(role)
    t0 = time.perf_counter()
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql, params)
                cols = [d.name for d in cur.description] if cur.description else []
                rows = cur.fetchmany(max_rows + 1) if cur.description else []
    except psycopg.Error as e:
        raise QueryError(str(e).strip().split("\n")[0], getattr(e, "sqlstate", None)) from None
    truncated = len(rows) > max_rows
    rows = [[_jsonable(v) for v in r] for r in rows[:max_rows]]
    return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


def visible_schema(role: str) -> dict[str, list[dict]]:
    """Schema-qualified tables/columns this role can SELECT, read from the catalogue *as that role*."""
    sql = """
      SELECT c.table_schema || '.' || c.table_name, c.column_name, c.data_type
      FROM information_schema.columns c
      WHERE c.table_schema = ANY(%(schemas)s)
        AND has_column_privilege(current_user, format('%%I.%%I', c.table_schema, c.table_name),
                                 c.column_name, 'SELECT')
      ORDER BY 1, c.ordinal_position
    """
    out: dict[str, list[dict]] = {}
    for t, col, typ in run_query(role, sql, {"schemas": list(config.QUERY_SCHEMAS)}, max_rows=5000)["rows"]:
        out.setdefault(t, []).append({"column": col, "type": typ})
    return out


def superuser_conn() -> psycopg.Connection:
    return psycopg.connect(config.dsn("superuser"), autocommit=True)
