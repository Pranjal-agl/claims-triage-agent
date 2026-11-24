"""End-to-end with a fake LLM: graph wiring, new decision rules, runner, reports."""

from pathlib import Path

from eval.dataset import get_cases


def _run(text):
    from agents.graph import build_graph
    g = build_graph()
    return g.invoke({"claim_text": text, "extracted": None, "policy": None, "fraud": None,
                     "decision": None, "final_report": None, "error": None})


def test_graph_runs_and_reports(fake_llm):
    st = _run("Policy POL-004, claimant Sunita Patel. On 2024-11-10 a truck sideswiped my car. "
              "FIR filed (copy attached). Requesting Rs 65,000.")
    assert st["decision"]["decision"] == "APPROVED"
    assert "TRIAGE REPORT" in st["final_report"]
    assert st["error"] is None


def test_new_rules_inactive_and_pre_start(fake_llm):
    st = _run("Policy POL-020, claimant Manoj Tiwari. On 2025-04-01 I was hospitalised at CMC Vellore. "
              "Discharge summary and hospital bill attached. Claiming Rs 87,000.")
    assert st["decision"]["decision"] == "REJECTED" and "cancelled" in st["decision"]["justification"]
    st = _run("Kiran Rao, POL-024. On 2024-06-10 a pipe burst. Plumber invoice attached. Claiming Rs 50,000.")
    assert st["decision"]["decision"] == "REJECTED" and "precedes policy start" in st["decision"]["justification"]


def test_noisy_policy_id_is_normalised(fake_llm):
    st = _run("hi pls help. kavita reddy here, policy pol010, 11/02/2025 - pothole damage, "
              "workshop estimate attached, claim amt rs 30000")
    assert st["policy"]["found"] and st["policy"]["policy_id"] == "POL-010"


def test_runner_compare_and_error_analysis(fake_llm, tmp_path: Path):
    from eval import compare, error_analysis
    from eval.runner import run_eval
    cases = get_cases("v1")
    for system in ("agent", "single_prompt", "rules"):
        m = run_eval(system, cases, tmp_path, split="v1", sleep_s=0, quiet=True)
        assert m["total_cases"] == 25 and m["errors"] == 0
        assert {"confusion_matrix", "tier_metrics", "extraction_accuracy", "failure_breakdown"} <= set(m)
    md, summary = compare.build(["agent", "single_prompt", "rules"], "agent", tmp_path)
    assert "McNemar" in md and set(summary["systems"]) == {"agent", "single_prompt", "rules"}
    ea = error_analysis.build("agent", ["rules", "single_prompt"], runs=tmp_path)
    assert "Root cause" in ea


def test_resume_skips_done(fake_llm, tmp_path: Path):
    from eval.runner import run_eval
    cases = get_cases("v1")[:3]
    run_eval("rules", cases, tmp_path, sleep_s=0, quiet=True)
    m = run_eval("rules", cases, tmp_path, resume=True, sleep_s=0, quiet=True)
    assert m["total_cases"] == 3


def test_ablation_systems_run(fake_llm, tmp_path: Path):
    from eval.runner import run_eval
    cases = get_cases("v1")[:4]
    for system in ("agent_no_fraud", "agent_no_policy", "agent_simple_prompt"):
        m = run_eval(system, cases, tmp_path, sleep_s=0, quiet=True)
        assert m["total_cases"] == 4 and m["errors"] == 0


def test_degraded_pipeline_escalates_never_rejects(monkeypatch):
    """Regression: with the LLM down (e.g. retired model → 404), every claim used to be REJECTED
    because the extraction fallback has no policy_id. It must ESCALATE to a human instead."""
    import agents.nodes as nodes

    class Down:
        def with_structured_output(self, schema):
            return self

        def invoke(self, *a, **k):
            raise RuntimeError("Error code: 404 - model_not_found")
    monkeypatch.setattr(nodes, "get_llm", lambda: Down())
    st = _run("Policy POL-004, Sunita Patel. On 2024-11-10 a truck hit my car. FIR filed. Requesting Rs 65,000.")
    assert st["error"] and st["decision"]["decision"] == "ESCALATED"


def test_runner_marks_degraded_and_retries_on_resume(monkeypatch, tmp_path: Path):
    import agents.nodes as nodes
    from eval import runner

    class Down:
        def with_structured_output(self, schema):
            return self

        def invoke(self, *a, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(nodes, "get_llm", lambda: Down())
    monkeypatch.setattr(runner, "preflight", lambda: None)
    m = runner.run_eval("agent", get_cases("v1")[:2], tmp_path, sleep_s=0, quiet=True)
    assert m["errors"] == 2 and m["failure_breakdown"] == {"degraded": 2}
    assert list(tmp_path.glob("agent_*.partial.jsonl"))   # kept, so --resume re-runs them


def test_preflight_explains_retired_model(monkeypatch):
    import pytest

    import agents.llm as llm
    from eval import runner

    class Gone:
        def invoke(self, *a, **k):
            raise RuntimeError("Error code: 404 - {'error': {'code': 'model_not_found'}}")
    monkeypatch.setattr(llm, "make_chat_model", lambda *a, **k: Gone())
    with pytest.raises(SystemExit, match="LLM_MODEL"):
        runner.preflight()


def test_fraud_node_sees_verbatim_claim_text(fake_llm, monkeypatch):
    """Regression: the fraud node used to see only the extractor's one-line description, so a
    terse summary dropped 'FIR filed' / 'workshop quotes' and documented claims were scored as
    undocumented fraud. It must receive the original claim text."""
    import agents.nodes as nodes
    from tests.fake_llm import FakeLLM, _Bound

    class TerseExtractor(FakeLLM):
        def with_structured_output(self, schema):
            bound = super().with_structured_output(schema)
            if schema.__name__ != "ExtractedClaim":
                return bound
            orig = bound.invoke

            def invoke(prompt, config=None):
                out = orig(prompt, config)
                return out.model_copy(update={"description": "Truck sideswiped my car"})   # drops the FIR
            bound.invoke = invoke
            return bound
    monkeypatch.setattr(nodes, "get_llm", lambda: TerseExtractor())
    text = ("Policy POL-004, claimant Sunita Patel. On 2024-11-10 a truck sideswiped my car. "
            "Two workshop quotes attached. FIR filed (copy attached). Requesting Rs 65,000.")
    _run(text)
    prompt = _Bound.last_prompts["FraudAssessment"]
    assert "FIR filed (copy attached)" in prompt and "<claim>" in prompt
