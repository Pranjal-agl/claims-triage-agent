from eval.rubric import band_from_score, decide, fraud_band
from scripts.policies import by_id

P = {k: dict(v, found=True) for k, v in by_id().items()}


def test_rule_order_and_boundaries():
    p = P["POL-004"]  # limit 300k, 2024-01-01 .. 2027-01-01, active
    assert decide(None, 1000, "2025-01-01", "low")[1] == "policy_not_found"
    assert decide(P["POL-013"], 1000, "2025-01-01", "low")[1] == "policy_not_active"
    assert decide(p, 1000, "2023-12-31", "low")[1] == "before_policy_start"
    assert decide(p, 1000, "2027-01-01", "low")[0] == "APPROVED"          # end date inclusive
    assert decide(p, 1000, "2027-01-02", "low")[1] == "policy_expired"
    assert decide(p, 300001, "2025-01-01", "low")[1] == "exceeds_coverage"
    assert decide(p, 240000, "2025-01-01", "low")[0] == "APPROVED"         # exactly 80% is not > 80%
    assert decide(p, 241000, "2025-01-01", "low")[0] == "ESCALATED"
    assert decide(p, 300000, "2025-01-01", "low")[0] == "ESCALATED"        # exactly at limit
    assert decide(p, 1000, "2025-01-01", "high")[0] == "REJECTED"
    assert decide(p, 1000, None, "medium")[0] == "ESCALATED"               # no date → date rule skipped


def test_fraud_band():
    assert fraud_band([], 0.5) == "low"
    assert fraud_band([], 0.81) == "medium"
    assert fraud_band(["partial_docs"], 0.1) == "medium"
    assert fraud_band(["contradiction", "partial_docs"], 0.1) == "high"
    assert fraud_band([], 3.0) == "high"
    assert band_from_score(0.39) == "low" and band_from_score(0.4) == "medium" and band_from_score(0.75) == "high"
