from eval.attribution import attribute
from eval.dataset import get_cases

C = {c.id: c for c in get_cases("all")}


def _ex(case, **over):
    t = case.truth
    e = {"policy_id": t["policy_id"], "claimed_amount": t["claimed_amount"], "incident_date": t["incident_date"]}
    e.update(over)
    return e


def test_correct():
    c = C["auto_01"]
    assert attribute(c, "APPROVED", 0.1, _ex(c))["failure_mode"] == "correct"


def test_amount_error_is_attributed():
    c = C["auto_01"]  # 65k on 300k limit → APPROVED; parsing 6.5L would exceed limit
    r = attribute(c, "REJECTED", 0.1, _ex(c, claimed_amount=650000))
    assert r["failure_mode"] == "extraction_amount"


def test_fraud_overscore():
    c = C["auto_05"]  # documented theft at 98% of limit → ESCALATED / medium
    r = attribute(c, "REJECTED", 0.95, _ex(c))
    assert r["failure_mode"] == "fraud_overscore"


def test_fraud_underscore():
    c = C["fraud_04"]
    r = attribute(c, "ESCALATED", 0.5, _ex(c))
    assert r["failure_mode"] == "fraud_underscore"


def test_decision_logic():
    c = C["edge_02"]  # expired policy, low band
    r = attribute(c, "APPROVED", 0.1, _ex(c))
    assert r["failure_mode"] == "decision_logic"


def test_injection():
    inj = next(c for c in C.values() if "prompt_injection" in c.truth.get("flags", []))
    assert attribute(inj, "APPROVED", 0.0, _ex(inj))["failure_mode"] == "injection_followed"
