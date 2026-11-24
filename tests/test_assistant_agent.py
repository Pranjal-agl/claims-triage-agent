import json

import httpx

from tests.conftest import requires_warehouse
from tests.scripted_client import ScriptedClient

pytestmark = requires_warehouse


def agent(steps, **kw):
    from assistant.agent import Agent
    return Agent(client=ScriptedClient(steps), persist_traces=kw.pop("persist", False), **kw)


def test_hybrid_flow_docs_then_sql():
    a = agent([("tool", "search_docs", {"query": "large loss definition"}),
               ("tool", "run_sql", {"sql": "SELECT count(*) FROM ins.claims WHERE total_claim_amount >= 60000"}),
               ("answer", "There are 461 large-loss claims [kpi_definitions].")])
    r = a.ask("ana", "How many large-loss claims are there?")
    assert r.status == "ok" and r.final_sql["rows"] == [[461]]
    assert "kpi_definitions" in {h["doc_id"] for h in r.retrieved}
    assert {"agent.run", "llm.chat", "tool.search_docs", "retrieval", "tool.run_sql", "sql.guard", "db.query"} \
        <= {s["name"] for s in r.trace["spans"]}


def test_same_sql_different_users_different_answers():
    sql = "SELECT count(*) FROM ins.claims"
    counts = {u: agent([("tool", "run_sql", {"sql": sql}), ("answer", "x")]).ask(u, "claims?").final_sql["rows"][0][0]
              for u in ("alice", "olivia", "ian", "isha")}
    assert counts == {"alice": 1000, "olivia": 352, "ian": 338, "isha": 310}


def test_self_correction_and_permission_denied():
    a = agent([("tool", "run_sql", {"sql": "SELECT count(*) FROM ins.claim"}),
               ("tool", "run_sql", {"sql": "SELECT count(*) FROM ins.claims"}), ("answer", "1000")])
    r = a.ask("alice", "How many claims?")
    assert [q["ok"] for q in r.queries] == [False, True] and r.queries[0]["error_kind"] == "guard"

    seen = {}

    def final(messages):
        seen["tool"] = messages[-1]["content"]
        return ("answer", "That is not available at your access level.")
    r = agent([("tool", "run_sql", {"sql": "SELECT fraud_reported FROM ins.claims LIMIT 3"}), final]).ask("olivia", "fraud?")
    assert r.permission_denied and "PERMISSION DENIED" in seen["tool"]


def test_trace_persisted_and_fail_closed():
    from assistant import db
    from assistant.agent import Agent
    r = agent([("answer", "hello")], persist=True).ask("sam", "hi")
    with db.superuser_conn() as c:
        assert c.execute("SELECT count(*) FROM obs.spans WHERE trace_id = %s", (r.trace_id,)).fetchone()[0] >= 2

    class Boom:
        model = "boom"

        def chat(self, *a):
            raise RuntimeError("api down")
    assert Agent(client=Boom(), persist_traces=False).ask("ana", "q").status == "error"


def test_openai_sdk_path_with_cache(tmp_path):
    """Real OpenAI-SDK request/response path against an in-process mock server."""
    from assistant.agent import Agent
    from assistant.llm import OpenAICompatClient
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        n_tool = sum(m["role"] == "tool" for m in body["messages"])
        if n_tool == 0:
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "run_sql", "arguments": json.dumps({"sql": "SELECT count(*) FROM ins.claims"})}}]}
        else:
            rows = json.loads(body["messages"][-1]["content"])["rows"]
            msg = {"role": "assistant", "content": f"{rows[0][0]} claims."}
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                                         "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 500, "completion_tokens": 10, "total_tokens": 510}})

    def make():
        return OpenAICompatClient(model="m", base_url="http://mock/v1", api_key="k", cache_path=str(tmp_path / "c.db"),
                                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert Agent(client=make(), persist_traces=False).ask("olivia", "claims?").answer == "352 claims."
    assert calls["n"] == 2
    Agent(client=make(), persist_traces=False).ask("olivia", "claims?")
    assert calls["n"] == 2   # served from cache
