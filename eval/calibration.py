"""
eval/calibration.py

Fraud score calibration analysis.

A well-calibrated fraud scorer produces high scores for actual fraud cases
and low scores for legitimate ones. This module measures that:

1. SCORE DISTRIBUTION by ground truth
   For each eval case, bucket the fraud_score by (expected_fraud_band × outcome).
   A well-calibrated scorer should show clear separation between fraud and
   non-fraud score distributions.

2. CALIBRATION CURVE
   Group cases by fraud score decile (0–0.1, 0.1–0.2, …) and compute:
   - Mean predicted fraud score in the bucket
   - Fraction of cases in that bucket that were true fraud (expected_band=high)
   Perfect calibration: these two numbers should be equal (score == frequency).

3. DISCRIMINATION METRICS
   - AUC-ROC approximation (trapezoidal rule, no sklearn needed)
   - Brier score (mean squared error of fraud_score vs binary fraud label)

Reads from a run manifest (eval/runs/latest.json by default).

Usage:
    python -m eval.calibration                           # from latest run
    python -m eval.calibration --run eval/runs/run_X.json
    python -m eval.calibration --plot                    # ASCII plot in terminal
"""

import argparse
import json
import math
import sys
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_fraud(expected_band: str) -> int:
    """Binary fraud label: 1 if expected_band=high, 0 otherwise."""
    return 1 if expected_band == "high" else 0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _auc_roc(scores: list[float], labels: list[int]) -> float:
    """
    Trapezoidal AUC-ROC. No external dependencies.
    AUC=0.5 → random; AUC=1.0 → perfect discrimination.
    """
    pairs = sorted(zip(scores, labels), key=lambda x: -x[0])
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    tpr_pts, fpr_pts = [0.0], [0.0]
    tp, fp = 0, 0
    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        tpr_pts.append(tp / n_pos)
        fpr_pts.append(fp / n_neg)

    # Trapezoidal integration
    auc = sum(
        (fpr_pts[i] - fpr_pts[i - 1]) * (tpr_pts[i] + tpr_pts[i - 1]) / 2
        for i in range(1, len(tpr_pts))
    )
    return round(auc, 4)


def _brier_score(scores: list[float], labels: list[int]) -> float:
    """
    Brier score = mean((score - label)^2).
    Lower is better; 0.0 = perfect, 0.25 = random (for balanced classes).
    """
    if not scores:
        return float("nan")
    return round(sum((s - l) ** 2 for s, l in zip(scores, labels)) / len(scores), 4)


def _ascii_bar(value: float, max_val: float = 1.0, width: int = 20) -> str:
    filled = int(round(value / max_val * width))
    return "█" * filled + "░" * (width - filled)


# ── main analysis ─────────────────────────────────────────────────────────────


