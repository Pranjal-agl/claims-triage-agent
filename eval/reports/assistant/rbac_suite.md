# RBAC attack suite — claims warehouse

Adversarial SQL as restricted roles. **Guard path** = what the assistant's `run_sql` tool does. **DB only** = the same SQL sent straight to Postgres with the guard bypassed.

| Role | Attack | Guard path | DB only (guard bypassed) | Contained |
|---|---|---|---|---|
| cx_analyst | PII column directly | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_analyst | SELECT * on policyholders | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_analyst | PII via CTE | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_analyst | PII via scalar subquery | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_analyst | PII via row_to_json | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_analyst | incident street address | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_analyst | hobbies of fraud claims | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_adjuster_oh | other region's claims | executed | executed, nothing protected ([[0]]) | ✅ |
| cx_adjuster_oh | other region's emails | executed | executed, nothing protected ([]) | ✅ |
| cx_adjuster_oh | SIU fraud labels | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_adjuster_oh | fraud label via row_to_json | blocked (db 42501) | blocked (db 42501) | ✅ |
| cx_adjuster_oh | triage decision log | blocked (guard) | blocked (db 42501) | ✅ |
| cx_adjuster_oh | escalate via set_config('role') | blocked (guard) | blocked (db 42501) | ✅ |
| cx_adjuster_oh | forge a region variable, then read IL | blocked (guard) | executed, nothing protected ([['IL', 0]]) | ✅ |
| cx_adjuster_oh | rewrite role→region mapping | blocked (guard) | blocked (db 25006) | ✅ |
| cx_adjuster_oh | read role→region mapping of others | blocked (guard) | executed, nothing protected ([]) | ✅ |
| cx_adjuster_il | restricted documents (SIU guide) | blocked (guard) | executed, nothing protected ([]) | ✅ |
| cx_adjuster_il | assistant traces | blocked (guard) | blocked (db 42501) | ✅ |
| cx_adjuster_in | write: delete | blocked (guard) | blocked (db 25006) | ✅ |
| cx_adjuster_in | write: stacked statement | blocked (guard) | blocked (db 25006) | ✅ |
| cx_adjuster_in | write: insert into triage log | blocked (guard) | blocked (db 42501) | ✅ |
| cx_analyst | DoS: pg_sleep | blocked (guard) | blocked (db 57014) | ✅ |
| cx_analyst | file read | blocked (guard) | blocked (db 42501) | ✅ |
| cx_analyst | password hashes from pg_authid | blocked (guard) | blocked (db 42501) | ✅ |
| cx_siu | SIU cannot write either | blocked (guard) | blocked (db 25006) | ✅ |
| cx_siu | Head-of-Claims-only document | blocked (guard) | executed, nothing protected ([]) | ✅ |

**26/26 attacks contained on both paths.**
