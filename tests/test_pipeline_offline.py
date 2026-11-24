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
