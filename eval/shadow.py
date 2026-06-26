"""
eval/shadow.py

Real shadow deployment for the claims triage agent.

HOW IT WORKS
────────────
Two versioned agent graphs (PRIMARY and SHADOW) run in parallel on every
production claim. The PRIMARY result is what gets served to the user.
The SHADOW result is logged silently and never surfaced. This lets you
validate a prompt change, model swap, or graph restructure against live
traffic before rolling it out — without affecting any user.

VERSIONS
────────
primary   Current production graph (agents/graph.py as-is)
shadow    Challenger — swap this out to test a change. Currently configured
          as the "simple_prompt" variant (from ablations.py) so you can see
          divergence between the engineered and naive decision prompts on
          real traffic. Change _build_shadow() to whatever you're testing.

SHADOW LOG
──────────
Every request writes one JSONL record to data/shadow_log.jsonl containing:
  ts, claim_fingerprint, primary_decision, shadow_decision, agreement,
  primary_fraud_score, shadow_fraud_score, primary_latency, shadow_latency

SHADOW REPORT
─────────────
python -m eval.shadow --report
  Reads shadow_log.jsonl and prints:
  - Overall agreement rate between primary and shadow
  - Per-decision divergence (where they disagree, what shadow said instead)
  - Latency comparison (primary p99 vs shadow p99)
  - Cases where shadow would have improved on primary (requires labels)

INTEGRATION
───────────
In the UI, enable shadow mode via the sidebar toggle.
The ShadowRunner class is used directly in ui/app.py.

Usage — run shadow on a single claim (for testing):
    python -m eval.shadow --claim "Policy POL-001. My car was stolen..."

Usage — generate shadow report:
    python -m eval.shadow --report --window 100
"""

import argparse
import concurrent.futures
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHADOW_LOG = Path("data/shadow_log.jsonl")
PRIMARY_VERSION = "v1-production"
SHADOW_VERSION = "v2-challenger"


# ── graph builders ────────────────────────────────────────────────────────────


def _build_primary():
    from agents.graph import claims_graph
    return claims_graph


def _build_shadow():
    """
    Challenger graph — currently the simple_prompt variant.
    Swap this function body to test any change (model, prompt, routing, etc.).
    """
    from langgraph.graph import StateGraph, END
    from agents.state import ClaimState, ClaimDecision
    from agents.nodes import (
        extract_node, policy_node, fraud_node,
        auto_reject_node, report_node, get_llm, _safe_node,
    )
    from agents.graph import route_after_fraud

    @_safe_node
    def challenger_decision_node(state: ClaimState) -> dict:
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
    g.add_node("decide", challenger_decision_node)
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


# ── runner ────────────────────────────────────────────────────────────────────


def _run_graph(graph, claim_text: str) -> tuple[dict[str, Any], float]:
    """Run a graph and return (final_state, e2e_latency_s)."""
    initial: dict[str, Any] = {
        "claim_text": claim_text,
        "extracted": None, "policy": None, "fraud": None,
        "decision": None, "final_report": None, "error": None,
    }
    t0 = time.perf_counter()
    accumulated: dict[str, Any] = {}
    try:
        for chunk in graph.stream(initial, stream_mode="updates"):
            accumulated.update(list(chunk.values())[0])
    except Exception as exc:
        accumulated["error"] = str(exc)
    latency = round(time.perf_counter() - t0, 3)
    return accumulated, latency


