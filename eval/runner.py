"""
eval/runner.py

Eval harness for the claims triage agent and its baselines.

Every system (see eval/systems.py) runs on the same pinned cases and is scored
the same way:
  ✓ Decision accuracy (headline) + 95% Wilson CI, macro-F1, confusion matrix
  ✓ Per-slice / per-tier / per-line / per-source accuracy, each with a CI
  ✓ Fraud: band accuracy and AUC-ROC (high vs not-high)
  ✓ Extraction accuracy per field (policy_id / amount / date) vs latent truth
  ✓ Prompt-injection resistance (share of injection cases NOT approved)
  ✓ Stage-level root cause for every wrong decision (eval/attribution.py)
  ✓ Per-node latency p50/p95/p99, tokens and estimated cost per case
  ✓ Run manifest (JSON) with dataset fingerprint, model, per-case results

Robust to free-tier rate limits:
  - LLM responses are cached on disk (agents/llm.py); a re-run is free
  - per-case results are appended to a .partial.jsonl; --resume skips done cases
  - 429s back off and retry instead of recording an error

Usage:
    python -m eval.runner                               # agent, all 231 cases
    python -m eval.runner --system rules                # rules-only baseline (no API key)
    python -m eval.runner --system single_prompt --resume
    python -m eval.runner --split v1                    # the original 25
    python -m eval.runner --slice fraud_story --tier noisy
    python -m eval.runner --case edge_03
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from eval.attribution import attribute  # noqa: E402
from eval.dataset import EVAL_DATASET, EvalCase, get_cases  # noqa: E402
from eval.metrics import (  # noqa: E402
    auc_roc, confusion, counts, grouped_accuracy, macro_f1, per_class_prf, wilson_ci,
)
from eval.metrics import percentile as _pctl  # noqa: E402

try:
    from agents.llm import model_name as _model_name
    MODEL = _model_name()
except Exception:  # pragma: no cover
    MODEL = "llama-3.3-70b-versatile"

FRAUD_BANDS = {"low": (0.0, 0.4), "medium": (0.4, 0.75), "high": (0.75, 1.01)}
# Approximate paid-tier list prices (USD / 1M tokens) for cost awareness only.
PRICES = {"llama-3.3-70b-versatile": (0.59, 0.79), "llama-3.1-8b-instant": (0.05, 0.08)}


# ── helpers kept for backwards compatibility (ablations.py imports these) ───


def fraud_band(score: float) -> str:
    for band, (lo, hi) in FRAUD_BANDS.items():
        if lo <= score < hi:
            return band
    return "high"


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def percentile(values: list[float], p: int) -> float:
    return _pctl(values, p)


def classify_failure(case: EvalCase, state: dict[str, Any], actual_decision: str, actual_band: str) -> str:
    """Root-cause label for one case ('correct' if the decision matches)."""
    score = (state.get("fraud") or {}).get("fraud_score")
    return attribute(case, actual_decision, score, state.get("extracted") or {})["failure_mode"]


def compute_slice_metrics(results: list[dict]) -> dict[str, dict]:
    for r in results:
        r.setdefault("decision_correct", r.get("failure_mode") == "correct")
    return grouped_accuracy(results, "slice")


def compute_latency_summary(results: list[dict]) -> dict[str, dict]:
    node_times: dict[str, list[float]] = {}
    e2e: list[float] = []
    for r in results:
        lat = {k: v for k, v in (r.get("node_latencies") or {}).items() if not k.startswith("__")}
        if not lat:
            continue
        e2e.append(sum(lat.values()))
        for node, t in lat.items():
            node_times.setdefault(node, []).append(t)
    summary = {n: {"p50_s": _pctl(t, 50), "p95_s": _pctl(t, 95), "p99_s": _pctl(t, 99), "n": len(t)}
               for n, t in node_times.items()}
    summary["__end_to_end__"] = {"p50_s": _pctl(e2e, 50), "p95_s": _pctl(e2e, 95),
                                 "p99_s": _pctl(e2e, 99), "n": len(e2e)}
    return summary


# ── one case ────────────────────────────────────────────────────────────────


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return "rate_limit" in s or "rate limit" in s or "429" in s or "too many requests" in s


def _rate_limit_wait(exc: Exception, attempt: int) -> float:
    s = str(exc)
    m = re.search(r"try again in (?:(\d+)m)?\s*(?:([\d.]+)s)?", s)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + float(m.group(2) or 0) + 2
    return min(300, 15 * 2**attempt)


def score_case(system: str, case: EvalCase, max_retries: int = 6) -> dict[str, Any]:
    from eval.systems import run_system

    out, err = None, None
    for attempt in range(max_retries + 1):
        try:
            out = run_system(system, case.claim_text)
            break
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc) and attempt < max_retries:
                wait = _rate_limit_wait(exc, attempt)
                print(f"rate-limited, sleeping {wait:.0f}s … ", end="", flush=True)
                time.sleep(wait)
                continue
            err = f"{type(exc).__name__}: {exc}"
            break

    state = (out or {}).get("state") or {}
    dec = (state.get("decision") or {}).get("decision", "ERROR" if err else "UNKNOWN")
    fraud = state.get("fraud") or {}
    score = fraud.get("fraud_score")
    score = float(score) if isinstance(score, (int, float)) else None
    if state.get("error") and not err:
        err_internal = state["error"]  # @_safe_node fallback fired — keep it visible
    else:
        err_internal = None
    att = attribute(case, dec, score, state.get("extracted") or {}, error=err)
    ext = state.get("extracted") or {}
    return {
        "id": case.id, "slice": case.slice, "line": case.line, "tier": case.tier, "source": case.source,
        "expected_decision": case.expected_decision, "expected_fraud_band": case.expected_fraud_band,
        "actual_decision": dec,
        "actual_fraud_score": round(score, 3) if score is not None else None,
        "actual_fraud_band": fraud_band(score) if score is not None else "unknown",
        "decision_correct": dec == case.expected_decision,
        "band_correct": score is not None and fraud_band(score) == case.expected_fraud_band,
        "failure_mode": att["failure_mode"],
        "evidence": att["evidence"],
        "field_correct": att["fields"],
        "extracted": {k: ext.get(k) for k in ("policy_id", "claimed_amount", "incident_date", "incident_type")},
        "truth": case.truth,
        "justification": (state.get("decision") or {}).get("justification", "")[:300],
        "node_latencies": (out or {}).get("node_latencies", {}),
        "token_usage": (out or {}).get("token_usage", {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0}),
        "error": err or err_internal,
        "notes": case.notes,
    }


# ── aggregate ───────────────────────────────────────────────────────────────


def summarize(results: list[dict], system: str, dataset_fp: str, split: str) -> dict[str, Any]:
    n = len(results)
    correct = sum(r["decision_correct"] for r in results)
    lo, hi = wilson_ci(correct, n)
    y_true = [r["expected_decision"] for r in results]
    y_pred = [r["actual_decision"] for r in results]

    scored = [r for r in results if r["actual_fraud_score"] is not None]
    fraud_auc = auc_roc([r["actual_fraud_score"] for r in scored],
                        [int(r["expected_fraud_band"] == "high") for r in scored])

    def field_acc(f):
        vals = [r["field_correct"][f] for r in results if r["field_correct"].get(f) is not None]
        return {"correct": sum(vals), "total": len(vals), "accuracy_pct": _pct(sum(vals), len(vals))}

    inj = [r for r in results if "prompt_injection" in (r["truth"] or {}).get("flags", [])]
    tin = sum(r["token_usage"].get("tokens_in", 0) for r in results)
    tout = sum(r["token_usage"].get("tokens_out", 0) for r in results)
    pin, pout = PRICES.get(MODEL, (0.59, 0.79))
    cost = tin * pin / 1e6 + tout * pout / 1e6
    strict = sum(r["decision_correct"] and r["band_correct"] for r in results)

    from eval.systems import LLM_SYSTEMS, SYSTEM_DESCRIPTIONS
    return {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "system": system,
        "system_description": SYSTEM_DESCRIPTIONS.get(system, system),
        "model": MODEL if system in LLM_SYSTEMS else None,
        "temperature": 0,
        "dataset_fingerprint": dataset_fp,
        "split": split,
        "total_cases": n,
        "correct": correct,
        "overall_accuracy_pct": _pct(correct, n),
        "confidence_interval_95pct": {"lower": lo, "upper": hi},
        "macro_f1": macro_f1(y_true, y_pred),
        "per_class": per_class_prf(y_true, y_pred),
        "confusion_matrix": confusion(y_true, y_pred),
        "strict_accuracy_pct": _pct(strict, n),
        "fraud_band_accuracy_pct": _pct(sum(r["band_correct"] for r in results), n),
        "fraud_auc_high_vs_rest": fraud_auc,
        "extraction_accuracy": {f: field_acc(f) for f in ("policy_id", "amount", "date")},
        "injection_resistance": {"not_approved": sum(r["actual_decision"] != "APPROVED" for r in inj),
                                 "total": len(inj)},
        "failure_breakdown": counts(results, "failure_mode"),
        "errors": sum(1 for r in results if r["failure_mode"] == "api_error"),
        "slice_metrics": grouped_accuracy(results, "slice"),
        "tier_metrics": grouped_accuracy(results, "tier"),
        "line_metrics": grouped_accuracy(results, "line"),
        "source_metrics": grouped_accuracy(results, "source"),
        "cost_summary": {"total_tokens_in": tin, "total_tokens_out": tout, "total_tokens": tin + tout,
                         "avg_tokens_per_case": round((tin + tout) / n, 1) if n else 0,
                         "estimated_cost_usd": round(cost, 5),
                         "estimated_cost_per_1k_claims_usd": round(1000 * cost / n, 3) if n else 0},
        "latency_summary": compute_latency_summary(results),
        "per_case_results": results,
    }


def dataset_fingerprint() -> str:
    from eval.integrity import _dataset_fingerprint
    return _dataset_fingerprint(EVAL_DATASET)


# ── main ────────────────────────────────────────────────────────────────────


def run_eval(system: str, cases: list[EvalCase], out_dir: Path, split: str = "all",
             resume: bool = False, sleep_s: float | None = None, quiet: bool = False) -> dict[str, Any]:
    from eval.systems import LLM_SYSTEMS

    out_dir.mkdir(parents=True, exist_ok=True)
    fp = dataset_fingerprint()
    partial = out_dir / f"{system}_{fp[:12]}.partial.jsonl"
    done: dict[str, dict] = {}
    if resume and partial.exists():
        for line in partial.read_text().splitlines():
            r = json.loads(line)
            if r["failure_mode"] != "api_error":
                done[r["id"]] = r
    elif partial.exists():
        partial.unlink()
    if sleep_s is None:
        sleep_s = 1.0 if system in LLM_SYSTEMS else 0.0

    if not quiet:
        print(f"\n{'─' * 64}\n  Eval  system={system}  cases={len(cases)}  "
              f"model={MODEL if system in LLM_SYSTEMS else '—'}  resume={len(done)} done\n{'─' * 64}")
    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        if case.id in done:
            results.append(done[case.id])
            continue
        if not quiet:
            print(f"[{i:03d}/{len(cases):03d}] {case.id:<28}", end=" ", flush=True)
        r = score_case(system, case)
        results.append(r)
        with partial.open("a") as f:
            f.write(json.dumps(r) + "\n")
        if not quiet:
            mark = "✓" if r["decision_correct"] else "✗"
            sc = f"{r['actual_fraud_score']:.2f}" if r["actual_fraud_score"] is not None else "  — "
            print(f"{mark} got={r['actual_decision']:<9} exp={r['expected_decision']:<9} "
                  f"fraud={sc} {r['failure_mode'] if not r['decision_correct'] else ''}")
        if sleep_s:
            time.sleep(sleep_s)

    manifest = summarize(results, system, fp, split)
    sys_dir = out_dir / system
    sys_dir.mkdir(exist_ok=True)
    out_file = sys_dir / f"run_{manifest['run_id']}.json"
    out_file.write_text(json.dumps(manifest, indent=2))
    (out_dir / f"latest_{system}.json").write_text(json.dumps(manifest, indent=2))
    if system == "agent":  # back-compat: calibration / diff / monitor default to latest.json
        (out_dir / "latest.json").write_text(json.dumps(manifest, indent=2))
    if manifest["errors"] == 0 and partial.exists():
        partial.unlink()

    if not quiet:
        print_summary(manifest)
        print(f"  Results → {out_file}\n")
    return manifest


def print_summary(m: dict) -> None:
    ci = m["confidence_interval_95pct"]
    print(f"\n{'─' * 64}")
    print(f"  {m['system']}: decision accuracy {m['correct']}/{m['total_cases']} "
          f"({m['overall_accuracy_pct']:.1f}%)  95% CI [{ci['lower']:.1f}, {ci['upper']:.1f}]")
    print(f"  macro-F1 {m['macro_f1']:.3f} | fraud AUC {m['fraud_auc_high_vs_rest']} | "
          f"band acc {m['fraud_band_accuracy_pct']}% | strict {m['strict_accuracy_pct']}%")
    ex = m["extraction_accuracy"]
    print("  extraction: " + ", ".join(f"{k} {v['accuracy_pct']}%" for k, v in ex.items()))
    inj = m["injection_resistance"]
    if inj["total"]:
        print(f"  injection resistance: {inj['not_approved']}/{inj['total']} not approved")
    print("  tiers: " + ", ".join(f"{k} {v['accuracy_pct']}% (n={v['total']})" for k, v in m["tier_metrics"].items()))
    print("  failures: " + ", ".join(f"{k}={v}" for k, v in m["failure_breakdown"].items() if k != "correct"))
    c = m["cost_summary"]
    e2e = m["latency_summary"]["__end_to_end__"]
    print(f"  tokens/case {c['avg_tokens_per_case']:.0f} | ~${c['estimated_cost_per_1k_claims_usd']}/1k claims | "
          f"p50 {e2e['p50_s']}s p95 {e2e['p95_s']}s")
    print(f"{'─' * 64}")


def main() -> None:
    from eval.systems import SYSTEMS
    ap = argparse.ArgumentParser(description="Claims triage eval harness")
    ap.add_argument("--system", default="agent", choices=sorted(SYSTEMS))
    ap.add_argument("--split", default="all", choices=["all", "v1", "v2"])
    ap.add_argument("--slice")
    ap.add_argument("--tier", choices=["canonical", "paraphrase", "noisy"])
    ap.add_argument("--case")
    ap.add_argument("--limit", type=int, help="only the first N cases (smoke test)")
    ap.add_argument("--resume", action="store_true", help="skip cases already in the .partial.jsonl")
    ap.add_argument("--sleep", type=float, help="seconds between cases (default 1 for LLM systems)")
    ap.add_argument("--out", default="eval/runs")
    args = ap.parse_args()

    cases = get_cases(args.split, slice_=args.slice, tier=args.tier, case_id=args.case)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("No cases match those filters.")
        sys.exit(1)
    run_eval(args.system, cases, Path(args.out), split=args.split, resume=args.resume, sleep_s=args.sleep)


if __name__ == "__main__":
    main()
