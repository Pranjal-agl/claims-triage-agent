import math

from eval.metrics import auc_roc, macro_f1, mcnemar_exact, paired_bootstrap_diff, wilson_ci


def test_wilson_matches_readme_v1_number():
    assert wilson_ci(24, 25) == (80.5, 99.3)


def test_wilson_narrows_with_n():
    lo1, hi1 = wilson_ci(24, 25)
    lo2, hi2 = wilson_ci(208, 231)
    assert (hi2 - lo2) < (hi1 - lo1) / 2


def test_mcnemar():
    a = [True] * 10 + [False] * 2 + [True] * 50
    b = [False] * 10 + [True] * 2 + [True] * 50
    r = mcnemar_exact(a, b)
    assert (r["a_only"], r["b_only"]) == (10, 2)
    assert math.isclose(r["p_value"], 0.038574, rel_tol=1e-3)
    assert mcnemar_exact([True, False], [True, False])["p_value"] == 1.0


def test_bootstrap_diff_sign():
    a = [True] * 90 + [False] * 10
    b = [True] * 70 + [False] * 30
    r = paired_bootstrap_diff(a, b, n_boot=2000)
    assert r["diff_pp"] == 20.0 and r["ci95_pp"][0] > 0


def test_auc_and_f1():
    assert auc_roc([0.9, 0.8, 0.1, 0.2], [1, 1, 0, 0]) == 1.0
    assert auc_roc([0.5, 0.5], [1, 0]) == 0.5
    assert macro_f1(["APPROVED", "REJECTED", "ESCALATED"], ["APPROVED", "REJECTED", "ESCALATED"]) == 1.0
