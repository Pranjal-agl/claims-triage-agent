# Claims analytics assistant — eval report: `oracle`

Model `llama-3.3-70b-versatile` · 76 questions · run 2026-11-24T08:51:56Z

## Headline

| Metric | Value |
|---|---|
| Overall pass rate | **100.0%** (76/76), 95% CI [95.2, 100.0] |
| Execution accuracy (SQL, hybrid, RBAC-scoped, triage log) | 44/44 (100%) |
| …of which the final answer reports the result correctly | 44/44 (100%) |
| Gold-document recall during the run | 1.00 |
| Correct refusals (denied data, denied docs, injections) | 18/18 (100%) |
| **Forbidden data in answers** | **0** |
| Forbidden data reaching the model's context (non-admin) | 0 |
| Over-refusal on answerable questions | 0/55 (0%) |
| Avg tool calls / SQL attempts per question | 0.0 / 0.58 |
| Queries that errored then self-corrected to the right result | 0 |
| Tokens per question | 0 |
| Latency p50 / p95 | 0.0s / 0.01s |

## By category

| Category | Passed | 95% CI |
|---|---|---|
| doc | 11/11 (100%) | [74.1, 100] |
| doc_acl | 4/4 (100%) | [51.0, 100] |
| hybrid | 12/12 (100%) | [75.7, 100] |
| rbac_denied | 7/7 (100%) | [64.6, 100] |
| rbac_scope | 8/8 (100%) | [67.6, 100] |
| safety | 7/7 (100%) | [64.6, 100] |
| sql_complex | 10/10 (100%) | [72.2, 100] |
| sql_simple | 10/10 (100%) | [72.2, 100] |
| triage_log | 4/4 (100%) | [51.0, 100] |
| unanswerable | 3/3 (100%) | [43.8, 100] |

## Failure analysis

No failures.
