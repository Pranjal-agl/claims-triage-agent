"""
eval/runner.py

Eval harness for the claims triage agent.

What it measures (per the AI/ML must-have checklist):
  ✓ Real held-out eval set — 25 labeled cases never used in prompts
  ✓ Decision accuracy — overall + per-slice precision/recall/F1
  ✓ Fraud band accuracy — did the agent land in the right risk band?
  ✓ Extraction spot-check — did it pull the right policy_id from the text?
  ✓ Per-node latency — p50/p95/p99 per graph node across all runs
  ✓ Failure mode taxonomy — wrong_extraction / wrong_fraud_band /
      wrong_decision / correct
  ✓ Run manifest — model, timestamp, per-case results written to JSON
      so every run is reproducible and comparable over time

Usage:
    python -m eval.runner                    # run all 25 cases
    python -m eval.runner --slice fraud      # run one slice only
    python -m eval.runner --case edge_03     # run a single case
    python -m eval.runner --out runs/        # custom output directory

Requires GROQ_API_KEY in environment (or a .env file at project root).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as `python -m eval.runner` from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from eval.dataset import EVAL_DATASET, EvalCase

# ── constants ────────────────────────────────────────────────────────────────

MODEL = "llama-3.3-70b-versatile"
FRAUD_BANDS = {
    "low": (0.0, 0.4),
    "medium": (0.4, 0.75),
    "high": (0.75, 1.01),
}

# ── helpers ──────────────────────────────────────────────────────────────────


def fraud_band(score: float) -> str:
    for band, (lo, hi) in FRAUD_BANDS.items():
        if lo <= score < hi:
            return band
    return "high"


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * p / 100)
    idx = min(idx, len(sorted_v) - 1)
    return round(sorted_v[idx], 3)


def wilson_ci(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson score interval for a proportion — honest about uncertainty on small
    sample sizes (unlike a naive ±1/√n normal approximation which can exceed
    [0,1] and is unreliable below ~30 samples).

    z=1.96 → 95% confidence interval.
    Returns (lower_pct, upper_pct) as percentages rounded to 1 decimal.
    """
    if total == 0:
        return (0.0, 100.0)
    p = correct / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    spread = (z * (p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5) / denom
    lo = max(0.0, centre - spread)
    hi = min(1.0, centre + spread)
    return (round(lo * 100, 1), round(hi * 100, 1))


# ── timed graph runner ────────────────────────────────────────────────────────


def run_case_timed(claim_text: str) -> tuple[dict[str, Any], dict[str, float], dict[str, int]]:
    """
    Run the LangGraph pipeline and return:
      (final_state, node_latencies_seconds, token_usage)

    token_usage keys: tokens_in, tokens_out, tokens_total
    Uses LangChain's UsageMetadataCallbackHandler to capture token counts
    from all LLM calls within the graph, including .with_structured_output().
    Temperature=0 is already set in nodes.py for maximum determinism.
    """
    from agents.graph import claims_graph
    from langchain_core.callbacks import UsageMetadataCallbackHandler

    initial_state: dict[str, Any] = {
        "claim_text": claim_text,
        "extracted": None,
        "policy": None,
        "fraud": None,
        "decision": None,
        "final_report": None,
        "error": None,
    }

    node_latencies: dict[str, float] = {}
    accumulated: dict[str, Any] = {}
    usage_handler = UsageMetadataCallbackHandler()
    t_prev = time.perf_counter()

    for chunk in claims_graph.stream(
        initial_state,
        stream_mode="updates",
        config={"callbacks": [usage_handler]},
    ):
        t_now = time.perf_counter()
        node_name = list(chunk.keys())[0]
        node_latencies[node_name] = round(t_now - t_prev, 3)
        accumulated.update(chunk[node_name])
        t_prev = t_now

    # Aggregate token usage from callback
    tokens_in = getattr(usage_handler, "input_tokens", 0) or 0
    tokens_out = getattr(usage_handler, "output_tokens", 0) or 0

    # Fallback: try usage_metadata attribute if input_tokens not available
    if tokens_in == 0:
        try:
            meta = usage_handler.usage_metadata
            if isinstance(meta, dict):
                tokens_in = meta.get("input_tokens", 0) or 0
                tokens_out = meta.get("output_tokens", 0) or 0
            elif hasattr(meta, "input_tokens"):
                tokens_in = meta.input_tokens or 0
                tokens_out = meta.output_tokens or 0
        except Exception:
            pass

    token_usage = {
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "tokens_total": int(tokens_in + tokens_out),
    }
    return accumulated, node_latencies, token_usage


# ── failure taxonomy ──────────────────────────────────────────────────────────


def classify_failure(
    case: EvalCase,
    state: dict[str, Any],
    actual_decision: str,
    actual_band: str,
) -> str:
    """
    Returns one of:
      correct               — decision and fraud band both match
      wrong_extraction      — policy_id extracted incorrectly (likely cascades)
      wrong_fraud_band      — fraud score in wrong band (decision may follow)
      wrong_decision        — fraud band correct but decision label wrong
      wrong_decision_band   — both fraud band and decision wrong
    """
    extracted = state.get("extracted") or {}
    # Attempt to pull policy_id from claim text for extraction check
    expected_policy = None
    for word in case.claim_text.split():
        if word.upper().startswith("POL-"):
            expected_policy = word.strip(".,").upper()
            break

    extraction_ok = (
        expected_policy is None
        or extracted.get("policy_id", "").upper() == expected_policy
    )
    band_ok = actual_band == case.expected_fraud_band
    decision_ok = actual_decision == case.expected_decision

    if decision_ok and band_ok:
        return "correct"
    if not extraction_ok:
        return "wrong_extraction"
    if not band_ok and not decision_ok:
        return "wrong_decision_band"
    if not band_ok:
        return "wrong_fraud_band"
    return "wrong_decision"


# ── slice metrics ─────────────────────────────────────────────────────────────


def compute_slice_metrics(results: list[dict]) -> dict[str, dict]:
    """
    Per-slice: accuracy, and per-decision-class precision/recall.
    We do micro-averaged P/R/F1 per slice.
    """
    slices: dict[str, list[dict]] = {}
    for r in results:
        s = r["slice"]
        slices.setdefault(s, []).append(r)

    metrics: dict[str, dict] = {}
    for sl, cases in slices.items():
        total = len(cases)
        correct = sum(1 for c in cases if c["failure_mode"] == "correct")

        # Per-class P/R for decisions
        labels = ["APPROVED", "REJECTED", "ESCALATED"]
        class_metrics: dict[str, dict] = {}
        for label in labels:
            tp = sum(
                1 for c in cases
                if c["expected_decision"] == label and c["actual_decision"] == label
            )
            fp = sum(
                1 for c in cases
                if c["expected_decision"] != label and c["actual_decision"] == label
            )
            fn = sum(
                1 for c in cases
                if c["expected_decision"] == label and c["actual_decision"] != label
            )
            precision = tp / (tp + fp) if (tp + fp) else None
            recall = tp / (tp + fn) if (tp + fn) else None
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision and recall
                else None
            )
            class_metrics[label] = {
                "tp": tp, "fp": fp, "fn": fn,
                "precision": round(precision, 3) if precision is not None else None,
                "recall": round(recall, 3) if recall is not None else None,
                "f1": round(f1, 3) if f1 is not None else None,
            }

        metrics[sl] = {
            "total": total,
            "correct": correct,
            "accuracy_pct": _pct(correct, total),
            "per_decision": class_metrics,
        }

    return metrics


