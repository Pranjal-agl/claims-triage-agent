"""
eval/diff.py

Compare two eval run manifests to track regression / improvement.

Usage:
    python -m eval.diff eval/runs/run_A.json eval/runs/run_B.json
    python -m eval.diff eval/runs/run_A.json eval/runs/latest.json

Prints:
  - Overall accuracy delta
  - Per-slice accuracy delta
  - Cases that flipped: correct→wrong or wrong→correct
  - Latency delta (p99 end-to-end)
"""

import json
import sys
from pathlib import Path


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def diff(a: dict, b: dict) -> None:
    print(f"\n{'─'*60}")
    print(f"  Regression Diff")
    print(f"  A : {a['run_id']}  (model={a['model']})")
    print(f"  B : {b['run_id']}  (model={b['model']})")
    print(f"{'─'*60}\n")

    acc_a = a["overall_accuracy_pct"]
    acc_b = b["overall_accuracy_pct"]
    delta = round(acc_b - acc_a, 1)
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "─")
    print(f"  Overall accuracy : {acc_a:.1f}% → {acc_b:.1f}%  {arrow} {abs(delta):.1f}pp\n")

    print("  Per-slice:")
    slices_a = a.get("slice_metrics", {})
    slices_b = b.get("slice_metrics", {})
    all_slices = sorted(set(slices_a) | set(slices_b))
    for sl in all_slices:
        va = slices_a.get(sl, {}).get("accuracy_pct", 0)
        vb = slices_b.get(sl, {}).get("accuracy_pct", 0)
        d = round(vb - va, 1)
        arrow = "▲" if d > 0 else ("▼" if d < 0 else "─")
        print(f"    {sl:<12} {va:.1f}% → {vb:.1f}%  {arrow} {abs(d):.1f}pp")

    # Flipped cases
    results_a = {r["id"]: r for r in a.get("per_case_results", [])}
    results_b = {r["id"]: r for r in b.get("per_case_results", [])}
    all_ids = sorted(set(results_a) | set(results_b))

    regressions = []
    improvements = []
    for cid in all_ids:
        ra = results_a.get(cid, {})
        rb = results_b.get(cid, {})
        was_correct = ra.get("failure_mode") == "correct"
        now_correct = rb.get("failure_mode") == "correct"
        if was_correct and not now_correct:
            regressions.append((cid, ra.get("slice"), rb.get("failure_mode")))
        elif not was_correct and now_correct:
            improvements.append((cid, ra.get("slice"), ra.get("failure_mode")))

    if improvements:
        print(f"\n  Fixed ({len(improvements)}):")
        for cid, sl, old_mode in improvements:
            print(f"    ✓ {cid} ({sl})  was: {old_mode}")
    if regressions:
        print(f"\n  Regressed ({len(regressions)}):")
        for cid, sl, new_mode in regressions:
            print(f"    ✗ {cid} ({sl})  now: {new_mode}")
    if not improvements and not regressions:
        print("\n  No cases flipped.")

    # Latency
    lat_a = a.get("latency_summary", {}).get("__end_to_end__", {})
    lat_b = b.get("latency_summary", {}).get("__end_to_end__", {})
    p99_a = lat_a.get("p99_s", "?")
    p99_b = lat_b.get("p99_s", "?")
    print(f"\n  p99 latency (e2e) : {p99_a}s → {p99_b}s")
    print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m eval.diff <run_a.json> <run_b.json>")
        sys.exit(1)
    a = load(sys.argv[1])
    b = load(sys.argv[2])
    diff(a, b)
