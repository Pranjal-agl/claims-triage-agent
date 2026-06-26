from langgraph.graph import StateGraph, END
from .state import ClaimState
from .nodes import (
    extract_node,
    policy_node,
    fraud_node,
    auto_reject_node,
    decision_node,
    report_node,
)


def route_after_fraud(state: ClaimState) -> str:
    """
    Conditional routing after fraud assessment.

    Documentation-aware cap: if claim text has strong POSITIVE evidence of
    legitimate documentation, cap effective routing score at 0.74 for scores
    in the ambiguous 0.75–0.84 range. This prevents auto-rejecting large
    legitimate claims (e.g. cardiac surgery at Fortis, car total-loss with FIR).

    The cap does NOT apply if:
    - fraud_score >= 0.85 (clear fraud always auto-rejects)
    - Documentation signals appear in a negative context ("no FIR", "no receipts")
    """
    fraud = state.get("fraud") or {}
    score = fraud.get("fraud_score", 0.0)

    # Positive documentation patterns — must appear affirmatively
    positive_signals = [
        "fir filed", "fir lodged", "police report attached", "police report filed",
        "discharge summary", "hospital bill", "invoice attached", "invoice enclosed",
        "receipt", "workshop quote", "engineer report", "fire brigade report",
        "all documents", "documents ready", "documents attached", "documents enclosed",
        "apollo", "fortis", "aiims", "max hospital",
        "garage", "plumber", "contractor",
    ]
    # Negative context phrases that indicate ABSENCE of documentation
    negative_signals = [
        "no fir", "no police", "no receipt", "no document", "no invoice",
        "didn't file", "did not file", "never filed", "no report",
        "no records", "without documents",
    ]

    claim_text = state.get("claim_text", "").lower()
    has_positive_docs = any(sig in claim_text for sig in positive_signals)
    has_negative_context = any(sig in claim_text for sig in negative_signals)

    has_documentation = has_positive_docs and not has_negative_context

    # Only cap in ambiguous zone (0.75–0.84) with genuine documentation
    if has_documentation and score < 0.85:
        effective_score = min(score, 0.74)
    else:
        effective_score = score

    return "auto_reject" if effective_score > 0.75 else "decide"


def build_graph() -> StateGraph:
    g = StateGraph(ClaimState)

    g.add_node("extract", extract_node)
    g.add_node("lookup_policy", policy_node)
    g.add_node("assess_fraud", fraud_node)
    g.add_node("auto_reject", auto_reject_node)
    g.add_node("decide", decision_node)
    g.add_node("generate_report", report_node)

    g.set_entry_point("extract")
    g.add_edge("extract", "lookup_policy")
    g.add_edge("lookup_policy", "assess_fraud")
    g.add_conditional_edges(
        "assess_fraud",
        route_after_fraud,
        {"auto_reject": "auto_reject", "decide": "decide"},
    )
    g.add_edge("auto_reject", "generate_report")
    g.add_edge("decide", "generate_report")
    g.add_edge("generate_report", END)

    return g.compile()


claims_graph = build_graph()
