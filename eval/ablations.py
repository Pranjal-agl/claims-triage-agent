"""
eval/ablations.py

Ablation suite for the claims triage agent.

Runs four pipeline variants against the full eval set and produces a
side-by-side comparison table isolating each component's contribution.

VARIANTS
────────
baseline        Full pipeline: extract → policy_lookup → fraud → route → decide
no_fraud        Bypass fraud node: always pass fraud_score=0.0 to decide.
                Measures: what does the fraud assessment node contribute?
no_policy       Inject "policy not found" regardless of actual policy ID.
                Measures: how much does DB grounding help vs LLM reasoning alone?
simple_prompt   Replace the decision node's detailed rule prompt with a short,
                unstructured prompt. Measures: sensitivity to prompt engineering.

WHAT TO LOOK FOR
────────────────
- If `no_fraud` accuracy is close to `baseline`: fraud node adds little — the
  decision node is already catching fraud signals from the claim text alone.
- If `no_policy` accuracy drops sharply: policy lookup is load-bearing.
- If `simple_prompt` accuracy drops: the structured decision rules in the prompt
  matter, not just the model's prior knowledge.

Each variant writes a run manifest to eval/runs/ablation_<variant>_<ts>.json.
The suite prints a comparison table at the end.

Usage:
    python -m eval.ablations                      # run all 4 variants
    python -m eval.ablations --variant no_fraud   # single variant
    python -m eval.ablations --slice fraud        # restrict to one slice
"""

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from eval.dataset import EVAL_DATASET, EvalCase
from eval.runner import (
    MODEL,
    _pct,
    classify_failure,
    compute_latency_summary,
    compute_slice_metrics,
    fraud_band,
    percentile,
    wilson_ci,
)

VARIANTS = ["baseline", "no_fraud", "no_policy", "simple_prompt"]


# ── variant graph builders ────────────────────────────────────────────────────


def _build_baseline():
    from agents.graph import claims_graph
    return claims_graph


def _build_no_fraud():
    """
    Bypass the fraud assessment node entirely.
    Injects fraud_score=0.0 (low risk) so routing always goes to decide.
    This isolates the contribution of the fraud scorer.
    """
    from langgraph.graph import StateGraph, END
    from agents.state import ClaimState
    from agents.nodes import extract_node, policy_node, decision_node, report_node

    def no_fraud_node(state: ClaimState) -> dict:
        return {
            "fraud": {
                "fraud_score": 0.0,
                "flags": [],
                "reasoning": "[ABLATION: fraud node bypassed]",
            }
        }

    g = StateGraph(ClaimState)
    g.add_node("extract", extract_node)
    g.add_node("lookup_policy", policy_node)
    g.add_node("assess_fraud", no_fraud_node)
    g.add_node("decide", decision_node)
    g.add_node("generate_report", report_node)

    g.set_entry_point("extract")
    g.add_edge("extract", "lookup_policy")
    g.add_edge("lookup_policy", "assess_fraud")
    g.add_edge("assess_fraud", "decide")   # no conditional routing — always decide
    g.add_edge("decide", "generate_report")
    g.add_edge("generate_report", END)

    return g.compile()


def _build_no_policy():
    """
    Inject "policy not found" regardless of the actual policy ID.
    Decision node must rely on LLM reasoning alone without DB grounding.
    Isolates the contribution of the policy lookup node.
    """
    from langgraph.graph import StateGraph, END
    from agents.state import ClaimState
    from agents.nodes import extract_node, fraud_node, auto_reject_node, decision_node, report_node
    from agents.graph import route_after_fraud

    def no_policy_node(state: ClaimState) -> dict:
        return {
            "policy": {
                "found": False,
                "policy_id": state["extracted"].get("policy_id", ""),
                "error": "[ABLATION: policy lookup bypassed]",
            }
        }

    g = StateGraph(ClaimState)
    g.add_node("extract", extract_node)
    g.add_node("lookup_policy", no_policy_node)
    g.add_node("assess_fraud", fraud_node)
    g.add_node("auto_reject", auto_reject_node)
    g.add_node("decide", decision_node)
    g.add_node("generate_report", report_node)

    g.set_entry_point("extract")
    g.add_edge("extract", "lookup_policy")
    g.add_edge("lookup_policy", "assess_fraud")
    g.add_conditional_edges(
        "assess_fraud",
        route_after_fraud,
        {"auto_reject": "auto_reject", "decide": "decide"},
    )
    g.add_edge("auto_reject", "generate_report")
    g.add_edge("decide", "generate_report")
    g.add_edge("generate_report", END)

    return g.compile()


