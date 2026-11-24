"""
eval/systems.py

Registry of triage systems that the eval runner can score on the same cases.
Every system takes claim text and returns the same shape:

    {
      "state":          final state dict (extracted / policy / fraud / decision),
      "node_latencies": {node: seconds},
      "token_usage":    {"tokens_in", "tokens_out", "tokens_total"},
      "llm_calls":      int,
    }

Systems
───────
agent                 full LangGraph pipeline (agents/graph.py)
rules                 rules-only baseline, no LLM (baselines/rules_only.py)
single_prompt         one LLM call with rules + policy table (baselines/single_prompt.py)
agent_no_fraud        ablation: fraud node bypassed (score = 0)
agent_no_policy       ablation: policy lookup always "not found"
agent_simple_prompt   ablation: decision node replaced by a minimal LLM prompt
agent_rag             variant: fraud node grounded in the SIU guide retrieved from the warehouse
"""

from __future__ import annotations

import time
from typing import Any, Callable

SYSTEM_DESCRIPTIONS = {
    "agent": "LangGraph agent: extract → policy DB → fraud LLM → router → rules + LLM justification",
    "rules": "Rules-only baseline: regex extraction + keyword fraud heuristics, 0 LLM calls",
    "single_prompt": "Single-prompt LLM baseline: 1 call with full rules + policy table, no tools",
    "agent_no_fraud": "Ablation: fraud node bypassed (score=0)",
    "agent_no_policy": "Ablation: policy lookup always returns 'not found'",
    "agent_simple_prompt": "Ablation: decision node uses a minimal unstructured prompt",
    "agent_rag": "Variant: + retrieval of company fraud guidance (pgvector/FTS) before fraud scoring",
}
LLM_SYSTEMS = {"agent", "single_prompt", "agent_no_fraud", "agent_no_policy", "agent_simple_prompt", "agent_rag"}


def _initial(claim_text: str) -> dict[str, Any]:
    return {"claim_text": claim_text, "extracted": None, "policy": None, "fraud": None,
            "decision": None, "final_report": None, "error": None}


def _usage(handler) -> dict[str, int]:
    tin = tout = 0
    meta = getattr(handler, "usage_metadata", None) or {}
    for v in (meta.values() if isinstance(meta, dict) else []):
        tin += int(v.get("input_tokens", 0) or 0)
        tout += int(v.get("output_tokens", 0) or 0)
    return {"tokens_in": tin, "tokens_out": tout, "tokens_total": tin + tout}


def _graph_runner(build: Callable[[], Any]) -> Callable[[str], dict]:
    graph_holder: dict[str, Any] = {}

    def run(claim_text: str) -> dict:
        from langchain_core.callbacks import UsageMetadataCallbackHandler
        if "g" not in graph_holder:
            graph_holder["g"] = build()
        handler = UsageMetadataCallbackHandler()
        acc: dict[str, Any] = {}
        lat: dict[str, float] = {}
        t_prev = time.perf_counter()
        for chunk in graph_holder["g"].stream(_initial(claim_text), stream_mode="updates",
                                               config={"callbacks": [handler]}):
            now = time.perf_counter()
            node = list(chunk.keys())[0]
            lat[node] = round(now - t_prev, 3)
            acc.update(chunk[node] or {})
            t_prev = now
        usage = _usage(handler)
        return {"state": acc, "node_latencies": lat, "token_usage": usage, "llm_calls": None}

    return run


def _agent_graph():
    from agents.graph import claims_graph
    return claims_graph


def _ablation(name: str):
    def build():
        from eval import ablations
        return ablations.VARIANT_BUILDERS[name]()
    return build


def _rag_graph():
    from agents.rag import build_rag_graph
    return build_rag_graph()


def _rules(claim_text: str) -> dict:
    from baselines.rules_only import triage
    t0 = time.perf_counter()
    state = triage(claim_text)
    lat = state.pop("_node_latencies", {})
    lat["__total__"] = round(time.perf_counter() - t0, 5)
    return {"state": state, "node_latencies": lat,
            "token_usage": {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0}, "llm_calls": 0}


def _single_prompt(claim_text: str) -> dict:
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    from baselines.single_prompt import triage
    handler = UsageMetadataCallbackHandler()
    t0 = time.perf_counter()
    state = triage(claim_text, callbacks=[handler])
    return {"state": state, "node_latencies": {"single_call": round(time.perf_counter() - t0, 3)},
            "token_usage": _usage(handler), "llm_calls": 1}


SYSTEMS: dict[str, Callable[[str], dict]] = {
    "agent": _graph_runner(_agent_graph),
    "rules": _rules,
    "single_prompt": _single_prompt,
    "agent_no_fraud": _graph_runner(_ablation("no_fraud")),
    "agent_no_policy": _graph_runner(_ablation("no_policy")),
    "agent_simple_prompt": _graph_runner(_ablation("simple_prompt")),
    "agent_rag": _graph_runner(_rag_graph),
}


def run_system(name: str, claim_text: str) -> dict:
    return SYSTEMS[name](claim_text)