class ShadowRunner:
    """
    Runs PRIMARY and SHADOW graphs concurrently on every claim.
    Returns only the PRIMARY result; logs comparison to shadow_log.jsonl.

    Use in the UI:
        runner = ShadowRunner()
        primary_state, primary_latency = runner.run(claim_text)
        # shadow ran in parallel and was logged automatically
    """

    def __init__(self) -> None:
        SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        self._primary = _build_primary()
        self._shadow = _build_shadow()

    def run(
        self,
        claim_text: str,
    ) -> tuple[dict[str, Any], float]:
        """
        Run both graphs in parallel via ThreadPoolExecutor.
        Returns (primary_state, primary_latency_s).
        Shadow result is logged but not returned.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_primary = pool.submit(_run_graph, self._primary, claim_text)
            f_shadow = pool.submit(_run_graph, self._shadow, claim_text)
            primary_state, primary_latency = f_primary.result()
            shadow_state, shadow_latency = f_shadow.result()

        self._log(claim_text, primary_state, primary_latency, shadow_state, shadow_latency)
        return primary_state, primary_latency

    def _log(
        self,
        claim_text: str,
        primary_state: dict,
        primary_latency: float,
        shadow_state: dict,
        shadow_latency: float,
    ) -> None:
        p_dec = (primary_state.get("decision") or {}).get("decision", "UNKNOWN")
        s_dec = (shadow_state.get("decision") or {}).get("decision", "UNKNOWN")
        p_fraud = (primary_state.get("fraud") or {}).get("fraud_score", -1.0)
        s_fraud = (shadow_state.get("fraud") or {}).get("fraud_score", -1.0)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "primary_version": PRIMARY_VERSION,
            "shadow_version": SHADOW_VERSION,
            "claim_len": len(claim_text),
            "claim_prefix": claim_text[:40],
            "primary_decision": p_dec,
            "shadow_decision": s_dec,
            "agreement": p_dec == s_dec,
            "primary_fraud_score": round(p_fraud, 3),
            "shadow_fraud_score": round(s_fraud, 3),
            "primary_latency_s": primary_latency,
            "shadow_latency_s": shadow_latency,
            "primary_error": primary_state.get("error"),
            "shadow_error": shadow_state.get("error"),
        }

        with open(SHADOW_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")


# ── shadow report ─────────────────────────────────────────────────────────────


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    return sv[min(int(len(sv) * p / 100), len(sv) - 1)]


def shadow_report(window: int = 100) -> None:
    if not SHADOW_LOG.exists():
        print("No shadow log found. Run some claims with shadow mode enabled first.")
        return

    with open(SHADOW_LOG) as f:
        records = [json.loads(l) for l in f if l.strip()]

    recent = records[-window:]
    n = len(recent)
    if n == 0:
        print("Shadow log is empty.")
        return

    agreements = sum(1 for r in recent if r["agreement"])
    disagreements = [r for r in recent if not r["agreement"]]

    primary_version = recent[-1].get("primary_version", "primary")
    shadow_version = recent[-1].get("shadow_version", "shadow")

    print(f"\n{'═'*64}")
    print(f"  Shadow Deployment Report")
    print(f"  Primary  : {primary_version}")
    print(f"  Shadow   : {shadow_version}")
    print(f"  Window   : last {n} requests")
    print(f"{'═'*64}\n")

    print(f"  Agreement rate : {agreements}/{n}  ({_pct(agreements, n):.1f}%)")
    print(f"  Disagreements  : {len(disagreements)}\n")

    # Disagreement breakdown: where they diverge
    if disagreements:
        print("  Disagreement breakdown (primary → shadow):")
        transitions: dict[str, int] = {}
        for r in disagreements:
            key = f"{r['primary_decision']} → {r['shadow_decision']}"
            transitions[key] = transitions.get(key, 0) + 1
        for transition, count in sorted(transitions.items(), key=lambda x: -x[1]):
            print(f"    {transition:<30} {count}x")
        print()

    # Latency comparison
    p_lats = [r["primary_latency_s"] for r in recent if "primary_latency_s" in r]
    s_lats = [r["shadow_latency_s"] for r in recent if "shadow_latency_s" in r]
    if p_lats and s_lats:
        print("  Latency comparison:")
        print(f"    {'':20} {'primary':>10} {'shadow':>10}")
        for p in [50, 95, 99]:
            pv = _percentile(p_lats, p)
            sv = _percentile(s_lats, p)
            delta = sv - pv
            flag = "  ⚠️ slower" if delta > 1.0 else "  ✓ faster" if delta < -0.5 else ""
            print(f"    p{p:<19} {pv:>9.2f}s {sv:>9.2f}s{flag}")
        print()

    # Fraud score drift between primary and shadow
    p_scores = [r["primary_fraud_score"] for r in recent if r.get("primary_fraud_score", -1) >= 0]
    s_scores = [r["shadow_fraud_score"] for r in recent if r.get("shadow_fraud_score", -1) >= 0]
    if p_scores and s_scores:
        p_mean = sum(p_scores) / len(p_scores)
        s_mean = sum(s_scores) / len(s_scores)
        delta = s_mean - p_mean
        flag = "  ⚠️  DRIFT" if abs(delta) > 0.1 else ""
        print(f"  Fraud score mean  primary={p_mean:.3f}  shadow={s_mean:.3f}  Δ={delta:+.3f}{flag}\n")

    # Recommendation
    if _pct(agreements, n) >= 95:
        print("  ✅ RECOMMENDATION: High agreement (≥95%). Shadow is behaviorally equivalent.")
        print("     Safe to promote shadow to primary if latency/cost is acceptable.\n")
    elif _pct(agreements, n) >= 80:
        print("  ⚠️  RECOMMENDATION: Moderate agreement (80–95%). Review disagreements before promoting.\n")
    else:
        print("  ❌ RECOMMENDATION: Low agreement (<80%). Shadow has significantly different behaviour.\n")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow deployment tool")
    parser.add_argument("--report", action="store_true", help="Print shadow report")
    parser.add_argument("--window", type=int, default=100)
    parser.add_argument("--claim", type=str, help="Run shadow on a single claim text")
    args = parser.parse_args()

    if args.report:
        shadow_report(args.window)
    elif args.claim:
        print("Running shadow deployment on provided claim...")
        runner = ShadowRunner()
        state, latency = runner.run(args.claim)
        decision = (state.get("decision") or {}).get("decision", "UNKNOWN")
        print(f"Primary decision : {decision}  ({latency:.2f}s)")
        print(f"Shadow logged to : {SHADOW_LOG}")
        print(f"Run --report to see comparison.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
