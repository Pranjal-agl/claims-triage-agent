"""
Static checks on model-generated SQL before it reaches Postgres.

Defense in depth: the database role is the real boundary (warehouse/sql/10_roles.sql,
20_rls.sql). The guard exists to fail fast with a message the agent can act on,
to block things that are expensive or odd even when permitted (pg_sleep,
catalog scraping, unbounded results), and to leave an auditable reason in the trace.

Rules
  1. exactly one statement, and it must be a read (SELECT / WITH … SELECT / set ops)
  2. no DDL, DML, COPY, SET, CALL, DO, transaction control, locking, SELECT INTO
  3. no denylisted functions (sleep, file I/O, large objects, dblink, set_config,
     current_setting, backend control, advisory locks, xml dumps, …)
  4. only tables in schemas `ins` / `triage` that this role can read; unqualified
     names resolve via search_path (ins, triage); app.*, obs.*, catalogs refused
  5. a LIMIT is added to the outermost query if missing
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

DENY_FUNCTIONS = {
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "pg_read_file", "pg_read_binary_file", "pg_ls_dir",
    "pg_stat_file", "lo_import", "lo_export", "lo_get", "lo_open", "dblink", "dblink_exec",
    "dblink_connect", "set_config", "current_setting", "pg_terminate_backend", "pg_cancel_backend",
    "pg_reload_conf", "pg_advisory_lock", "pg_advisory_xact_lock", "pg_try_advisory_lock",
    "query_to_xml", "table_to_xml", "cursor_to_xml", "query_to_xml_and_xmlschema",
    "pg_logical_emit_message", "txid_current", "pg_current_xact_id",
}
SEARCH_PATH = ("ins", "triage")
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command,
    exp.Merge, exp.TruncateTable, exp.Set, exp.Transaction, exp.Commit, exp.Rollback,
    exp.Copy, exp.Lock, exp.Into,
)


class GuardError(Exception):
    pass


@dataclass
class GuardResult:
    sql: str
    tables: set[str] = field(default_factory=set)    # schema-qualified
    limit_added: bool = False


def _func_name(f: exp.Expression) -> str:
    if isinstance(f, exp.Anonymous):
        return str(f.this).lower()
    return str(f.sql_name() if hasattr(f, "sql_name") else f.key).lower()


def check(sql: str, allowed_tables: set[str], default_limit: int = 200) -> GuardResult:
    """allowed_tables: schema-qualified names this role can SELECT, e.g. {'ins.claims', …}."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise GuardError("Empty query.")
    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise GuardError(f"Could not parse SQL: {str(e).splitlines()[0]}") from None
    if len(statements) != 1:
        raise GuardError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
        raise GuardError(f"Only read-only SELECT queries are allowed (got {tree.key.upper()}).")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError(f"Statement type {node.key.upper()} is not allowed.")
        if isinstance(node, exp.Func):
            name = _func_name(node)
            if name in DENY_FUNCTIONS or name.startswith("pg_") or name.startswith("lo_"):
                raise GuardError(f"Function {name}() is not allowed.")

    by_name: dict[str, list[str]] = {}
    for q in allowed_tables:
        by_name.setdefault(q.split(".", 1)[1], []).append(q)
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables: set[str] = set()
    for t in tree.find_all(exp.Table):
        name, schema = (t.name or "").lower(), (t.db or "").lower()
        if not name:
            continue
        if not schema and name in cte_names:
            continue
        if schema:
            if schema not in SEARCH_PATH:
                raise GuardError(f"Schema '{schema}' is not accessible.")
            qualified = f"{schema}.{name}"
        else:
            cands = sorted(by_name.get(name, []), key=lambda q: SEARCH_PATH.index(q.split(".")[0]))
            if not cands:
                raise GuardError(f"Table '{name}' is not available to your role. Use get_schema to see tables.")
            qualified = cands[0]
        if qualified not in allowed_tables:
            raise GuardError(f"Table '{qualified}' is not available to your role.")
        tables.add(qualified)

    limit_added = False
    if isinstance(tree, exp.Select) and not tree.args.get("limit"):
        tree = tree.limit(default_limit)
        limit_added = True
    return GuardResult(sql=tree.sql(dialect="postgres"), tables=tables, limit_added=limit_added)
