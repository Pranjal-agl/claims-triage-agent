"""Stage 1 → stage 2: triage decisions land in the warehouse and the assistant can query them."""

from agents.decision_log import reason_code
from tests.conftest import requires_warehouse


def test_reason_codes():
    base = {"extracted": {"policy_id": "POL-004", "claimed_amount": 1000, "incident_date": "2025-01-01"},
            "policy": {"found": True, "status": "active", "start_date": "2024-01-01", "end_date": "2027-01-01",
                       "coverage_limit": 300000}}
    mk = lambda dec, score, **kw: {**base, "fraud": {"fraud_score": score}, "decision": {"decision": dec}, **kw}  # noqa: E731
    assert reason_code(mk("REJECTED", 0.9)) == "fraud_high"
    assert reason_code(mk("ESCALATED", 0.5)) == "fraud_medium"
    assert reason_code(mk("ESCALATED", 0.1)) == "high_ratio"
    assert reason_code(mk("APPROVED", 0.1)) == "approved"
    assert reason_code(mk("ESCALATED", 0.5, error="boom")) == "degraded"
    assert reason_code({**mk("REJECTED", 0.1), "policy": {"found": False}}) == "policy_not_found"


@requires_warehouse
def test_api_triage_logs_and_assistant_reads(fake_llm, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as m
    from assistant import db
    from assistant.agent import Agent
    from tests.scripted_client import ScriptedClient
    before = db.run_query("cx_admin", "SELECT count(*) FROM triage.decisions WHERE source = 'api'")["rows"][0][0]
    c = TestClient(m.app)
    r = c.post("/triage", json={"claim_text": "Policy POL-004, claimant Sunita Patel. On 2024-11-10 a truck "
                                              "sideswiped my car. FIR filed (copy attached). Requesting Rs 65,000."})
    assert r.status_code == 200 and r.json()["decision"] == "APPROVED"
    after = db.run_query("cx_admin", "SELECT count(*) FROM triage.decisions WHERE source = 'api'")["rows"][0][0]
    assert after == before + 1

    monkeypatch.setattr(m, "_assistant", Agent(client=ScriptedClient([
        ("tool", "run_sql", {"sql": "SELECT count(*) FROM triage.decisions WHERE source = 'api'"}),
        ("answer", "logged")]), persist_traces=True))
    a = c.post("/assistant/ask", json={"question": "How many API triage decisions?"}, headers={"X-User": "ana"}).json()
    assert a["sql"][0]["row_count"] == 1 and a["status"] == "ok"
    assert c.get(f"/assistant/traces/{a['trace_id']}", headers={"X-User": "ana"}).status_code == 200
    assert c.get(f"/assistant/traces/{a['trace_id']}", headers={"X-User": "olivia"}).status_code == 404
    assert c.post("/assistant/ask", json={"question": "x?x"}, headers={"X-User": "mallory"}).status_code == 401
    with db.superuser_conn() as conn:   # keep the seeded log clean
        conn.execute("DELETE FROM triage.decisions WHERE source = 'api'")


@requires_warehouse
def test_agent_rag_variant_grounds_fraud_prompt(fake_llm):
    from agents.rag import build_rag_graph
    from tests.fake_llm import _Bound
    st = build_rag_graph().invoke({"claim_text": "Policy POL-004. My car was stolen 8 weeks ago, I never filed "
                                                 "a police report. Claiming Rs 1,00,000.", "extracted": None,
                                   "policy": None, "fraud": None, "decision": None, "final_report": None, "error": None})
    assert st["guidelines"] and "COMPANY GUIDANCE" in _Bound.last_prompts["FraudAssessment"]
    assert any(g["chunk_id"].startswith("siu_fraud_guide") for g in st["guidelines"])
