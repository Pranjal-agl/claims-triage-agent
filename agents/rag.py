"""
agents/rag.py — "agent_rag": the triage graph with a retrieval step.

    extract → lookup_policy → retrieve_guidelines → assess_fraud → route → decide → report

retrieve_guidelines queries the claims warehouse's document store AS the
least-privilege `cx_triage` role (row-level security limits it to public docs
plus the SIU red-flag guide) and passes the top chunks to the fraud node.
Run it as an ablation:  python -m eval.runner --system agent_rag
If the warehouse is unreachable the node returns no guidance, so the variant
degrades to the plain agent rather than failing.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .graph import route_after_fraud
from .nodes import auto_reject_node, decision_node, extract_node, fraud_node, policy_node, report_node
from .state import ClaimState

K = 3


def retrieve_guidelines_node(state: ClaimState) -> dict:
    ext = state.get("extracted") or {}
    query = f"fraud red flags {ext.get('incident_type', '')} {ext.get('description', '')}"[:500]
    try:
        from assistant import retrieval
        hits = retrieval.search("cx_triage", query, k=K)
        return {"guidelines": [{"chunk_id": h["chunk_id"], "text": h["content"]} for h in hits]}
    except Exception:
        return {"guidelines": []}


def build_rag_graph():
    g = StateGraph(ClaimState)
    g.add_node("extract", extract_node)
    g.add_node("lookup_policy", policy_node)
    g.add_node("retrieve_guidelines", retrieve_guidelines_node)
    g.add_node("assess_fraud", fraud_node)
    g.add_node("auto_reject", auto_reject_node)
    g.add_node("decide", decision_node)
    g.add_node("generate_report", report_node)
    g.set_entry_point("extract")
    g.add_edge("extract", "lookup_policy")
    g.add_edge("lookup_policy", "retrieve_guidelines")
    g.add_edge("retrieve_guidelines", "assess_fraud")
    g.add_conditional_edges("assess_fraud", route_after_fraud, {"auto_reject": "auto_reject", "decide": "decide"})
    g.add_edge("auto_reject", "generate_report")
    g.add_edge("decide", "generate_report")
    g.add_edge("generate_report", END)
    return g.compile()
