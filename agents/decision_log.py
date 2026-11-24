"""
agents/decision_log.py

Writes every triage decision to the claims warehouse (triage.decisions) as the
least-privilege `cx_triage` role (INSERT on that one table, nothing else).
This is the bridge between stage 1 (the triage agent) and stage 2 (the claims
analytics assistant, which can then answer "how many claims did we escalate
yesterday, and why?").

Logging is best-effort and never blocks a decision: if the warehouse isn't
configured or reachable, the decision is returned anyway and a single warning
is printed. Set TRIAGE_LOG=off to disable.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, datetime
from typing import Any

from .tools import lookup_policy, normalize_policy_id

_warned = False


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def reason_code(state: dict[str, Any]) -> str:
    """Short machine reason for a decision (codes documented in warehouse/docs/triage_runbook.md)."""
    if state.get("error"):
        return "degraded"
    dec = (state.get("decision") or {}).get("decision")
    score = (state.get("fraud") or {}).get("fraud_score")
    ext = state.get("extracted") or {}
    pol = state.get("policy") or {}
    if not pol and ext.get("policy_id"):
        pol = lookup_policy(ext["policy_id"])
    if dec == "REJECTED" and isinstance(score, (int, float)) and score > 0.75:
        return "fraud_high"
    if dec == "REJECTED":
        if not pol.get("found"):
            return "policy_not_found"
        if str(pol.get("status", "active")).lower() != "active":
            return "policy_not_active"
        inc, start, end = _d(ext.get("incident_date")), _d(pol.get("start_date")), _d(pol.get("end_date"))
        if inc and start and inc < start:
            return "before_policy_start"
        if inc and end and inc > end:
            return "policy_expired"
        if float(ext.get("claimed_amount") or 0) > float(pol.get("coverage_limit") or 0) > 0:
            return "exceeds_coverage"
        return "fraud_high"
    if dec == "ESCALATED":
        return "fraud_medium" if isinstance(score, (int, float)) and score >= 0.4 else "high_ratio"
    return "approved" if dec == "APPROVED" else "unknown"


def log_decision(state: dict[str, Any], claim_text: str, *, source: str, system: str = "agent",
                 model: str | None = None, latency_ms: int | None = None, tokens: int | None = None,
                 decided_at: datetime | None = None) -> bool:
    global _warned
    if os.getenv("TRIAGE_LOG", "auto").lower() == "off":
        return False
    try:
        import psycopg

        from assistant import config
        ext = state.get("extracted") or {}
        pid = normalize_policy_id(ext.get("policy_id") or "") or None
        pol = state.get("policy") or (lookup_policy(pid) if pid else {})
        dec = state.get("decision") or {}
        row = (decided_at or datetime.now().astimezone(), source, system, model,
               hashlib.sha256(claim_text.encode()).hexdigest(), pid, bool(pol.get("found")),
               ext.get("claimed_amount"), ext.get("incident_type"),
               (state.get("fraud") or {}).get("fraud_score"), dec.get("decision", "ESCALATED"),
               reason_code(state), dec.get("recommended_payout"), latency_ms, tokens, bool(state.get("error")))
        with psycopg.connect(config.dsn("cx_triage"), connect_timeout=2, autocommit=True) as c:
            c.execute(
                "INSERT INTO triage.decisions (decided_at, source, system, model, claim_text_sha, policy_id, "
                "policy_found, claimed_amount, incident_type, fraud_score, decision, reason, payout, latency_ms, "
                "tokens, degraded) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
        return True
    except Exception as exc:  # never block triage on logging
        if not _warned:
            print(f"[decision_log] not logging to warehouse ({type(exc).__name__}: {str(exc)[:80]})")
            _warned = True
        return False
