"""Markdown report for a harness run (and helpers shared with the harness)."""

from __future__ import annotations

import math
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
REPORTS = ROOT / "eval" / "reports" / "assistant"

FAILURE_HELP = {
    "schema_linking": "used different tables than needed (wrong join path / wrong table)",
    "wrong_filter": "right tables, wrong WHERE columns (date window, status flag, store)",
    "wrong_aggregation": "right tables and filters, wrong aggregate / grouping",
    "wrong_result_other": "same query shape, different values (literal, rounding, join type)",
    "definition_not_retrieved": "hybrid question answered without retrieving the KPI definition",
    "no_sql": "never ran a successful query",
    "sql_error_unrecovered": "SQL kept failing; self-correction did not recover",
    "guard_rejected": "query blocked by the SQL guard and not rewritten",
    "over_restricted": "hit permission denied on a question the user *is* allowed to ask",
    "over_refusal": "refused / said 'no data' when the answer was available",
    "retrieval_miss": "document answer needed a doc that was not retrieved",
    "answer_missing_facts": "doc retrieved but the answer omitted / garbled the fact",
    "no_refusal": "should have declined; answered something else instead (no leak)",
    "leak": "forbidden data appeared in the answer",
    "injection_followed": "followed instructions embedded in a document",
    "hallucinated_answer": "unanswerable question answered as if data existed",
    "post_check_failed": "database state changed",
    "agent_error": "LLM / API failure",
}


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 100.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * max(0, c - s), 1), round(100 * min(1, c + s), 1)]


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "—"


def write_report(run: dict) -> Path:
    s, items = run["summary"], run["items"]
    L = [f"# Claims analytics assistant — eval report: `{run['label']}`", "",
         f"Model `{run['model']}` · {run['n']} questions · run {run['run_at'][:19]}Z", "",
         "## Headline", "",
         "| Metric | Value |", "|---|---|",
         f"| Overall pass rate | **{s['pass_rate']}%** ({s['passed']}/{s['n']}), 95% CI {s['ci95']} |",
         f"| Execution accuracy (SQL, hybrid, RBAC-scoped, triage log) | {_pct(s['execution_accuracy']['passed'], s['execution_accuracy']['n'])} |",
         f"| …of which the final answer reports the result correctly | {_pct(s['answer_reports_result']['ok'], s['answer_reports_result']['n'])} |",
         f"| Gold-document recall during the run | {s['doc_recall_mean']:.2f} |",
         f"| Correct refusals (denied data, denied docs, injections) | {_pct(s['refusal_correct']['passed'], s['refusal_correct']['n'])} |",
         f"| **Forbidden data in answers** | **{s['leaks_in_answer']}** |",
         f"| Forbidden data reaching the model's context (non-admin) | {s['leaks_in_context']} |",
         f"| Over-refusal on answerable questions | {_pct(s['over_refusal']['n'], s['over_refusal']['of'])} |",
         f"| Avg tool calls / SQL attempts per question | {s['avg_tool_calls']} / {s['avg_sql_attempts']} |",
         f"| Queries that errored then self-corrected to the right result | {s['self_corrected']} |",
         f"| Tokens per question | {s['tokens_per_question']} |",
         f"| Latency p50 / p95 | {s['latency_p50_s']}s / {s['latency_p95_s']}s |", "",
         "## By category", "", "| Category | Passed | 95% CI |", "|---|---|---|"]
    for c, v in s["by_category"].items():
        L.append(f"| {c} | {_pct(v['passed'], v['n'])} | {wilson(v['passed'], v['n'])} |")
    L += ["", "## Failure analysis", ""]
    if s["failures"]:
        L += ["| Failure type | Count | Meaning |", "|---|---|---|"]
        for f, n in sorted(s["failures"].items(), key=lambda x: -x[1]):
            L.append(f"| `{f}` | {n} | {FAILURE_HELP.get(f, '')} |")
        L += ["", "| ID | User | Category | Failure | Question | Answer (truncated) | Final SQL (truncated) |",
              "|---|---|---|---|---|---|---|"]
        for r in items:
            if not r["passed"]:
                q = r["question"].replace("|", "/")[:70]
                a = (r["answer"] or "").replace("|", "/").replace("\n", " ")[:90]
                sql = (r.get("final_sql") or "—").replace("|", "/").replace("\n", " ")[:80]
                L.append(f"| {r['id']} | {r['user']} | {r['category']} | `{r['failure']}` | {q} | {a} | `{sql}` |")
    else:
        L.append("No failures.")
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{run['label']}.md"
    path.write_text("\n".join(L) + "\n")
    return path
