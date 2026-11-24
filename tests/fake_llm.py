"""
Deterministic stand-in for the chat model so the full LangGraph pipeline, the
single-prompt baseline and the eval harness can be exercised offline in CI.
It is NOT a model of LLM quality — it reuses the rules baseline's heuristics —
so numbers produced with it are meaningless and must never be reported.
"""

import re

from baselines import rules_only


class _Bound:
    last_prompts: dict = {}

    def __init__(self, schema):
        self.schema = schema

    def invoke(self, prompt, config=None):
        name = self.schema.__name__
        _Bound.last_prompts[name] = prompt
        if name == "ExtractedClaim":
            text = prompt.split("Claim text:\n", 1)[1].split("\n\nFor incident_type", 1)[0]
            st = rules_only.triage(text)
            e = st["extracted"]
            return self.schema(policy_id=e["policy_id"] or "UNKNOWN", claimant_name="x",
                               incident_type=e["incident_type"], incident_date=e["incident_date"] or "unknown",
                               claimed_amount=e["claimed_amount"], description=f"<<{text}>>")
        if name == "FraudAssessment":
            m = re.search(r"<<(.*?)>>", prompt, re.S)
            score, flags = rules_only.fraud_score(m.group(1) if m else "", 0.0, True)
            return self.schema(fraud_score=score, flags=flags, reasoning="fake")
        if name == "ClaimDecision":
            m = re.search(r"recommended_payout=(\d+)", prompt)
            return self.schema(decision="APPROVED", justification="fake",
                               recommended_payout=float(m.group(1)) if m else 0.0)
        if name == "SinglePromptOutput":
            text = prompt.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
            st = rules_only.triage(text)
            e = st["extracted"]
            return self.schema(policy_id=e["policy_id"], claimed_amount=e["claimed_amount"],
                               incident_date=e["incident_date"] or "unknown",
                               fraud_score=st["fraud"]["fraud_score"], decision=st["decision"]["decision"],
                               recommended_payout=st["decision"]["recommended_payout"], justification="fake")
        raise NotImplementedError(name)


class FakeLLM:
    def with_structured_output(self, schema):
        return _Bound(schema)
