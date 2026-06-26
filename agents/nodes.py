import os
from datetime import date as _date
from langchain_groq import ChatGroq
from .state import ClaimState, ExtractedClaim, FraudAssessment, ClaimDecision
from .tools import lookup_policy

_llm = None

_SAFE_DECISION = {
    "decision": "ESCALATED",
    "justification": (
        "Automatic processing failed due to an internal error. "
        "Claim has been escalated for manual human review."
    ),
    "recommended_payout": 0.0,
}

_SAFE_FRAUD = {
    "fraud_score": 0.5,
    "flags": ["processing_error"],
    "reasoning": "Fraud assessment could not be completed; defaulting to medium risk.",
}


def _safe_node(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(state: ClaimState) -> dict:
        try:
            return fn(state)
        except Exception as exc:
            error_msg = f"{fn.__name__} failed: {type(exc).__name__}: {exc}"
            print(f"\n  [SAFE_NODE] {error_msg}\n")
            fallback: dict = {"error": error_msg}
            if fn.__name__ == "extract_node":
                fallback["extracted"] = {
                    "policy_id": "",
                    "claimant_name": "Unknown",
                    "incident_type": "other",
                    "incident_date": "Unknown",
                    "claimed_amount": 0.0,
                    "description": "Extraction failed.",
                }
            elif fn.__name__ == "fraud_node":
                fallback["fraud"] = _SAFE_FRAUD
            elif fn.__name__ in ("decision_node", "auto_reject_node"):
                fallback["decision"] = _SAFE_DECISION
            return fallback

    return wrapper


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0,
            max_retries=3,
        )
    return _llm


@_safe_node
def extract_node(state: ClaimState) -> dict:
    llm = get_llm().with_structured_output(ExtractedClaim)
    result = llm.invoke(
        f"Extract structured insurance claim information from the following text.\n\n"
        f"Claim text:\n{state['claim_text']}\n\n"
        "For incident_type use exactly one of: accident, theft, medical, property_damage, fire, other. "
        "For policy_id, look for any ID, number, or reference code. "
        "For claimed_amount, extract the numeric value in INR as a plain integer or float, "
        "with no currency symbols, commas, or units — e.g. 65000 not 'Rs 65,000'."
    )
    return {"extracted": result.model_dump()}


def policy_node(state: ClaimState) -> dict:
    extracted = state.get("extracted") or {}
    policy_id = extracted.get("policy_id", "")
    policy = lookup_policy(policy_id)
    return {"policy": policy}


@_safe_node
def fraud_node(state: ClaimState) -> dict:
    llm = get_llm().with_structured_output(FraudAssessment)

    extracted = state.get("extracted") or {}
    policy = state.get("policy") or {}
    coverage = policy.get("coverage_limit", 0) if policy.get("found") else 0
    claimed = extracted.get("claimed_amount", 0)
    ratio = claimed / coverage if coverage > 0 else 999

    context = (
        f"Assess fraud risk for this insurance claim. Return fraud_score 0.0-1.0.\n\n"
        f"Claim details: {extracted}\n"
        f"Policy details: {policy}\n"
        f"Claimed/coverage ratio: {ratio:.2f}\n\n"
        f"Score HIGH (>0.75) — story itself is suspicious:\n"
        f"  - No police report/FIR for theft or accident claims\n"
        f"  - Contradictory story (e.g. settled privately then changed mind)\n"
        f"  - No documentation at all (no receipts, no dates, no incident details)\n"
        f"  - Vague or unnamed medical condition with no supporting evidence\n"
        f"  - Claimed amount grossly exceeds plausible market value\n"
        f"  - Multiple incidents without any dates or documentation\n"
        f"  - Fabricated or non-existent policy ID\n\n"
        f"Score MEDIUM (0.4-0.75) — plausible but needs review:\n"
        f"  - Large claim (>80% of limit) with documentation present\n"
        f"  - Some missing details but core story is consistent\n\n"
        f"Score LOW (<0.4) — legitimate claim:\n"
        f"  - FIR/police report filed same day or promptly after incident\n"
        f"  - Receipts, discharge summary, or engineer report present\n"
        f"  - Named hospital, garage, or contractor mentioned\n"
        f"  - Clear incident date and plausible amount for the incident type\n"
        f"  - Car theft with FIR = LOW fraud even if claiming near coverage limit\n\n"
        f"CRITICAL: Large amount alone is NOT fraud. A cardiac surgery at Fortis with "
        f"documents is LOW fraud. A car theft with FIR filed same day is LOW fraud. "
        f"A total-loss collision with a police report is LOW fraud. "
        f"Only score HIGH if the STORY itself is suspicious (no docs, contradictions, vague), "
        f"not just because the amount is large.\n\n"
        f"Be decisive. Do not default to 0.5 or 0.8 without clear reason."
    )
    result = llm.invoke(context)
    return {"fraud": result.model_dump()}


def auto_reject_node(state: ClaimState) -> dict:
    fraud = state.get("fraud") or {}
    return {
        "decision": {
            "decision": "REJECTED",
            "justification": (
                f"Automatically rejected due to high fraud risk score of "
                f"{fraud.get('fraud_score', 1.0):.0%}. "
                f"Flags: {', '.join(fraud.get('flags', [])) or 'none specified'}."
            ),
            "recommended_payout": 0.0,
        }
    }


def _check_policy_expired(extracted: dict, policy: dict) -> bool:
    """
    Compare incident_date against policy end_date in Python.
    More reliable than asking the LLM to compare date strings.
    Returns True if the incident occurred after the policy expired.
    """
    try:
        incident_str = extracted.get("incident_date", "")
        end_str = policy.get("end_date", "")
        if incident_str and end_str and len(incident_str) >= 10 and len(end_str) >= 10:
            incident_dt = _date.fromisoformat(incident_str[:10])
            end_dt = _date.fromisoformat(end_str[:10])
            return incident_dt > end_dt
    except (ValueError, TypeError):
        pass
    return False


