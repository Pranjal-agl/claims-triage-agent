import pytest

from tests.conftest import requires_warehouse

pytestmark = requires_warehouse


def q(role, sql):
    from assistant import db
    return db.run_query(role, sql)["rows"]


def test_row_level_security_scopes_adjusters_by_policy_state():
    assert q("cx_admin", "SELECT count(*) FROM ins.claims") == [[1000]]
    per_state = {r: q(r, "SELECT count(*) FROM ins.claims")[0][0] for r in ("cx_adjuster_oh", "cx_adjuster_il", "cx_adjuster_in")}
    assert per_state == {"cx_adjuster_oh": 352, "cx_adjuster_il": 338, "cx_adjuster_in": 310}
    assert q("cx_adjuster_oh", "SELECT count(*) FROM ins.policies WHERE state <> 'OH'") == [[0]]
    assert q("cx_adjuster_oh", "SELECT count(*) FROM ins.policyholders") == [[352]]


def test_column_grants():
    from assistant import db
    for role, sql in [("cx_analyst", "SELECT email FROM ins.policyholders LIMIT 1"),
                      ("cx_analyst", "SELECT incident_location FROM ins.claims LIMIT 1"),
                      ("cx_adjuster_oh", "SELECT fraud_reported FROM ins.claims LIMIT 1"),
                      ("cx_adjuster_oh", "SELECT count(*) FROM triage.decisions")]:
        with pytest.raises(db.QueryError) as e:
            q(role, sql)
        assert e.value.permission_denied
    assert q("cx_analyst", "SELECT count(*) FROM ins.claims WHERE fraud_reported") == [[247]]
    assert "@example.com" in q("cx_adjuster_oh", "SELECT email FROM ins.policyholders LIMIT 1")[0][0]


def test_document_acl():
    docs = lambda r: {x[0] for x in q(r, "SELECT DISTINCT doc_id FROM app.doc_chunks")}   # noqa: E731
    assert "underwriting_guidelines_2015" in docs("cx_admin")
    assert "underwriting_guidelines_2015" not in docs("cx_siu")
    assert "siu_fraud_guide" in docs("cx_siu") and "siu_fraud_guide" not in docs("cx_analyst")
    assert "reserve_guidelines" in docs("cx_adjuster_oh") and "reserve_guidelines" not in docs("cx_analyst")
    assert "siu_fraud_guide" in docs("cx_triage")


def test_attack_suite_all_contained():
    from eval.assistant.rbac_suite import main
    assert main() == 0
