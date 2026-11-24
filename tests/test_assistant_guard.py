import pytest

from assistant.sql_guard import GuardError, check

T = {"ins.claims", "ins.policies", "ins.policyholders", "triage.decisions"}


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM ins.claims",
    "SELECT count(*) FROM claims",                                  # resolves via search_path
    "SELECT p.state, count(*) FROM ins.claims c JOIN ins.policies p USING (policy_number) GROUP BY 1",
    "WITH x AS (SELECT * FROM ins.claims) SELECT count(*) FROM x",
    "SELECT decision, count(*) FROM triage.decisions GROUP BY 1",
    "SELECT max(umbrella_limit) FROM ins.policies",
])
def test_allowed(sql):
    check(sql, T)


@pytest.mark.parametrize("sql,reason", [
    ("DELETE FROM ins.claims", "Only read-only"),
    ("SELECT 1; DROP TABLE ins.claims", "Exactly one"),
    ("UPDATE ins.claims SET total_claim_amount = 0", "Only read-only"),
    ("SELECT pg_sleep(10)", "pg_sleep"),
    ("SELECT set_config('role', 'cx_admin', false)", "set_config"),
    ("SELECT current_setting('app.state')", "current_setting"),
    ("SELECT * FROM pg_catalog.pg_authid", "Schema"),
    ("SELECT * FROM app.doc_chunks", "Schema"),
    ("SELECT * FROM obs.traces", "Schema"),
    ("SELECT * FROM ins.insured_vehicles", "not available"),
    ("SELECT * FROM triage.policies", "not available"),
    ("SELECT * INTO x FROM ins.claims", None),
    ("SELECT * FROM ins.claims FOR UPDATE", None),
    ("", "Empty"),
])
def test_blocked(sql, reason):
    with pytest.raises(GuardError, match=reason):
        check(sql, T)


def test_limit_injected_only_when_missing():
    r = check("SELECT * FROM ins.claims", T)
    assert r.limit_added and "LIMIT 200" in r.sql and r.tables == {"ins.claims"}
    assert not check("SELECT * FROM ins.claims LIMIT 5", T).limit_added