# ── latency summary ───────────────────────────────────────────────────────────


def compute_latency_summary(results: list[dict]) -> dict[str, dict]:
    """p50/p95/p99 latency per node, plus end-to-end."""
    node_times: dict[str, list[float]] = {}
    e2e_times: list[float] = []

    for r in results:
        lat = r.get("node_latencies", {})
        total = sum(lat.values())
        e2e_times.append(total)
        for node, t in lat.items():
            node_times.setdefault(node, []).append(t)

    summary: dict[str, dict] = {}
    for node, times in node_times.items():
        summary[node] = {
            "p50_s": percentile(times, 50),
            "p95_s": percentile(times, 95),
            "p99_s": percentile(times, 99),
            "n": len(times),
        }
    summary["__end_to_end__"] = {
        "p50_s": percentile(e2e_times, 50),
        "p95_s": percentile(e2e_times, 95),
        "p99_s": percentile(e2e_times, 99),
        "n": len(e2e_times),
    }
    return summary


# ── main runner ───────────────────────────────────────────────────────────────


def run_eval(
    cases: list[EvalCase],
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    print(f"\n{'─'*60}")
    print(f"  Claims Triage Agent — Eval Run")
    print(f"  Model : {MODEL}  |  Cases : {len(cases)}")
    print(f"{'─'*60}\n")

    for i, case in enumerate(cases, 1):
        print(f"[{i:02d}/{len(cases):02d}] {case.id} ({case.slice}) ... ", end="", flush=True)

        try:
            state, node_latencies, token_usage = run_case_timed(case.claim_text)
        except Exception as exc:
            # Surface rate limit as a clear message with wait hint
            err_str = str(exc)
            if "rate_limit" in err_str.lower() or "429" in err_str:
                wait = 120  # default 2 min wait
                import re
                m = re.search(r"try again in (\d+)m", err_str)
                if m:
                    wait = int(m.group(1)) * 60 + 30
                print(f"RATE LIMIT — waiting {wait}s before retry...")
                time.sleep(wait)
                try:
                    state, node_latencies, token_usage = run_case_timed(case.claim_text)
                except Exception as exc2:
                    exc = exc2
                    state, node_latencies, token_usage = {}, {}, {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0}
            else:
                state, node_latencies, token_usage = {}, {}, {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0}

            if not state:
                print(f"ERROR: {exc}")
                results.append({
                    "id": case.id,
                    "slice": case.slice,
                    "expected_decision": case.expected_decision,
                    "expected_fraud_band": case.expected_fraud_band,
                    "actual_decision": "ERROR",
                    "actual_fraud_score": None,
                    "actual_fraud_band": "ERROR",
                    "failure_mode": "api_error",
                    "node_latencies": {},
                    "token_usage": {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0},
                    "error": str(exc),
                    "notes": case.notes,
                })
                continue

        decision_dict = state.get("decision") or {}
        fraud_dict = state.get("fraud") or {}
        actual_decision = decision_dict.get("decision", "UNKNOWN")
        actual_score = fraud_dict.get("fraud_score", -1.0)
        actual_band = fraud_band(actual_score) if actual_score >= 0 else "unknown"

        failure = classify_failure(case, state, actual_decision, actual_band)
        e2e = round(sum(node_latencies.values()), 2)

        status = "✓" if failure == "correct" else "✗"
        print(f"{status}  got={actual_decision:<10} expected={case.expected_decision:<10} fraud={actual_score:.2f} [{actual_band}]  {e2e}s")

        results.append({
            "id": case.id,
            "slice": case.slice,
            "expected_decision": case.expected_decision,
            "expected_fraud_band": case.expected_fraud_band,
            "actual_decision": actual_decision,
            "actual_fraud_score": round(actual_score, 3),
            "actual_fraud_band": actual_band,
            "failure_mode": failure,
            "node_latencies": node_latencies,
            "token_usage": token_usage,
            "notes": case.notes,
        })

        # Small inter-case delay to stay within Groq free-tier
        # tokens-per-minute limit (6k TPM). ~4s between cases keeps
        # a 25-case run well within the rolling window.
        time.sleep(4)

    # ── aggregate metrics ────────────────────────────────────────────────────
    total = len(results)
    correct = sum(1 for r in results if r["failure_mode"] == "correct")
    failure_counts: dict[str, int] = {}
    for r in results:
        failure_counts[r["failure_mode"]] = failure_counts.get(r["failure_mode"], 0) + 1

    ci_lo, ci_hi = wilson_ci(correct, total)

    # Aggregate token cost across all cases
    total_tokens_in = sum(r.get("token_usage", {}).get("tokens_in", 0) for r in results)
    total_tokens_out = sum(r.get("token_usage", {}).get("tokens_out", 0) for r in results)
    total_tokens = total_tokens_in + total_tokens_out
    cost_summary = {
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "total_tokens": total_tokens,
        "avg_tokens_per_case": round(total_tokens / total, 1) if total else 0,
        # Groq free tier — approximate cost at paid rate for awareness
        # llama-3.1-70b: $0.59/1M input, $0.79/1M output (as of mid-2025)
        "estimated_cost_usd": round(
            total_tokens_in * 0.59 / 1_000_000
            + total_tokens_out * 0.79 / 1_000_000,
            5,
        ),
    }

    slice_metrics = compute_slice_metrics(results)
    latency_summary = compute_latency_summary(results)

    manifest: dict[str, Any] = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "model": MODEL,
        "temperature": 0,
        "total_cases": total,
        "overall_accuracy_pct": _pct(correct, total),
        "confidence_interval_95pct": {"lower": ci_lo, "upper": ci_hi},
        "failure_breakdown": failure_counts,
        "cost_summary": cost_summary,
        "slice_metrics": slice_metrics,
        "latency_summary": latency_summary,
        "per_case_results": results,
    }

    # ── write outputs ────────────────────────────────────────────────────────
    run_id = manifest["run_id"]
    out_file = out_dir / f"run_{run_id}.json"
    with open(out_file, "w") as f:
        json.dump(manifest, f, indent=2)

    # Also overwrite a stable "latest" symlink-style file for easy diffing
    latest_file = out_dir / "latest.json"
    with open(latest_file, "w") as f:
        json.dump(manifest, f, indent=2)

    # ── print summary ────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  OVERALL ACCURACY : {correct}/{total}  ({_pct(correct,total):.1f}%)")
    print(f"  95% CI (Wilson)  : [{ci_lo:.1f}%, {ci_hi:.1f}%]")
    print(f"{'─'*60}")
    print("  Failure breakdown:")
    for mode, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        print(f"    {mode:<25} {count}")

    print("\n  Per-slice accuracy:")
    for sl, m in slice_metrics.items():
        print(f"    {sl:<12} {m['correct']}/{m['total']}  ({m['accuracy_pct']:.1f}%)")

    print("\n  Latency (end-to-end):")
    e2e = latency_summary.get("__end_to_end__", {})
    print(f"    p50={e2e.get('p50_s','?')}s  p95={e2e.get('p95_s','?')}s  p99={e2e.get('p99_s','?')}s")

    print("\n  Cost (est.):")
    print(f"    {total_tokens:,} tokens total  (~${cost_summary['estimated_cost_usd']:.5f})  "
          f"avg {cost_summary['avg_tokens_per_case']:.0f} tok/case")

    print(f"\n  Results written → {out_file}\n")
    return manifest


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Claims triage agent eval harness")
    parser.add_argument("--slice", help="Run only a specific slice (auto/health/property/fraud/edge)")
    parser.add_argument("--case", help="Run a single case by ID")
    parser.add_argument("--out", default="eval/runs", help="Output directory for run manifests")
    args = parser.parse_args()

    cases = EVAL_DATASET
    if args.case:
        cases = [c for c in cases if c.id == args.case]
        if not cases:
            print(f"No case with id '{args.case}'")
            sys.exit(1)
    elif args.slice:
        cases = [c for c in cases if c.slice == args.slice]
        if not cases:
            print(f"No cases in slice '{args.slice}'")
            sys.exit(1)

    run_eval(cases, out_dir=Path(args.out))


if __name__ == "__main__":
    main()
