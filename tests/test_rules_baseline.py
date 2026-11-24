import pytest

from agents.tools import normalize_policy_id
from baselines.rules_only import extract_amount, extract_date, triage


@pytest.mark.parametrize("text,amt", [
    ("Requesting Rs 65,000.", 65000), ("claiming total loss of Rs 3,80,000.", 380000),
    ("I am claiming ₹1.2 lakh.", 120000), ("Claiming Rs 1.95 crore", 19500000),
    ("Two quotes: Rs 62,000 and Rs 67,000. Requesting Rs 65,000.", 65000),
    ("claim amt rs 123000", 123000), ("INR 85,000 is what I'm claiming", 85000),
    ("I'd like to claim Rs. 7,67,000/- for this.", 767000),   # regression: "Rs." split the sentence
])
def test_amounts(text, amt):
    assert extract_amount(text) == amt


@pytest.mark.parametrize("text,d", [
    ("On 2024-11-10 a truck", "2024-11-10"), ("It happened on 14 March 2025:", "2025-03-14"),
    ("on the 3rd of June 2024", "2024-06-03"), ("On March 4, 2025, the", "2025-03-04"),
    ("14/03/2025 - my car", "2025-03-14"), ("no date here", None),
])
def test_dates(text, d):
    assert extract_date(text) == d


@pytest.mark.parametrize("raw,norm", [("POL-012", "POL-012"), ("pol012", "POL-012"), ("POL 12", "POL-012"),
                                      ("Policy POL-7", "POL-007"), ("POL-999", "POL-999"), ("", "")])
def test_policy_normalisation(raw, norm):
    assert normalize_policy_id(raw) == norm


def test_rules_triage_shapes():
    st = triage("Policy POL-004, claimant Sunita Patel. On 2024-11-10 a truck sideswiped my car. "
                "FIR filed (copy attached). Requesting Rs 65,000.")
    assert st["decision"]["decision"] == "APPROVED"
    assert st["extracted"]["policy_id"] == "POL-004"