@_safe_node
def decision_node(state: ClaimState) -> dict:
    llm = get_llm().with_structured_output(ClaimDecision)

    extracted = state.get("extracted") or {}
    policy = state.get("policy") or {}
    fraud = state.get("fraud") or {}

    coverage = policy.get("coverage_limit", 0) if policy.get("found") else 0
    deductible = policy.get("deductible", 0) if policy.get("found") else 0
    claimed = float(extracted.get("claimed_amount") or 0)
    fraud_score = float(fraud.get("fraud_score") or 0)
    ratio = claimed / coverage if coverage > 0 else 999

    # Deterministic checks in Python — don't leave these to LLM interpretation
    policy_not_found = not policy.get("found", False)
    policy_expired = _check_policy_expired(extracted, policy) if not policy_not_found else False
    exceeds_coverage = claimed > coverage > 0

    # Hard-enforce thresholds deterministically — LLM only writes justification
    if policy_not_found:
        forced_decision = "REJECTED"
        forced_reason = f"Policy not found in database."
    elif policy_expired:
        forced_decision = "REJECTED"
        forced_reason = f"Policy expired before incident date ({extracted.get('incident_date','?')} > {policy.get('end_date','?')})."
    elif exceeds_coverage:
        forced_decision = "REJECTED"
        forced_reason = f"Claimed amount ₹{claimed:,.0f} exceeds coverage limit ₹{coverage:,.0f}."
    elif fraud_score >= 0.4 or ratio > 0.80:
        forced_decision = "ESCALATED"
        reasons = []
        if fraud_score >= 0.4:
            reasons.append(f"fraud_score={fraud_score:.2f} (≥0.40 threshold)")
        if ratio > 0.80:
            reasons.append(f"ratio={ratio:.2f} (>0.80 threshold, claimed {claimed:,.0f} vs limit {coverage:,.0f})")
        forced_reason = "Escalated for human review: " + "; ".join(reasons) + "."
    else:
        forced_decision = "APPROVED"
        forced_reason = None

    # For REJECTED/ESCALATED we can return immediately without an LLM call,
    # saving tokens. For APPROVED, use LLM to compute exact payout and write
    # a natural justification.
    if forced_decision in ("REJECTED", "ESCALATED"):
        payout = 0.0
        if forced_decision == "ESCALATED":
            # Payout estimate for escalated claims (subject to human review)
            payout = max(0.0, claimed - deductible)
        return {"decision": {
            "decision": forced_decision,
            "justification": forced_reason,
            "recommended_payout": payout,
        }}

    # APPROVED path — use LLM for natural language justification only
    context = (
        f"An insurance claim has been pre-approved by the rules engine. "
        f"Write a brief, professional justification and confirm the payout.\n\n"
        f"Claim: {extracted.get('description', '')}\n"
        f"Claimant: {extracted.get('claimant_name', '')}\n"
        f"Claimed: ₹{claimed:,.0f}  |  Deductible: ₹{deductible:,.0f}  "
        f"|  Recommended payout: ₹{max(0, claimed - deductible):,.0f}\n"
        f"Fraud score: {fraud_score:.2f} (low risk)\n\n"
        f"Return decision=APPROVED, recommended_payout={max(0, claimed - deductible):.0f}, "
        f"and a 1-2 sentence justification."
    )
    result = llm.invoke(context)
    return {"decision": result.model_dump()}


def report_node(state: ClaimState) -> dict:
    ext = state.get("extracted") or {}
    pol = state.get("policy") or {}
    fraud = state.get("fraud") or {}
    dec = state.get("decision") or {}

    coverage_line = (
        f"Coverage Limit  : ₹{pol.get('coverage_limit', 0):>12,.0f}\n"
        f"Deductible      : ₹{pol.get('deductible', 0):>12,.0f}\n"
        f"Policy Type     : {pol.get('policy_type', '').title()}\n"
        f"Valid Until     : {pol.get('end_date', 'unknown')}"
    ) if pol.get("found") else "Policy not found in database"

    flags = ", ".join(fraud.get("flags", [])) or "None"
    score = fraud.get("fraud_score", 0)
    risk_label = "HIGH" if score > 0.7 else "MEDIUM" if score > 0.4 else "LOW"

    report = f"""
╔══════════════════════════════════════════════════════════╗
║           INSURANCE CLAIM TRIAGE REPORT                  ║
╚══════════════════════════════════════════════════════════╝

CLAIMANT        : {ext.get('claimant_name', 'Unknown')}
POLICY ID       : {ext.get('policy_id', 'Unknown')}
INCIDENT TYPE   : {ext.get('incident_type', 'Unknown').replace('_', ' ').title()}
INCIDENT DATE   : {ext.get('incident_date', 'Unknown')}
CLAIMED AMOUNT  : ₹{ext.get('claimed_amount', 0):,.0f}

INCIDENT SUMMARY
{ext.get('description', 'No description available')}

POLICY DETAILS
{coverage_line}

FRAUD ASSESSMENT
Risk Level      : {risk_label} ({score:.0%})
Flags           : {flags}
Reasoning       : {fraud.get('reasoning', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DECISION        : {dec.get('decision', 'UNKNOWN')}
PAYOUT          : ₹{dec.get('recommended_payout', 0):,.0f}
JUSTIFICATION   : {dec.get('justification', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""".strip()

    return {"final_report": report}
