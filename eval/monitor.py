"""
eval/monitor.py

Online drift monitoring for the claims triage agent.

Two parts:

1. ProductionLogger
   Call log_decision() after every live agent run. Appends a JSONL record
   to data/production_log.jsonl with the decision, fraud score, latency,
   and token count. No ground truth required at log time.

2. drift_report()
   When you have human-reviewed ground truth for a sample of production
   cases (add them to data/production_labels.jsonl), this compares online
   accuracy to the eval-harness offline accuracy and flags divergence.
   Also tracks rolling fraud score distribution to catch score drift even
   without labels (if the mean fraud score shifts significantly, something
   has changed in the model or input distribution).

Usage — log a decision:
    from eval.monitor import ProductionLogger
    logger = ProductionLogger()
    logger.log_decision(claim_text, state, node_latencies, token_usage)

Usage — check drift:
    python -m eval.monitor --baseline eval/runs/latest.json --window 50
"""

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_PATH = Path("data/production_log.jsonl")
LABELS_PATH = Path("data/production_labels.jsonl")


# ── production logger ─────────────────────────────────────────────────────────


class ProductionLogger:
    """
    Append-only JSONL logger for live production decisions.
    One record per claim processed through the agent in production.
    """

    def __init__(self, log_path: Path = LOG_PATH) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_decision(
        self,
        claim_text: str,
        state: dict[str, Any],
        node_latencies: dict[str, float],
        token_usage: dict[str, int] | None = None,
    ) -> None:
        decision_dict = state.get("decision") or {}
        fraud_dict = state.get("fraud") or {}

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "decision": decision_dict.get("decision", "UNKNOWN"),
            "fraud_score": fraud_dict.get("fraud_score", -1.0),
            "fraud_flags": fraud_dict.get("flags", []),
            "e2e_latency_s": round(sum(node_latencies.values()), 3),
            "node_latencies": node_latencies,
            "token_usage": token_usage or {},
            # Store a short fingerprint of the claim for audit, not the full text
            # (avoids logging PII in plaintext; use claim length + first 40 chars)
            "claim_len": len(claim_text),
            "claim_prefix": claim_text[:40],
        }

        with open(self.log_path, "a") as f:
            f.write(json.dumps(record) + "\n")


# ── drift report ──────────────────────────────────────────────────────────────


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))


def drift_report(baseline_path: Path, window: int = 50) -> None:
    """
    Compare the most recent `window` production decisions against the
    offline eval baseline, and flag statistical divergence.

    Checks:
      1. Decision distribution drift — if REJECTED% has shifted > 15pp
         vs the baseline, something changed (model, prompt, or input dist).
      2. Fraud score distribution drift — mean + stddev of fraud scores
         in the production window vs offline eval cases.
      3. Labeled accuracy (if production_labels.jsonl exists) — online
         accuracy vs offline accuracy, flagged if gap > 10pp.
    """
    # Load baseline
    if not baseline_path.exists():
        print(f"Baseline not found: {baseline_path}")
        sys.exit(1)
    with open(baseline_path) as f:
        baseline = json.load(f)

    baseline_acc = baseline.get("overall_accuracy_pct", None)
    baseline_cases = baseline.get("per_case_results", [])
    baseline_fraud_scores = [
        c["actual_fraud_score"]
        for c in baseline_cases
        if c.get("actual_fraud_score") is not None and c["actual_fraud_score"] >= 0
    ]
    baseline_decisions = [c["actual_decision"] for c in baseline_cases]

    # Load production log (last `window` records)
    prod_log = _load_jsonl(LOG_PATH)
    recent = prod_log[-window:] if len(prod_log) >= window else prod_log
    n_prod = len(recent)

    print(f"\n{'─'*60}")
    print(f"  Drift Report")
    print(f"  Baseline : {baseline_path.name}  (offline acc={baseline_acc}%)")
    print(f"  Window   : last {n_prod} production decisions")
    print(f"{'─'*60}\n")

    if n_prod == 0:
        print("  No production decisions logged yet.")
        print(f"  Log file: {LOG_PATH}\n")
        return

    # 1. Decision distribution
    prod_decisions = [r["decision"] for r in recent]
    for label in ["APPROVED", "REJECTED", "ESCALATED"]:
        base_pct = 100 * baseline_decisions.count(label) / len(baseline_decisions) if baseline_decisions else 0
        prod_pct = 100 * prod_decisions.count(label) / n_prod
        delta = prod_pct - base_pct
        flag = "  ⚠️  DRIFT" if abs(delta) > 15 else ""
        print(f"  {label:<10}  baseline={base_pct:.1f}%  production={prod_pct:.1f}%  Δ={delta:+.1f}pp{flag}")

    # 2. Fraud score distribution
    prod_scores = [r["fraud_score"] for r in recent if r.get("fraud_score", -1) >= 0]
    if prod_scores and baseline_fraud_scores:
        b_mean = _mean(baseline_fraud_scores)
        p_mean = _mean(prod_scores)
        b_std = _stddev(baseline_fraud_scores)
        p_std = _stddev(prod_scores)
        score_delta = p_mean - b_mean
        flag = "  ⚠️  DRIFT" if abs(score_delta) > 0.1 else ""
        print(f"\n  Fraud score distribution:")
        print(f"    baseline  mean={b_mean:.3f}  std={b_std:.3f}")
        print(f"    production mean={p_mean:.3f}  std={p_std:.3f}  Δ={score_delta:+.3f}{flag}")

    # 3. Labeled accuracy (optional)
    labels = _load_jsonl(LABELS_PATH)
    if labels:
        labeled_correct = sum(
            1 for l in labels
            if l.get("actual_decision") == l.get("expected_decision")
        )
        online_acc = round(100 * labeled_correct / len(labels), 1)
        gap = online_acc - (baseline_acc or 0)
        flag = "  ⚠️  GAP" if abs(gap) > 10 else ""
        print(f"\n  Labeled online accuracy : {labeled_correct}/{len(labels)}  ({online_acc}%)")
        print(f"  Offline/online gap      : {gap:+.1f}pp{flag}")
    else:
        print(f"\n  No labeled production data yet.")
        print(f"  Add records to {LABELS_PATH} to enable online accuracy tracking.")
        print(f"  Format: {{\"actual_decision\": \"APPROVED\", \"expected_decision\": \"APPROVED\"}}")

    # 4. Latency in production vs eval
    prod_latencies = [r["e2e_latency_s"] for r in recent if "e2e_latency_s" in r]
    if prod_latencies:
        sorted_lat = sorted(prod_latencies)
        p99_idx = min(int(len(sorted_lat) * 0.99), len(sorted_lat) - 1)
        p99 = sorted_lat[p99_idx]
        baseline_p99 = (
            baseline.get("latency_summary", {})
            .get("__end_to_end__", {})
            .get("p99_s", None)
        )
        flag = ""
        if baseline_p99 and p99 > baseline_p99 * 1.5:
            flag = "  ⚠️  LATENCY REGRESSION"
        print(f"\n  Production p99 latency  : {p99:.2f}s", end="")
        if baseline_p99:
            print(f"  (baseline p99={baseline_p99}s){flag}")
        else:
            print()

    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Claims agent drift monitor")
    parser.add_argument(
        "--baseline",
        default="eval/runs/latest.json",
        help="Path to baseline eval run manifest",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=50,
        help="Number of recent production decisions to compare against",
    )
    args = parser.parse_args()
    drift_report(Path(args.baseline), args.window)