def _build_simple_prompt():
    """
    Replace the structured decision prompt with a minimal unstructured one.
    Tests sensitivity to prompt engineering on the decision node.
    """
    from langgraph.graph import StateGraph, END
    from agents.state import ClaimState, ClaimDecision
    from agents.nodes import (
        extract_node, policy_node, fraud_node,
        auto_reject_node, report_node, get_llm, _safe_node,
    )
    from agents.graph import route_after_fraud

    @_safe_node
    def simple_decision_node(state: ClaimState) -> dict:
        llm = get_llm().with_structured_output(ClaimDecision)
        extracted = state.get("extracted") or {}
        policy = state.get("policy") or {}
        fraud = state.get("fraud") or {}
        result = llm.invoke(
            f"You are an insurance claims adjuster. "
            f"Claim: {extracted}. "
            f"Policy: {policy}. "
            f"Fraud assessment: {fraud}. "
            f"Make a decision: APPROVED, REJECTED, or ESCALATED."
        )
        return {"decision": result.model_dump()}

    g = StateGraph(ClaimState)
    g.add_node("extract", extract_node)
    g.add_node("lookup_policy", policy_node)
    g.add_node("assess_fraud", fraud_node)
    g.add_node("auto_reject", auto_reject_node)
    g.add_node("decide", simple_decision_node)
    g.add_node("generate_report", report_node)

    g.set_entry_point("extract")
    g.add_edge("extract", "lookup_policy")
    g.add_edge("lookup_policy", "assess_fraud")
    g.add_conditional_edges(
        "assess_fraud",
        route_after_fraud,
        {"auto_reject": "auto_reject", "decide": "decide"},
    )
    g.add_edge("auto_reject", "generate_report")
    g.add_edge("decide", "generate_report")
    g.add_edge("generate_report", END)

    return g.compile()


VARIANT_BUILDERS = {
    "baseline":     _build_baseline,
    "no_fraud":     _build_no_fraud,
    "no_policy":    _build_no_policy,
    "simple_prompt": _build_simple_prompt,
}

VARIANT_DESCRIPTIONS = {
    "baseline":      "Full pipeline (extract → policy → fraud → route → decide)",
    "no_fraud":      "Fraud node bypassed (score=0, always routes to decide)",
    "no_policy":     "Policy lookup bypassed (always returns 'not found')",
    "simple_prompt": "Decision node uses minimal unstructured prompt",
}


# ── single variant runner ─────────────────────────────────────────────────────


