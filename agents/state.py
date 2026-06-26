from typing import TypedDict, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator


class ExtractedClaim(BaseModel):
    policy_id: str = Field(description="Policy ID/number mentioned in the claim")
    claimant_name: str = Field(description="Full name of the person filing the claim")
    incident_type: str = Field(description="One of: accident, theft, medical, property_damage, fire, other")
    incident_date: str = Field(description="Date of incident in YYYY-MM-DD format, or best guess")
    claimed_amount: Union[float, int, str] = Field(description="Total amount claimed in INR as a plain number e.g. 65000")
    description: str = Field(description="Brief summary of the incident")

    @field_validator("claimed_amount", mode="before")
    @classmethod
    def coerce_amount(cls, v) -> float:
        if isinstance(v, str):
            return float(v.replace(",", "").replace("₹", "").replace("Rs", "").replace(" ", "").strip())
        return float(v)


class FraudAssessment(BaseModel):
    fraud_score: float = Field(description="Fraud risk score from 0.0 (no risk) to 1.0 (definite fraud)")
    flags: list[str] = Field(description="List of specific red flags identified, empty if none")
    reasoning: str = Field(description="Concise explanation of the fraud assessment")


class ClaimDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "ESCALATED"] = Field(
        description="Must be exactly one of: APPROVED, REJECTED, ESCALATED"
    )
    justification: str = Field(description="Clear explanation of why this decision was made")
    recommended_payout: float = Field(description="Recommended payout in INR, 0 if rejected")

    @field_validator("decision", mode="before")
    @classmethod
    def normalise_decision(cls, v: str) -> str:
        v = str(v).strip().upper()
        mapping = {
            "ESCALATE": "ESCALATED",
            "APPROVE": "APPROVED",
            "REJECT": "REJECTED",
        }
        return mapping.get(v, v)


class ClaimState(TypedDict):
    claim_text: str
    extracted: Optional[dict]
    policy: Optional[dict]
    fraud: Optional[dict]
    decision: Optional[dict]
    final_report: Optional[str]
    error: Optional[str]
