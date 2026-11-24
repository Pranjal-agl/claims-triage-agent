"""
The three tools the claims analytics assistant can call. Each is bound to the caller's DB role and
the run's tracer, so every call is permission-scoped and traced.

  get_schema(tables?)     tables/columns THIS ROLE can read (+ join hints)
  search_docs(query, k?)  hybrid retrieval over business documents (ACL'd by RLS)
  run_sql(sql)            guard → execute read-only as the role → rows / error
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from . import config, db, retrieval, sql_guard
from .tracing import Tracer

TABLE_NOTES = {
    "ins.policies": "US auto book: one row per policy; state (OH/IL/IN), csl limits, deductible, annual_premium, umbrella_limit",
    "ins.policyholders": "insured persons (personal data columns may be hidden for your role)",
    "ins.insured_vehicles": "the insured vehicle per policy: make, model, year",
    "ins.claims": "one claim per policy (incidents 2015-01-01..2015-03-01); amounts in USD; "
                  "NULL in collision_type / property_damage / police_report_available = unknown; "
                  "fraud_reported = SIU determination (may be hidden for your role)",
    "triage.policies": "the triage agent's retail book (INR): coverage_limit, deductible, dates, status",
    "triage.decisions": "log of decisions made by the claims triage agent (and baselines): "
                        "decision, reason, fraud_score, payout (INR), system, decided_at",
}
JOIN_HINTS = [
    "ins.claims.policy_number → ins.policies.policy_number",
    "ins.policies.policyholder_id → ins.policyholders.policyholder_id",
    "ins.insured_vehicles.policy_number → ins.policies.policy_number",
    "triage.decisions.policy_id → triage.policies.policy_id (may be NULL / unknown IDs)",
    "Always schema-qualify tables (ins.claims, triage.decisions).",
]

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_schema",
        "description": "List the database tables and columns you are allowed to query, with join hints. "
                       "Call this before writing SQL if you are unsure of table or column names.",
        "parameters": {"type": "object", "properties": {
            "tables": {"type": "array", "items": {"type": "string"},
                       "description": "Optional subset of table names. Omit to list all."}}}}},
    {"type": "function", "function": {
        "name": "search_docs",
        "description": "Search company documents (KPI definitions, data dictionary, claims handling manual, "
                       "privacy policy, SIU guides, triage runbook). "
                       "Use it whenever a question depends on a business definition or policy.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "k": {"type": "integer", "default": 4}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Run ONE read-only PostgreSQL SELECT against the claims warehouse (schemas ins, triage). "
                       "Results are limited to what your role may see.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
]


@dataclass
class ToolContext:
    role: str
    tracer: Tracer
    retrieval_mode: str = "hybrid"
    queries: list[dict] = field(default_factory=list)       # every run_sql attempt
    retrieved: list[dict] = field(default_factory=list)     # every chunk returned
    _schema: dict | None = None

    def schema(self) -> dict:
        if self._schema is None:
            self._schema = db.visible_schema(self.role)
        return self._schema


def _resolve(sch: dict, name: str) -> str | None:
    name = (name or "").strip().lower()
    if name in sch:
        return name
    for schema in config.QUERY_SCHEMAS:
        if f"{schema}.{name}" in sch:
            return f"{schema}.{name}"
    return None


def get_schema(ctx: ToolContext, tables: list[str] | None = None) -> dict:
    sch = ctx.schema()
    wanted = tables or sorted(sch)
    names = [r for r in (_resolve(sch, t) for t in wanted) if r]
    return {
        "tables": {t: {"note": TABLE_NOTES.get(t, ""), "columns": [f"{c['column']} {c['type']}" for c in sch[t]]}
                   for t in names},
        "join_hints": JOIN_HINTS,
        "unknown_or_not_permitted": [t for t in (tables or []) if not _resolve(sch, t)],
    }


def search_docs(ctx: ToolContext, query: str, k: int = 4) -> dict:
    k = max(1, min(int(k or 4), 8))
    with ctx.tracer.span("retrieval", mode=ctx.retrieval_mode, query=query, k=k) as sp:
        hits = retrieval.search(ctx.role, query, k=k, mode=ctx.retrieval_mode)
        sp.set(chunks=[h["chunk_id"] for h in hits])
    ctx.retrieved.extend(hits)
    return {"results": [{"doc_id": h["doc_id"], "chunk_id": h["chunk_id"], "title": h["title"],
                         "section": h["section"], "text": h["content"]} for h in hits]}


def run_sql(ctx: ToolContext, sql: str) -> dict:
    record: dict[str, Any] = {"sql": sql, "ok": False}
    ctx.queries.append(record)
    with ctx.tracer.span("sql.guard") as sp:
        try:
            g = sql_guard.check(sql, set(ctx.schema()), default_limit=config.DEFAULT_LIMIT)
            sp.set(verdict="allowed", tables=sorted(g.tables), limit_added=g.limit_added)
        except sql_guard.GuardError as e:
            sp.set(verdict="rejected", reason=str(e))
            record.update(error=str(e), error_kind="guard")
            return {"error": f"Query rejected by SQL guard: {e}"}
    record["executed_sql"] = g.sql
    with ctx.tracer.span("db.query", role=ctx.role) as sp:
        try:
            res = db.run_query(ctx.role, g.sql)
        except db.QueryError as e:
            sp.error(str(e))
            sp.set(sqlstate=e.sqlstate)
            kind = "permission_denied" if e.permission_denied else "db_error"
            record.update(error=str(e), error_kind=kind, sqlstate=e.sqlstate)
            if e.permission_denied:
                return {"error": f"PERMISSION DENIED for your role: {e}. This data is not available to the "
                                 f"current user. Do not try to work around it; tell the user."}
            return {"error": f"Database error: {e}. Fix the query and try again."}
        sp.set(rows=res["row_count"], ms=res["ms"], truncated=res["truncated"])
    record.update(ok=True, columns=res["columns"], rows=res["rows"], row_count=res["row_count"])
    shown = res["rows"][: config.MAX_ROWS_TO_LLM]
    return {"columns": res["columns"], "rows": shown, "row_count": res["row_count"],
            "note": f"showing first {len(shown)} rows" if res["row_count"] > len(shown) else None}


def dispatch(ctx: ToolContext, name: str, raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}") or {}
    except json.JSONDecodeError:
        return json.dumps({"error": "Arguments were not valid JSON."})
    with ctx.tracer.span(f"tool.{name}", args=args) as sp:
        try:
            if name == "get_schema":
                out = get_schema(ctx, args.get("tables"))
            elif name == "search_docs":
                out = search_docs(ctx, args.get("query", ""), args.get("k", 4))
            elif name == "run_sql":
                out = run_sql(ctx, args.get("sql", ""))
            else:
                out = {"error": f"Unknown tool {name}"}
        except Exception as e:  # never let a tool crash the loop
            sp.error(str(e))
            out = {"error": f"{type(e).__name__}: {e}"}
        if "error" in out:
            sp.set(error=str(out["error"])[:200])
    return json.dumps(out, default=str)[:12000]
