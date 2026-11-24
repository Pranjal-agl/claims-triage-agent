"""
eval/metrics.py

Pure-Python metrics shared by the runner, the comparison report and tests.
No numpy/scipy dependency so CI stays light.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Iterable

LABELS = ["APPROVED", "ESCALATED", "REJECTED"]


def wilson_ci(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval, returned as percentages (1 decimal)."""
    if total == 0:
        return (0.0, 100.0)
    p = correct / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    spread = (z * (p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5) / denom
    return (round(max(0.0, centre - spread) * 100, 1), round(min(1.0, centre + spread) * 100, 1))


def confusion(y_true: list[str], y_pred: list[str]) -> dict[str, dict[str, int]]:
    cols = LABELS + ["ERROR"]
    m = {t: {p: 0 for p in cols} for t in LABELS}
    for t, p in zip(y_true, y_pred):
        m[t][p if p in cols else "ERROR"] += 1
    return m


def per_class_prf(y_true: list[str], y_pred: list[str]) -> dict[str, dict]:
    out = {}
    for lab in LABELS:
        tp = sum(t == lab and p == lab for t, p in zip(y_true, y_pred))
        fp = sum(t != lab and p == lab for t, p in zip(y_true, y_pred))
        fn = sum(t == lab and p != lab for t, p in zip(y_true, y_pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
                    "support": tp + fn}
    return out


def macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    prf = per_class_prf(y_true, y_pred)
    return round(sum(v["f1"] for v in prf.values()) / len(prf), 3)


def auc_roc(scores: list[float], labels: list[int]) -> float:
    """Mann–Whitney AUC with tie handling. nan if one class is empty."""
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return round(wins / (len(pos) * len(neg)), 4)


def grouped_accuracy(rows: list[dict], key: str) -> dict[str, dict]:
    groups: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key, ""))].append(bool(r["decision_correct"]))
    out = {}
    for g, vals in sorted(groups.items()):
        c, n = sum(vals), len(vals)
        lo, hi = wilson_ci(c, n)
        out[g] = {"correct": c, "total": n, "accuracy_pct": round(100 * c / n, 1), "ci95": [lo, hi]}
    return out


# ── paired comparisons ───────────────────────────────────────────────────────


def mcnemar_exact(a_correct: list[bool], b_correct: list[bool]) -> dict:
    """
    Exact (binomial) McNemar test on paired outcomes. Returns the discordant
    counts and a two-sided p-value. b = cases A got right and B got wrong;
    c = cases B got right and A got wrong.
    """
    b = sum(x and not y for x, y in zip(a_correct, b_correct))
    c = sum(y and not x for x, y in zip(a_correct, b_correct))
    n = b + c
    if n == 0:
        return {"a_only": b, "b_only": c, "p_value": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2**n
    return {"a_only": b, "b_only": c, "p_value": round(min(1.0, 2 * tail), 6)}


def paired_bootstrap_diff(a_correct: list[bool], b_correct: list[bool],
                          n_boot: int = 10_000, seed: int = 0) -> dict:
    """95% percentile CI for accuracy(A) − accuracy(B), resampling cases jointly."""
    rng = random.Random(seed)
    n = len(a_correct)
    if n == 0:
        return {"diff_pp": 0.0, "ci95_pp": [0.0, 0.0]}
    a = [int(x) for x in a_correct]
    b = [int(x) for x in b_correct]
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(a[i] - b[i] for i in idx) / n)
    diffs.sort()
    lo, hi = diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]
    return {"diff_pp": round(100 * (sum(a) - sum(b)) / n, 1),
            "ci95_pp": [round(100 * lo, 1), round(100 * hi, 1)]}


def percentile(values: Iterable[float], p: float) -> float:
    v = sorted(values)
    if not v:
        return 0.0
    k = (len(v) - 1) * p / 100
    f, c = math.floor(k), math.ceil(k)
    return round(v[f] + (v[c] - v[f]) * (k - f), 3)


def counts(rows: list[dict], key: str) -> dict[str, int]:
    return dict(Counter(r.get(key) for r in rows).most_common())
