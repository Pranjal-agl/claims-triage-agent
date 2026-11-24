"""
eval/dataset.py

Labeled held-out eval set for the claims triage agent.

v1  (25 cases, hand-written)  — the original set: auto / health / property /
    fraud / edge, 5 each. Texts are unchanged. Three labels were corrected to
    match the written rubric (see V1_RELABELS and docs/LABEL_AUDIT.md), and every
    case now carries `truth` (the real policy ID, amount and date) so the error
    analysis can attribute failures to a pipeline stage.

v2  (206 cases, generated)     — eval/data/claims_v2.jsonl, produced by
    eval/generate_cases.py from latent facts and labeled by eval/rubric.py.
    13 scenario slices × 3 phrasing tiers (canonical / paraphrase / noisy).

Selectors:
    get_cases("all")  → v1 + v2   (default for all reports; n=231)
    get_cases("v1")   → the original 25
    get_cases("v2")   → the generated 206

Labels follow docs/RUBRIC.md (code: eval/rubric.py):
  - REJECT if policy not found, not active, or incident outside its window
  - REJECT if claimed > coverage_limit
  - REJECT if fraud band is high
  - ESCALATE if fraud band is medium OR claimed > 80% of coverage
  - APPROVE otherwise (payout = claimed − deductible)

Do NOT add these cases to few-shot prompts or the system prompt — they are the
test set. eval/integrity.py checks for leakage into agents/ and baselines/.
"""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Optional

DecisionLabel = Literal["APPROVED", "REJECTED", "ESCALATED"]
FraudBand = Literal["low", "medium", "high"]

V2_PATH = Path(__file__).parent / "data" / "claims_v2.jsonl"


@dataclass
class EvalCase:
    id: str
    claim_text: str
    expected_decision: DecisionLabel
    expected_fraud_band: FraudBand
    slice: str
    notes: str = ""
    line: str = ""                 # auto | health | property
    tier: str = "canonical"        # canonical | paraphrase | noisy
    source: str = "v1_handwritten" # v1_handwritten | v2_generated
    truth: dict = field(default_factory=dict)


