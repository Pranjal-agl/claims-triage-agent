"""
FastAPI service: stage 1 (claims triage agent) and stage 2 (claims analytics assistant).

Triage
    POST /triage                 decide a free-text claim; the decision is logged to triage.decisions
Assistant (needs the Postgres warehouse: python -m warehouse.load)
    GET  /assistant/me           who am I / what can I see       (header X-User)
    POST /assistant/ask          question → answer, SQL, sources, trace id
    GET  /assistant/traces/{id}  the trace (own traces only; Head of Claims sees all)

    uvicorn api.main:app --reload
    curl -s localhost:8000/triage -H 'content-type: application/json' \
         -d '{"claim_text": "Policy POL-004, Sunita Patel. On 2024-11-10 ... Requesting Rs 65,000."}'
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI(title="Claims Triage Agent + Analytics Assistant", version="3.0")


class TriageRequest(BaseModel):
    claim_text: str = Field(min_length=10, max_length=8000)


class TriageResponse(BaseModel):
    decision: str
    recommended_payout: float
    justification: str
    fraud_score: float | None
    fraud_flags: list[str]
    policy_found: bool
    extracted: dict
    latency_s: float
    degraded: bool = Field(description="True if a node failed and a safe fallback was used")
    report: str


@app.get("/health")
def health() -> dict:
    from agents.tools import DB_PATH
    return {"status": "ok", "policy_db": DB_PATH.exists()}


@app.post("/triage", response_model=TriageResponse)
def triage(req: TriageRequest) -> TriageResponse:
    from agents.graph import claims_graph
    t0 = time.perf_counter()
    try:
        st = claims_graph.invoke({"claim_text": req.claim_text, "extracted": None, "policy": None,
                                  "fraud": None, "decision": None, "final_report": None, "error": None})
    except Exception as exc:  # graph-level failure (node failures are already caught by @_safe_node)
        raise HTTPException(status_code=502, detail=f"triage failed: {exc}") from exc
    dec, fraud = st.get("decision") or {}, st.get("fraud") or {}
    from agents.decision_log import log_decision
    from agents.llm import model_name
    log_decision(st, req.claim_text, source="api", system="agent", model=model_name(),
                 latency_ms=int((time.perf_counter() - t0) * 1000))
    return TriageResponse(
        decision=dec.get("decision", "ESCALATED"),
        recommended_payout=float(dec.get("recommended_payout") or 0),
        justification=dec.get("justification", ""),
        fraud_score=fraud.get("fraud_score"),
        fraud_flags=fraud.get("flags", []),
        policy_found=bool((st.get("policy") or {}).get("found")),
        extracted=st.get("extracted") or {},
        latency_s=round(time.perf_counter() - t0, 3),
        degraded=bool(st.get("error")),
        report=st.get("final_report") or "",
    )


# ── stage 2: claims analytics assistant ─────────────────────────────────────

_assistant = None


def get_assistant():
    global _assistant
    if _assistant is None:
        from assistant.agent import Agent
        _assistant = Agent()
    return _assistant


def current_user(x_user: str = Header(..., description="demo identity: alice | ana | olivia | ian | isha | sam")) -> str:
    from assistant.config import USERS
    if x_user not in USERS:
        raise HTTPException(status_code=401, detail="unknown user")
    return x_user


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class AskResponse(BaseModel):
    answer: str
    status: str
    trace_id: str
    sql: list[dict]
    sources: list[dict]


@app.get("/assistant/me")
def assistant_me(user: str = Depends(current_user)) -> dict:
    from assistant.config import USERS
    u = USERS[user]
    return {"user": u.username, "display": u.display, "db_role": u.db_role, "access": u.description}


@app.post("/assistant/ask", response_model=AskResponse)
def assistant_ask(req: AskRequest, user: str = Depends(current_user)) -> AskResponse:
    r = get_assistant().ask(user, req.question, tags={"source": "api"})
    return AskResponse(
        answer=r.answer, status=r.status, trace_id=r.trace_id,
        sql=[{"sql": q.get("executed_sql") or q["sql"], "ok": q.get("ok", False), "error": q.get("error"),
              "row_count": q.get("row_count")} for q in r.queries],
        sources=[{"doc_id": d, "chunks": sorted({h["chunk_id"] for h in r.retrieved if h["doc_id"] == d})}
                 for d in sorted({h["doc_id"] for h in r.retrieved})],
    )


@app.get("/assistant/traces/{trace_id}")
def assistant_trace(trace_id: str, user: str = Depends(current_user)) -> dict:
    import psycopg

    from assistant import config
    with psycopg.connect(config.dsn("cx_obs")) as c:
        t = c.execute("SELECT app_user, question, answer, status, duration_ms, llm_calls, tool_calls, tokens_in, "
                      "tokens_out FROM obs.traces WHERE trace_id = %s", (trace_id,)).fetchone()
        if not t or (t[0] != user and config.USERS[user].db_role != "cx_admin"):
            raise HTTPException(status_code=404, detail="trace not found")
        spans = c.execute("SELECT span_id, parent_id, name, duration_ms, status, attrs FROM obs.spans "
                          "WHERE trace_id = %s ORDER BY started_at", (trace_id,)).fetchall()
    keys = ["app_user", "question", "answer", "status", "duration_ms", "llm_calls", "tool_calls", "tokens_in", "tokens_out"]
    return {**dict(zip(keys, t)), "spans": [
        {"span_id": str(s[0]), "parent_id": str(s[1]) if s[1] else None, "name": s[2], "duration_ms": s[3],
         "status": s[4], "attrs": s[5]} for s in spans]}
