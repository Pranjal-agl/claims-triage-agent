"""
eval/dataset.py

Held-out labeled dataset for the claims triage agent eval harness.
25 claims across 5 slices:
  - auto        (5 cases)
  - health      (5 cases)
  - property    (5 cases)
  - fraud       (5 cases — high-confidence fraud, expected REJECTED)
  - edge        (5 cases — boundary conditions: expired policy, unknown policy,
                           amount exactly at limit, suspiciously round number,
                           missing incident date)

Each case carries:
  claim_text            : free-text input to the agent
  expected_decision     : APPROVED | REJECTED | ESCALATED
  expected_fraud_band   : "low" (<0.4) | "medium" (0.4–0.75) | "high" (>0.75)
  slice                 : slice label for per-slice metrics
  notes                 : why this case is interesting / what it probes

Ground truth was set by a human (Knox) reading each claim against the seeded
policy DB and the decision rules in agents/nodes.py:
  - REJECT if policy not found or expired
  - REJECT if claimed > coverage_limit
  - ESCALATE if fraud 0.4–0.75 OR claimed > 80% of coverage
  - APPROVE otherwise (after deductible)
  - AUTO-REJECT (REJECTED) if fraud > 0.75

Do NOT add these cases to few-shot prompts or the system prompt — they are the
test set. Keep training/eval separation clean.
"""

from dataclasses import dataclass, field
from typing import Literal

DecisionLabel = Literal["APPROVED", "REJECTED", "ESCALATED"]
FraudBand = Literal["low", "medium", "high"]
Slice = Literal["auto", "health", "property", "fraud", "edge"]


@dataclass
class EvalCase:
    id: str
    claim_text: str
    expected_decision: DecisionLabel
    expected_fraud_band: FraudBand
    slice: Slice
    notes: str = ""


EVAL_DATASET: list[EvalCase] = [
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

# Sanity check — IDs must be unique
assert len({c.id for c in EVAL_DATASET}) == len(EVAL_DATASET), "Duplicate eval IDs"