_V1_ORIGINAL: list[EvalCase] = [
    # ── AUTO (5) ────────────────────────────────────────────────────────────
    EvalCase(
        id="auto_01",
        claim_text=(
            "Policy POL-004, claimant Sunita Patel. On 2024-11-10 a truck sideswiped my "
            "Honda City on the expressway. Two workshop quotes: Rs 62,000 and Rs 67,000. "
            "FIR filed (copy attached). Requesting Rs 65,000."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="auto",
        notes="Plausible auto claim well within POL-004 limit (300k). Should approve.",
    ),
    EvalCase(
        id="auto_02",
        claim_text=(
            "I am Rahul Gupta, POL-007. My car was totalled in a head-on collision on "
            "2025-01-20 on NH-48. Police report attached. Repair cost exceeds car value; "
            "claiming total loss of Rs 3,80,000."
        ),
        expected_decision="ESCALATED",
        expected_fraud_band="low",
        slice="auto",
        notes="Rs 3.8L > 80% of POL-007 limit (400k). Escalate. "
              "Police report attached — well documented, low fraud band.",
    ),
    EvalCase(
        id="auto_03",
        claim_text=(
            "POL-001 holder Ramesh Kumar. Minor scrape in parking lot on 2024-12-01. "
            "No other vehicle involved. Scratch on driver door, estimate Rs 8,500. "
            "No FIR needed for this."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="auto",
        notes="Very small, plausible claim. Low fraud, approve.",
    ),
    EvalCase(
        id="auto_04",
        claim_text=(
            "Policy POL-007, Rahul Gupta. Engine seized on 2025-02-14 due to water "
            "ingestion during heavy rain. Garage says full engine replacement needed, "
            "Rs 2,20,000. Monsoon was severe that week."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="auto",
        notes="Rs 2.2L within POL-007 limit (400k), plausible weather event.",
    ),
    EvalCase(
        id="auto_05",
        claim_text=(
            "My name is Ramesh Kumar. Policy POL-001. Car stolen from my office parking "
            "on 2024-10-05. FIR lodged the same day (copy enclosed). Claiming current "
            "market value of vehicle Rs 4,90,000."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="auto",
        notes="Rs 4.9L is 98% of POL-001 limit (500k). FIR present but claiming near-full "
              "market value triggers high fraud score consistently (0.90-0.98). "
              "Model auto-rejects — accepted as correct behaviour for near-limit claims "
              "without independent valuation. Known calibration case: documented in README.",
    ),

    # ── HEALTH (5) ──────────────────────────────────────────────────────────
    EvalCase(
        id="health_01",
        claim_text=(
            "Vikram Singh, POL-005. Hospitalised for dengue fever 2024-09-12 to "
            "2024-09-18 at a government hospital. Bills total Rs 42,000 (room, tests, "
            "medicines). Discharge summary attached."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="health",
        notes="Small, clear health claim vs 750k limit on POL-005.",
    ),
    EvalCase(
        id="health_02",
        claim_text=(
            "This is Meera Joshi, policy POL-008. Emergency cardiac stent procedure on "
            "2025-03-10 at Fortis Hospital. Angioplasty + 2 stents + 4-day stay. "
            "Total bill Rs 4,75,000. All documents ready."
        ),
        expected_decision="ESCALATED",
        expected_fraud_band="low",
        slice="health",
        notes="Rs 4.75L > 80% of POL-008 limit (500k). Escalate. "
              "Well-documented at named hospital — low fraud band.",
    ),
    EvalCase(
        id="health_03",
        claim_text=(
            "Vikram Singh here, POL-005. Routine knee arthroscopy 2024-11-22 at "
            "Apollo Hyderabad. Day surgery, discharged same day. Total Rs 95,000 "
            "including surgery, anaesthesia, implant."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="health",
        notes="Standard planned surgery, clear documentation, well within limit.",
    ),
    EvalCase(
        id="health_04",
        claim_text=(
            "Meera Joshi, policy POL-008. I had a very serious illness. The hospital "
            "bills are around Rs 6,00,000 but I don't have the exact receipts right now. "
            "The doctors said it was very dangerous. Please process quickly."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="health",
        notes="No receipts, vague illness, amount exceeds POL-008 limit (500k). High fraud → auto-reject.",
    ),
    EvalCase(
        id="health_05",
        claim_text=(
            "POL-005, Vikram Singh. Diagnosed with Type 2 diabetes 2024-06-01. "
            "Claiming Rs 1,20,000 for 6 months of insulin, testing kits, and "
            "dietitian consultations."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="health",
        notes="Chronic disease management, itemised costs, plausible amount.",
    ),

    # ── PROPERTY (5) ────────────────────────────────────────────────────────
    EvalCase(
        id="prop_01",
        claim_text=(
            "Deepa Nair, POL-006. Electrical short circuit on 2024-08-20 caused "
            "kitchen fire. Damage to cabinets, appliances, ceiling. Contractor estimate "
            "Rs 3,40,000. Fire brigade report attached."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="property",
        notes="Clear fire claim, documented, well within POL-006 limit (5M).",
    ),
    EvalCase(
        id="prop_02",
        claim_text=(
            "Anil Verma, POL-003. Landslide from adjacent hill on 2024-07-18 damaged "
            "rear retaining wall and half the ground floor. Structural engineer report "
            "says full demolition and rebuild required. Estimate Rs 18,00,000."
        ),
        expected_decision="ESCALATED",
        expected_fraud_band="medium",
        slice="property",
        notes="Rs 18L > 80% of POL-003 limit (2M). Escalate. High ratio = medium fraud band.",
    ),
    EvalCase(
        id="prop_03",
        claim_text=(
            "Policy POL-006, Deepa Nair. Burst pipe on 2024-12-03 flooded bathroom "
            "and bedroom. Plumber + flooring + repainting: Rs 85,000 total. "
            "Plumber invoice attached."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="property",
        notes="Small, well-documented property claim.",
    ),
    EvalCase(
        id="prop_04",
        claim_text=(
            "Anil Verma, POL-003. My entire property was destroyed in an earthquake "
            "on 2025-01-15. I am claiming the full value of the property which is "
            "Rs 1,95,00,000. I need immediate settlement."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="property",
        notes="Rs 1.95 crore far exceeds POL-003 limit (2M = Rs 20L). Should be caught as fraud/reject.",
    ),
    EvalCase(
        id="prop_05",
        claim_text=(
            "Deepa Nair, POL-006. Theft of electronics from home on 2024-09-07. "
            "TV, laptop, camera stolen. Filed FIR same day. Total claimed: Rs 2,10,000. "
            "Purchase receipts available for all items."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="property",
        notes="Theft with FIR and receipts, reasonable amount.",
    ),

    # ── FRAUD (5) ───────────────────────────────────────────────────────────
    EvalCase(
        id="fraud_01",
        claim_text=(
            "Hello, policy POL-001. My car was stolen I think 2 months ago. "
            "I never filed a police report because I assumed it would come back. "
            "It is a brand new Mercedes worth Rs 95,00,000. Please pay immediately."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="fraud",
        notes="Classic fraud: 2-month delay, no FIR, absurd amount vs coverage.",
    ),
    EvalCase(
        id="fraud_02",
        claim_text=(
            "I am John Smith, policy POL-003. My house burnt down completely last "
            "night. I don't have any documents because they all burned. The house was "
            "worth Rs 2,00,00,000. I need Rs 2,00,00,000 urgently today."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="fraud",
        notes="No documents, name doesn't match policy holder, grossly inflated amount.",
    ),
    EvalCase(
        id="fraud_03",
        claim_text=(
            "Policy POL-005 here. I was in hospital for 30 days for a 'secret medical "
            "condition' I cannot name. The bill is exactly Rs 7,50,000 (the full "
            "coverage limit). Please process without asking for documents."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="fraud",
        notes="Claiming exactly coverage limit, refusing to name condition or provide documents.",
    ),
    EvalCase(
        id="fraud_04",
        claim_text=(
            "Ramesh Kumar, POL-001. My car had an accident on 2024-10-10. The other "
            "driver was at fault. I am claiming Rs 5,00,000 for vehicle damage. "
            "No FIR was filed because we settled privately but then I changed my mind."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="fraud",
        notes="Claiming full policy limit, no FIR, contradictory story about settlement.",
    ),
    EvalCase(
        id="fraud_05",
        claim_text=(
            "This is an urgent claim. Policy POL-004. On some date in the last few "
            "months my car was in several accidents. Total damage is exactly "
            "Rs 3,00,000 (the full policy limit). I have no receipts or dates."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="fraud",
        notes="Vague dates, multiple incidents, exactly at limit, no documentation.",
    ),

    # ── EDGE (5) ─────────────────────────────────────────────────────────────
    EvalCase(
        id="edge_01",
        claim_text=(
            "Priya Sharma here, policy POL-002. I had a health emergency — appendix "
            "operation on 2024-08-10. Hospital bill is Rs 1,20,000. All documents "
            "ready. Please process my claim."
        ),
        expected_decision="APPROVED",
        expected_fraud_band="low",
        slice="edge",
        notes="POL-002 valid (expires 2025-03-15, incident 2024-08-10 is within window). "
              "Rs 1.2L well within 1M limit. Should APPROVE.",
    ),
    EvalCase(
        id="edge_02",
        claim_text=(
            "Priya Sharma, POL-002. I need to claim Rs 80,000 for a hospital stay "
            "on 2025-09-15 for knee replacement surgery."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="low",
        slice="edge",
        notes="POL-002 expired 2025-03-15. Incident 2025-09-15 is after expiry. Reject. "
              "Low fraud — claim is plausible, just post-expiry.",
    ),
    EvalCase(
        id="edge_03",
        claim_text=(
            "My policy number is POL-999. I had a car accident on 2024-11-01 and "
            "I am claiming Rs 50,000 for repairs. Documents attached."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="edge",
        notes="POL-999 does not exist in DB. Policy not found → reject. High fraud — fabricated policy ID.",
    ),
    EvalCase(
        id="edge_04",
        claim_text=(
            "Sunita Patel, POL-004. Car accident on 2024-12-20. Repair estimate "
            "is exactly Rs 2,40,000 — the full coverage limit minus deductible. "
            "Two quotes obtained. FIR filed."
        ),
        expected_decision="ESCALATED",
        expected_fraud_band="medium",
        slice="edge",
        notes="Amount exactly at 80% threshold of 300k limit (240k = 80%). Boundary condition.",
    ),
    EvalCase(
        id="edge_05",
        claim_text=(
            "Policy POL-001. An incident happened. I am claiming Rs 1,00,000. "
            "Please process."
        ),
        expected_decision="REJECTED",
        expected_fraud_band="high",
        slice="edge",
        notes="Minimal information: no name, no date, no incident type. "
              "High fraud — complete lack of detail. Auto-reject is correct.",
    ),
]


# ── v1 latent facts (for stage-level error attribution) ─────────────────────
# (policy_id, claimed_amount, incident_date, incident_type, flags)
_V1_TRUTH = {
    "auto_01":   ("POL-004",    65000, "2024-11-10", "accident", []),
    "auto_02":   ("POL-007",   380000, "2025-01-20", "accident", []),
    "auto_03":   ("POL-001",     8500, "2024-12-01", "accident", []),
    "auto_04":   ("POL-007",   220000, "2025-02-14", "other",    []),
    "auto_05":   ("POL-001",   490000, "2024-10-05", "theft",    []),
    "health_01": ("POL-005",    42000, "2024-09-12", "medical",  []),
    "health_02": ("POL-008",   475000, "2025-03-10", "medical",  []),
    "health_03": ("POL-005",    95000, "2024-11-22", "medical",  []),
    "health_04": ("POL-008",   600000, None,         "medical",  ["vague_condition"]),
    "health_05": ("POL-005",   120000, "2024-06-01", "medical",  []),
    "prop_01":   ("POL-006",   340000, "2024-08-20", "fire",     []),
    "prop_02":   ("POL-003",  1800000, "2024-07-18", "property_damage", []),
    "prop_03":   ("POL-006",    85000, "2024-12-03", "property_damage", []),
    "prop_04":   ("POL-003", 19500000, "2025-01-15", "property_damage", []),
    "prop_05":   ("POL-006",   210000, "2024-09-07", "theft",    []),
    "fraud_01":  ("POL-001",  9500000, None,         "theft",    ["no_police_report"]),
    "fraud_02":  ("POL-003", 20000000, None,         "fire",     ["name_mismatch", "docs_destroyed_max_claim"]),
    "fraud_03":  ("POL-005",   750000, None,         "medical",  ["vague_condition", "refuses_docs", "limit_anchoring"]),
    "fraud_04":  ("POL-001",   500000, "2024-10-10", "accident", ["contradiction"]),
    "fraud_05":  ("POL-004",   300000, None,         "accident", ["multiple_undated", "limit_anchoring"]),
    "edge_01":   ("POL-002",   120000, "2024-08-10", "medical",  []),
    "edge_02":   ("POL-002",    80000, "2025-09-15", "medical",  []),
    "edge_03":   ("POL-999",    50000, "2024-11-01", "accident", ["unknown_policy"]),
    "edge_04":   ("POL-004",   240000, "2024-12-20", "accident", ["limit_anchoring"]),
    "edge_05":   ("POL-001",   100000, None,         "other",    ["no_details"]),
}

# ── v1 label corrections (audit trail; see docs/LABEL_AUDIT.md) ──────────────
# id → (new_decision, new_band, reason)
V1_RELABELS = {
    "auto_05": ("ESCALATED", "medium",
                "Was REJECTED/high to match observed model output (the case notes said so). "
                "Under the rubric a documented theft (same-day FIR) at 98% of limit is "
                "ESCALATED with a medium band. The model's high score is a failure, not the label."),
    "auto_02": ("ESCALATED", "medium",
                "Band was 'low'; rubric (and the agent's own fraud prompt) say a documented claim "
                ">80% of limit is medium. Decision unchanged."),
    "health_02": ("ESCALATED", "medium",
                  "Band was 'low'; same >80%-of-limit rule as auto_02. Decision unchanged."),
}


def _build_v1() -> list[EvalCase]:
    out = []
    for c in _V1_ORIGINAL:
        pid, amt, d, itype, flags = _V1_TRUTH[c.id]
        line = {"auto": "auto", "health": "health", "prop": "property"}.get(c.id.split("_")[0], "")
        if not line:
            line = {"POL-001": "auto", "POL-004": "auto", "POL-003": "property",
                    "POL-005": "health", "POL-002": "health"}.get(pid, "auto")
        truth = {"policy_id": pid, "claimed_amount": float(amt), "incident_date": d,
                 "incident_type": itype, "flags": flags}
        c = replace(c, line=line, truth=truth)
        if c.id in V1_RELABELS:
            dec, band, why = V1_RELABELS[c.id]
            c = replace(c, expected_decision=dec, expected_fraud_band=band,
                        notes=f"[RELABELED v2] {why} | original note: {c.notes}")
        out.append(c)
    return out


def _load_v2() -> list[EvalCase]:
    if not V2_PATH.exists():
        return []
    cases = []
    for line in V2_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            cases.append(EvalCase(**d))
    return cases


V1_CASES: list[EvalCase] = _build_v1()
V2_CASES: list[EvalCase] = _load_v2()
EVAL_DATASET: list[EvalCase] = V1_CASES + V2_CASES


def get_cases(split: str = "all", slice_: Optional[str] = None, tier: Optional[str] = None,
              case_id: Optional[str] = None) -> list[EvalCase]:
    pool = {"all": EVAL_DATASET, "v1": V1_CASES, "v2": V2_CASES}[split]
    if case_id:
        pool = [c for c in pool if c.id == case_id]
    if slice_:
        pool = [c for c in pool if c.slice == slice_]
    if tier:
        pool = [c for c in pool if c.tier == tier]
    return pool


# Sanity check — IDs must be unique
assert len({c.id for c in EVAL_DATASET}) == len(EVAL_DATASET), "Duplicate eval IDs"
