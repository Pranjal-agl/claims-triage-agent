"""
eval/rubric.py

The labeling rubric, as code. This is the single definition of "correct" for
the eval set: every generated case is labeled by `fraud_band()` + `decide()`
applied to the case's *latent* facts (true policy, amount, date, red flags),
never to any system's output.

It is also used by eval/error_analysis.py for counterfactual stage
attribution: "if this system's extraction had been right, would its decision
have been right?"

The rubric lives in eval/, not agents/, on purpose — the agent never imports
it. See docs/RUBRIC.md for the prose version and the reasoning behind each rule.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

ESCALATE_RATIO = 0.80          # claimed / coverage strictly above this → escalate
GROSS_EXCESS_RATIO = 3.0       # claimed ≥ 3× coverage → fraud band high
BAND_THRESHOLDS = {"low": 0.40, "high": 0.75}   # score <0.40 low, ≥0.75 high

# Red flags that on their own make the story suspicious → fraud band "high"
STRONG_FLAGS = {
    "no_police_report",         # theft/accident never reported to police
    "contradiction",            # story contradicts itself
    "vague_condition",          # refuses to name the medical condition
    "refuses_docs",             # asks for payout without any documentation
    "multiple_undated",         # several incidents, no dates
    "docs_destroyed_max_claim", # "all docs burned" + very large claim
    "name_mismatch",            # claimant ≠ holder, no relationship stated
    "implausible_for_item",     # amount ≥10× typical value for the item
    "no_details",               # no incident type / date / description at all
    "prompt_injection",         # tries to instruct the triage system
    "unknown_policy",           # policy ID does not exist
}

# Signals that make the claim plausible-but-review-worthy → band "medium"
MEDIUM_FLAGS = {
    "partial_docs",             # documents promised later
    "late_report",              # reported 2–6 weeks after the incident
    "limit_anchoring",          # claimant anchors the amount to their cover
}


def band_from_score(score: float) -> str:
    if score >= BAND_THRESHOLDS["high"]:
        return "high"
    if score >= BAND_THRESHOLDS["low"]:
        return "medium"
    return "low"


def fraud_band(flags: set[str] | list[str], ratio: Optional[float]) -> str:
    """Ground-truth fraud band from latent red flags and claimed/coverage ratio."""
    flags = set(flags)
    if flags & STRONG_FLAGS:
        return "high"
    if ratio is not None and ratio >= GROSS_EXCESS_RATIO:
        return "high"   # e.g. ₹95 lakh claimed on a ₹5 lakh policy
    if flags & MEDIUM_FLAGS:
        return "medium"
    if ratio is not None and ratio > ESCALATE_RATIO:
        return "medium"
    return "low"


def _to_date(s: Optional[str]) -> Optional[date]:
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def decide(
    policy: Optional[dict],
    claimed_amount: Optional[float],
    incident_date: Optional[str],
    band: str,
) -> tuple[str, str]:
    """
    Apply the business rules in order. Returns (decision, rule_that_fired).

    1. policy not found                       → REJECTED
    2. policy status not "active"             → REJECTED
    3. incident date outside [start, end]     → REJECTED   (skipped if no date)
    4. claimed > coverage_limit               → REJECTED
    5. fraud band high                        → REJECTED
    6. fraud band medium OR ratio > 0.80      → ESCALATED
    7. otherwise                              → APPROVED
    """
    if not policy or not policy.get("found", True) or not policy.get("policy_id"):
        return "REJECTED", "policy_not_found"
    if str(policy.get("status", "active")).lower() != "active":
        return "REJECTED", "policy_not_active"

    inc = _to_date(incident_date)
    start, end = _to_date(policy.get("start_date")), _to_date(policy.get("end_date"))
    if inc and start and inc < start:
        return "REJECTED", "before_policy_start"
    if inc and end and inc > end:
        return "REJECTED", "policy_expired"

    limit = float(policy.get("coverage_limit") or 0)
    amt = float(claimed_amount or 0)
    if limit > 0 and amt > limit:
        return "REJECTED", "exceeds_coverage"
    if band == "high":
        return "REJECTED", "fraud_high"
    ratio = amt / limit if limit > 0 else None
    if band == "medium":
        return "ESCALATED", "fraud_medium"
    if ratio is not None and ratio > ESCALATE_RATIO:
        return "ESCALATED", "high_ratio"
    return "APPROVED", "approved"