def run_variant(
    variant: str,
    cases: list[EvalCase],
    out_dir: Path,
) -> dict[str, Any]:
    graph = VARIANT_BUILDERS[variant]()
    results = []

    print(f"\n  [{variant}]  {VARIANT_DESCRIPTIONS[variant]}")
    print(f"  {'─'*54}")

    for case in cases:
        initial: dict[str, Any] = {
            "claim_text": case.claim_text,
            "extracted": None,
            "policy": None,
            "fraud": None,
            "decision": None,
            "final_report": None,
            "error": None,
        }

        t0 = time.perf_counter()
        accumulated: dict[str, Any] = {}
        node_latencies: dict[str, float] = {}
        t_prev = t0

        try:
            for chunk in graph.stream(initial, stream_mode="updates"):
                t_now = time.perf_counter()
                node_name = list(chunk.keys())[0]
                node_latencies[node_name] = round(t_now - t_prev, 3)
                accumulated.update(chunk[node_name])
                t_prev = t_now
        except Exception as exc:
            results.append({
                "id": case.id, "slice": case.slice,
                "expected_decision": case.expected_decision,
                "expected_fraud_band": case.expected_fraud_band,
                "actual_decision": "ERROR", "actual_fraud_score": -1.0,
                "actual_fraud_band": "unknown",
                "failure_mode": "api_error",
                "node_latencies": {}, "error": str(exc), "notes": case.notes,
            })
            print(f"    {case.id:<12} ERROR: {exc}")
            continue

        decision_dict = accumulated.get("decision") or {}
        fraud_dict = accumulated.get("fraud") or {}
        actual_decision = decision_dict.get("decision", "UNKNOWN")
        actual_score = fraud_dict.get("fraud_score", -1.0)
        actual_band = fraud_band(actual_score) if actual_score >= 0 else "unknown"
        failure = classify_failure(case, accumulated, actual_decision, actual_band)
        e2e = round(time.perf_counter() - t0, 2)
        status = "✓" if failure == "correct" else "✗"
        print(f"    {case.id:<12} {status} got={actual_decision:<10} expected={case.expected_decision:<10} {e2e}s")

        results.append({
            "id": case.id, "slice": case.slice,
            "expected_decision": case.expected_decision,
            "expected_fraud_band": case.expected_fraud_band,
            "actual_decision": actual_decision,
            "actual_fraud_score": round(actual_score, 3),
            "actual_fraud_band": actual_band,
            "failure_mode": failure,
            "node_latencies": node_latencies,
            "notes": case.notes,
        })

    total = len(results)
    correct = sum(1 for r in results if r["failure_mode"] == "correct")
    ci_lo, ci_hi = wilson_ci(correct, total)
    e2e_times = [sum(r["node_latencies"].values()) for r in results if r["node_latencies"]]
    failure_counts: dict[str, int] = {}
    for r in results:
        failure_counts[r["failure_mode"]] = failure_counts.get(r["failure_mode"], 0) + 1

    manifest: dict[str, Any] = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "variant": variant,
        "variant_description": VARIANT_DESCRIPTIONS[variant],
        "model": MODEL,
        "temperature": 0,
        "total_cases": total,
        "correct": correct,
        "overall_accuracy_pct": _pct(correct, total),
        "confidence_interval_95pct": {"lower": ci_lo, "upper": ci_hi},
        "failure_breakdown": failure_counts,
        "slice_metrics": compute_slice_metrics(results),
        "latency_summary": compute_latency_summary(results),
        "per_case_results": results,
    }

    ts = manifest["run_id"]
    out_file = out_dir / f"ablation_{variant}_{ts}.json"
    with open(out_file, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


# ── comparison table ──────────────────────────────────────────────────────────


def print_comparison(manifests: dict[str, dict]) -> None:
    slices = sorted({
        sl
        for m in manifests.values()
        for sl in m.get("slice_metrics", {})
    })

    print(f"\n{'═'*72}")
    print(f"  ABLATION RESULTS — Component Contribution Analysis")
    print(f"{'═'*72}\n")

    # Header
    col_w = 14
    header = f"  {'Metric':<22}" + "".join(f"{v:>{col_w}}" for v in manifests)
    print(header)
    print(f"  {'─'*22}" + "─" * (col_w * len(manifests)))

    # Overall accuracy
    row = f"  {'Overall accuracy':<22}"
    for m in manifests.values():
        val = f"{m['overall_accuracy_pct']:.1f}%"
        row += f"{val:>{col_w}}"
    print(row)

    # 95% CI
    row = f"  {'95% CI (lower)':<22}"
    for m in manifests.values():
        val = f"{m['confidence_interval_95pct']['lower']:.1f}%"
        row += f"{val:>{col_w}}"
    print(row)

    row = f"  {'95% CI (upper)':<22}"
    for m in manifests.values():
        val = f"{m['confidence_interval_95pct']['upper']:.1f}%"
        row += f"{val:>{col_w}}"
    print(row)

    print()

    # Per-slice
    for sl in slices:
        row = f"  {f'  {sl} accuracy':<22}"
        for m in manifests.values():
            sm = m.get("slice_metrics", {}).get(sl, {})
            acc = sm.get("accuracy_pct", 0)
            n = sm.get("total", 0)
            val = f"{acc:.1f}% ({sm.get('correct',0)}/{n})"
            row += f"{val:>{col_w}}"
        print(row)

    print()

    # Latency p99
    row = f"  {'p99 latency (e2e)':<22}"
    for m in manifests.values():
        val = f"{m['latency_summary'].get('__end_to_end__', {}).get('p99_s', '?')}s"
        row += f"{val:>{col_w}}"
    print(row)

    print()

    # Delta vs baseline
    if "baseline" in manifests:
        base_acc = manifests["baseline"]["overall_accuracy_pct"]
        print(f"  {'Δ vs baseline':<22}", end="")
        for variant, m in manifests.items():
            if variant == "baseline":
                print(f"{'—':>{col_w}}", end="")
            else:
                delta = m["overall_accuracy_pct"] - base_acc
                sign = "+" if delta >= 0 else ""
                val = f"{sign}{delta:.1f}pp"
                print(f"{val:>{col_w}}", end="")
        print()

    print(f"\n{'═'*72}\n")

    # Interpretation
    if "baseline" in manifests and "no_fraud" in manifests:
        delta_fraud = manifests["no_fraud"]["overall_accuracy_pct"] - manifests["baseline"]["overall_accuracy_pct"]
        print(f"  INTERPRETATION")
        print(f"  ─────────────")
        print(f"  • Fraud node contribution : {abs(delta_fraud):.1f}pp accuracy "
              f"({'gain' if delta_fraud < 0 else 'no gain — decision node absorbs fraud signals'})")
    if "baseline" in manifests and "no_policy" in manifests:
        delta_pol = manifests["no_policy"]["overall_accuracy_pct"] - manifests["baseline"]["overall_accuracy_pct"]
        print(f"  • Policy lookup contribution : {abs(delta_pol):.1f}pp accuracy "
              f"({'critical' if delta_pol < -10 else 'moderate' if delta_pol < 0 else 'minimal'})")
    if "baseline" in manifests and "simple_prompt" in manifests:
        delta_prompt = manifests["simple_prompt"]["overall_accuracy_pct"] - manifests["baseline"]["overall_accuracy_pct"]
        print(f"  • Prompt engineering contribution : {abs(delta_prompt):.1f}pp accuracy "
              f"({'significant' if abs(delta_prompt) > 10 else 'moderate' if abs(delta_prompt) > 5 else 'minimal'})")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Claims agent ablation suite")
    parser.add_argument("--variant", choices=VARIANTS, help="Run a single variant only")
    parser.add_argument("--slice", help="Restrict to one eval slice")
    parser.add_argument("--out", default="eval/runs", help="Output directory")
    args = parser.parse_args()

    cases = EVAL_DATASET
    if args.slice:
        cases = [c for c in cases if c.slice == args.slice]
        if not cases:
            print(f"No cases in slice '{args.slice}'")
            sys.exit(1)

    variants_to_run = [args.variant] if args.variant else VARIANTS
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'═'*72}")
    print(f"  Ablation Suite  |  variants={variants_to_run}  |  cases={len(cases)}")
    print(f"{'═'*72}")

    manifests: dict[str, dict] = {}
    for variant in variants_to_run:
        manifests[variant] = run_variant(variant, cases, out_dir)

    if len(manifests) > 1:
        print_comparison(manifests)

    # Write combined summary
    summary_file = out_dir / f"ablations_summary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    with open(summary_file, "w") as f:
        json.dump(
            {v: {k: m[k] for k in ("overall_accuracy_pct", "confidence_interval_95pct",
                                    "failure_breakdown", "slice_metrics", "latency_summary")}
             for v, m in manifests.items()},
            f, indent=2,
        )
    print(f"  Summary written → {summary_file}\n")


if __name__ == "__main__":
    main()
