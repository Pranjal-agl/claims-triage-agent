"""
RBAC attack suite for the claims warehouse (no LLM). Adversarial SQL is run as
each restricted role twice:
  1. through the application path (SQL guard → database)
  2. straight to Postgres, BYPASSING the guard
An attack is contained if no protected data comes back on either path. Column
(2) is the point: Postgres alone holds the line, so a guard parsing gap would
not become a data leak.

    python -m eval.assistant.rbac_suite     → eval/reports/assistant/rbac_suite.md (exit 1 on any leak)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from assistant import db, sql_guard  # noqa: E402
from eval.assistant.report import REPORTS  # noqa: E402

EMAIL = lambda rows: any("@" in str(v) for r in rows for v in r)          # noqa: E731
NONZERO = lambda rows: any(v not in (None, 0, False) for r in rows for v in r)  # noqa: E731
LAST_NONZERO = lambda rows: any(r[-1] not in (None, 0) for r in rows)       # noqa: E731
ANY = lambda rows: bool(rows)                                              # noqa: E731
ALWAYS = lambda rows: True                                                 # noqa: E731

ATTACKS = [
    # analyst: no personal data
    ("cx_analyst", "PII column directly", "SELECT email FROM ins.policyholders LIMIT 5", EMAIL),
    ("cx_analyst", "SELECT * on policyholders", "SELECT * FROM ins.policyholders LIMIT 5", EMAIL),
    ("cx_analyst", "PII via CTE", "WITH h AS (SELECT * FROM ins.policyholders) SELECT * FROM h LIMIT 5", EMAIL),
    ("cx_analyst", "PII via scalar subquery", "SELECT (SELECT full_name FROM ins.policyholders LIMIT 1)", ANY),
    ("cx_analyst", "PII via row_to_json", "SELECT row_to_json(h) FROM ins.policyholders h LIMIT 1", EMAIL),
    ("cx_analyst", "incident street address", "SELECT incident_location FROM ins.claims LIMIT 5", ANY),
    ("cx_analyst", "hobbies of fraud claims", "SELECT h.hobbies FROM ins.policyholders h LIMIT 5", ANY),
    # adjusters: own region only, no fraud labels, no triage log
    ("cx_adjuster_oh", "other region's claims", "SELECT count(*) FROM ins.claims c JOIN ins.policies p USING (policy_number) WHERE p.state = 'IL'", NONZERO),
    ("cx_adjuster_oh", "other region's emails", "SELECT h.email FROM ins.policyholders h WHERE h.policyholder_id NOT IN (SELECT policyholder_id FROM ins.policies WHERE state = 'OH')", EMAIL),
    ("cx_adjuster_oh", "SIU fraud labels", "SELECT count(*) FILTER (WHERE fraud_reported) FROM ins.claims", NONZERO),
    ("cx_adjuster_oh", "fraud label via row_to_json", "SELECT row_to_json(c)->>'fraud_reported' FROM ins.claims c LIMIT 5", ANY),
    ("cx_adjuster_oh", "triage decision log", "SELECT count(*) FROM triage.decisions", NONZERO),
    ("cx_adjuster_oh", "escalate via set_config('role')", "SELECT set_config('role', 'cx_admin', false)", ANY),
    ("cx_adjuster_oh", "forge a region variable, then read IL",
     "SELECT set_config('app.state', 'IL', true), (SELECT count(*) FROM ins.policies WHERE state = 'IL')", LAST_NONZERO),
    ("cx_adjuster_oh", "rewrite role→region mapping", "UPDATE app.role_scope SET state = 'IL'", ALWAYS),
    ("cx_adjuster_oh", "read role→region mapping of others", "SELECT * FROM app.role_scope WHERE role_name <> current_user", ANY),
    ("cx_adjuster_il", "restricted documents (SIU guide)", "SELECT content FROM app.doc_chunks WHERE doc_id = 'siu_fraud_guide'", ANY),
    ("cx_adjuster_il", "assistant traces", "SELECT * FROM obs.traces LIMIT 1", ANY),
    # everyone: no writes, no DoS, no catalogs, no files
    ("cx_adjuster_in", "write: delete", "DELETE FROM ins.claims WHERE claim_id = 1", ALWAYS),
    ("cx_adjuster_in", "write: stacked statement", "SELECT 1; UPDATE ins.claims SET total_claim_amount = 0", ALWAYS),
    ("cx_adjuster_in", "write: insert into triage log", "INSERT INTO triage.decisions (source, system, claim_text_sha, decision) VALUES ('x','x','x','APPROVED')", ALWAYS),
    ("cx_analyst", "DoS: pg_sleep", "SELECT pg_sleep(20)", ALWAYS),
    ("cx_analyst", "file read", "SELECT pg_read_file('/etc/passwd')", ANY),
    ("cx_analyst", "password hashes from pg_authid", "SELECT rolname, rolpassword FROM pg_authid", ANY),
    ("cx_siu", "SIU cannot write either", "DELETE FROM ins.claims WHERE claim_id = 1", ALWAYS),
    ("cx_siu", "Head-of-Claims-only document", "SELECT content FROM app.doc_chunks WHERE doc_id = 'underwriting_guidelines_2015'", ANY),
]


def attempt(role: str, sql: str, use_guard: bool):
    if use_guard:
        try:
            sql = sql_guard.check(sql, set(db.visible_schema(role))).sql
        except sql_guard.GuardError as e:
            return "blocked (guard)", None
    try:
        return "executed", db.run_query(role, sql)["rows"]
    except db.QueryError as e:
        return f"blocked (db {e.sqlstate})", None


def main() -> int:
    L = ["# RBAC attack suite — claims warehouse", "",
         "Adversarial SQL as restricted roles. **Guard path** = what the assistant's `run_sql` tool does. "
         "**DB only** = the same SQL sent straight to Postgres with the guard bypassed.", "",
         "| Role | Attack | Guard path | DB only (guard bypassed) | Contained |", "|---|---|---|---|---|"]
    leaks = 0
    for role, desc, sql, leak_test in ATTACKS:
        g_status, g_rows = attempt(role, sql, True)
        d_status, d_rows = attempt(role, sql, False)
        g_leak = g_rows is not None and leak_test(g_rows)
        d_leak = d_rows is not None and leak_test(d_rows)
        if d_status == "executed" and not d_leak:
            d_status = f"executed, nothing protected ({str(d_rows[:1])[:40]})"
        ok = not g_leak and not d_leak
        leaks += not ok
        L.append(f"| {role} | {desc} | {g_status} | {d_status} | {'✅' if ok else '❌ LEAK'} |")
    L += ["", f"**{len(ATTACKS) - leaks}/{len(ATTACKS)} attacks contained on both paths.**"]
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "rbac_suite.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
