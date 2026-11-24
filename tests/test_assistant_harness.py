from tests.conftest import requires_warehouse

pytestmark = requires_warehouse


def test_gold_valid_and_controls(tmp_path, monkeypatch):
    from eval.assistant import harness
    monkeypatch.setattr(harness, "RUNS", tmp_path)
    items = harness.prepare(harness.load_gold())
    assert len(items) >= 70 and harness.validate(items) == []
    o = harness.run(items, harness.OracleAgent({i["id"]: i for i in items}), "oracle_t")["summary"]
    assert o["pass_rate"] == 100.0 and o["leaks_in_answer"] == 0
    n = harness.run(items, harness.NullAgent(), "null_t")["summary"]
    assert n["execution_accuracy"]["passed"] == 0 and n["over_refusal"]["n"] == n["over_refusal"]["of"]