def calibration_report(manifest_path: Path, plot: bool = False) -> dict:
    with open(manifest_path) as f:
        manifest = json.load(f)

    cases = manifest.get("per_case_results", [])
    if not cases:
        print("No per-case results in manifest.")
        sys.exit(1)

    # Filter cases where we have a fraud score
    valid = [
        c for c in cases
        if c.get("actual_fraud_score") is not None and c["actual_fraud_score"] >= 0
    ]

    scores = [c["actual_fraud_score"] for c in valid]
    labels = [_is_fraud(c["expected_fraud_band"]) for c in valid]
    outcomes = [c["failure_mode"] == "correct" for c in valid]

    auc = _auc_roc(scores, labels)
    brier = _brier_score(scores, labels)

    # Score distribution by band + outcome
    bands = {"low": [], "medium": [], "high": []}
    for c in valid:
        band = c["expected_fraud_band"]
        if band in bands:
            bands[band].append(c["actual_fraud_score"])

    # Calibration curve: 10 buckets
    buckets: list[dict] = []
    n_buckets = 10
    for i in range(n_buckets):
        lo = i / n_buckets
        hi = (i + 1) / n_buckets
        bucket_cases = [c for c in valid if lo <= c["actual_fraud_score"] < hi]
        if not bucket_cases:
            buckets.append({
                "range": f"{lo:.1f}–{hi:.1f}",
                "n": 0,
                "mean_score": (lo + hi) / 2,
                "fraud_fraction": None,
            })
        else:
            fraud_frac = sum(_is_fraud(c["expected_fraud_band"]) for c in bucket_cases) / len(bucket_cases)
            mean_score = _mean([c["actual_fraud_score"] for c in bucket_cases])
            buckets.append({
                "range": f"{lo:.1f}–{hi:.1f}",
                "n": len(bucket_cases),
                "mean_score": round(mean_score, 3),
                "fraud_fraction": round(fraud_frac, 3),
            })

    # ── print report ──────────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  Fraud Score Calibration Report")
    print(f"  Source : {manifest_path.name}")
    print(f"  Cases  : {len(valid)} with valid fraud scores")
    print(f"{'═'*60}\n")

    print(f"  Discrimination metrics:")
    print(f"    AUC-ROC    : {auc:.4f}  (1.0=perfect, 0.5=random)")
    print(f"    Brier score: {brier:.4f}  (0.0=perfect, 0.25=random)\n")

    print("  Score distribution by expected fraud band:")
    for band, band_scores in bands.items():
        if band_scores:
            mean_s = _mean(band_scores)
            min_s = min(band_scores)
            max_s = max(band_scores)
            bar = _ascii_bar(mean_s) if plot else ""
            print(f"    {band:<8}  n={len(band_scores):2d}  "
                  f"mean={mean_s:.3f}  range=[{min_s:.2f}, {max_s:.2f}]  {bar}")
        else:
            print(f"    {band:<8}  n= 0  (no cases)")
    print()

    # Ideal separation check
    if bands["high"] and bands["low"]:
        mean_fraud = _mean(bands["high"])
        mean_legit = _mean(bands["low"])
        separation = mean_fraud - mean_legit
        flag = "✓ good" if separation > 0.3 else "⚠️  poor"
        print(f"  Fraud vs legit mean separation : {separation:+.3f}  ({flag})\n")

    print("  Calibration curve (predicted score vs actual fraud fraction):")
    print(f"    {'Bucket':<10} {'n':>4} {'mean score':>12} {'fraud %':>10}  {'alignment':}")
    for b in buckets:
        if b["n"] == 0:
            print(f"    {b['range']:<10} {'—':>4}")
            continue
        frac = b["fraud_fraction"]
        score = b["mean_score"]
        # Alignment: how close is the predicted score to the actual fraud fraction?
        if frac is not None:
            error = abs(score - frac)
            align = "✓" if error < 0.15 else "~" if error < 0.3 else "✗"
        else:
            align = "?"
        frac_str = f"{frac*100:.0f}%" if frac is not None else "—"
        print(f"    {b['range']:<10} {b['n']:>4} {score:>12.3f} {frac_str:>10}  {align}")

    print()

    result = {
        "auc_roc": auc,
        "brier_score": brier,
        "score_distribution_by_band": {
            band: {
                "n": len(s),
                "mean": round(_mean(s), 3),
                "min": round(min(s), 3) if s else None,
                "max": round(max(s), 3) if s else None,
            }
            for band, s in bands.items()
        },
        "calibration_curve": buckets,
        "fraud_legit_separation": round(_mean(bands["high"]) - _mean(bands["low"]), 3)
        if bands["high"] and bands["low"] else None,
    }
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fraud score calibration analysis")
    parser.add_argument("--run", default="eval/runs/latest.json", help="Run manifest path")
    parser.add_argument("--plot", action="store_true", help="Include ASCII bar charts")
    args = parser.parse_args()

    result = calibration_report(Path(args.run), plot=args.plot)

    # Write calibration report alongside the run manifest
    out = Path(args.run).parent / (Path(args.run).stem + "_calibration.json")
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Calibration data written → {out}\n")
