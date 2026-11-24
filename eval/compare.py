"""
eval/compare.py

Head-to-head comparison of systems scored on the SAME pinned dataset.

For each system: decision accuracy with 95% Wilson CI, macro-F1, fraud AUC,
injection resistance, extraction accuracy, tokens and cost per case, latency.
Against the reference system (default: agent): paired accuracy difference with
a 95% paired-bootstrap CI and an exact McNemar test — so "the agent is better"
is a measured, significance-tested claim, not two numbers side by side.

Usage:
    python -m eval.compare                                 # agent vs rules vs single_prompt
    python -m eval.compare --systems agent rules agent_no_fraud
    python -m eval.compare --update-readme                 # rewrite README results block
Writes eval/reports/comparison.md and eval/reports/comparison.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.metrics import mcnemar_exact, paired_bootstrap_diff, wilson_ci  # noqa: E402

ROOT = Path(__file__).parent.parent
RUNS = ROOT / "eval" / "runs"
REPORTS = ROOT / "eval" / "reports"
README = ROOT / "README.md"
DEFAULT_SYSTEMS = ["agent", "single_prompt", "rules"]
NICE = {"agent": "**Agent (LangGraph)**", "single_prompt": "Single-prompt LLM", "rules": "Rules-only",
        "agent_no_fraud": "Agent − fraud node", "agent_no_policy": "Agent − policy DB",
        "agent_simple_prompt": "Agent − structured decision", "agent_rag": "Agent + RAG (SIU guide)"}


def load(system: str, runs: Path = RUNS) -> dict | None:
    p = runs / f"latest_{system}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _fmt_ci(m: dict) -> str:
    ci = m["confidence_interval_95pct"]
    return f"{m['overall_accuracy_pct']:.1f}% [{ci['lower']:.1f}, {ci['upper']:.1f}]"


def build(systems: list[str], reference: str, runs: Path = RUNS) -> tuple[str, dict]:
    manifests = {s: load(s, runs) for s in systems}
    missing = [s for s, m in manifests.items() if m is None]
    present = {s: m for s, m in manifests.items() if m is not None}
    if not present:
        raise SystemExit("No run manifests found. Run e.g. `python -m eval.runner --system rules` first.")

    fps = {m["dataset_fingerprint"] for m in present.values()}
    warn = []
    if len(fps) > 1:
        warn.append("⚠️ Systems were run on different dataset versions; comparing the common case IDs only.")
    ids = set.intersection(*[{r["id"] for r in m["per_case_results"]} for m in present.values()])
    by_sys = {s: {r["id"]: r for r in m["per_case_results"] if r["id"] in ids} for s, m in present.items()}
    order = sorted(ids)
    n = len(order)

    lines = [f"# System comparison — claims triage (n = {n} cases)", ""]
    lines += warn
    if missing:
        lines.append(f"_Not yet run: {', '.join(missing)} — `python -m eval.runner --system <name>`._")
        lines.append("")

    # ── headline table
    lines += ["| System | Decision accuracy (95% CI) | Macro-F1 | Fraud AUC | Injection resisted | "
              "Amount extraction | Tokens / claim | $ / 1k claims | p50 latency |",
              "|---|---|---|---|---|---|---|---|---|"]
    summary: dict = {"n": n, "systems": {}, "paired_vs_reference": {}}
    for s, m in present.items():
        rows = [by_sys[s][i] for i in order]
        c = sum(r["decision_correct"] for r in rows)
        lo, hi = wilson_ci(c, n)
        inj = m["injection_resistance"]
        ex = m["extraction_accuracy"]["amount"]
        cost = m["cost_summary"]
        e2e = m["latency_summary"]["__end_to_end__"]
        lat = f"{e2e['p50_s']:.2f}s" if e2e["p50_s"] >= 0.01 else "<10ms"
        auc = m["fraud_auc_high_vs_rest"]
        lines.append(
            f"| {NICE.get(s, s)} | {100 * c / n:.1f}% [{lo:.1f}, {hi:.1f}] | {m['macro_f1']:.3f} | "
            f"{auc if auc == auc else '—'} | {inj['not_approved']}/{inj['total']} | {ex['accuracy_pct']}% | "
            f"{cost['avg_tokens_per_case']:.0f} | ${cost['estimated_cost_per_1k_claims_usd']:.2f} | {lat} |")
        summary["systems"][s] = {"accuracy_pct": round(100 * c / n, 1), "ci95": [lo, hi],
                                 "macro_f1": m["macro_f1"], "fraud_auc": auc}
    lines.append("")

    # ── paired tests
    if reference in present and len(present) > 1:
        lines += [f"### Paired difference vs {NICE.get(reference, reference).strip('*')}", "",
                  "| Comparison | Δ accuracy (pp) | 95% paired-bootstrap CI | McNemar exact p | "
                  "only ref right | only other right |", "|---|---|---|---|---|---|"]
        ref = [by_sys[reference][i]["decision_correct"] for i in order]
        for s in present:
            if s == reference:
                continue
            oth = [by_sys[s][i]["decision_correct"] for i in order]
            bs = paired_bootstrap_diff(ref, oth)
            mc = mcnemar_exact(ref, oth)
            sig = " ✱" if mc["p_value"] < 0.05 else ""
            lines.append(f"| {reference} − {s} | {bs['diff_pp']:+.1f} | [{bs['ci95_pp'][0]:+.1f}, "
                         f"{bs['ci95_pp'][1]:+.1f}] | {mc['p_value']:.4g}{sig} | {mc['a_only']} | {mc['b_only']} |")
            summary["paired_vs_reference"][s] = {**bs, **mc}
        lines += ["", "✱ p < 0.05. The bootstrap resamples cases jointly across systems, so the CI is "
                  "for the *difference*, which is much tighter than comparing two overlapping marginal CIs.", ""]

    # ── by tier
    tiers = ["canonical", "paraphrase", "noisy"]
    lines += ["### Accuracy by phrasing tier", "",
              "| System | " + " | ".join(f"{t} (n={sum(by_sys[next(iter(present))][i]['tier'] == t for i in order)})"
                                        for t in tiers) + " |",
              "|---|" + "---|" * len(tiers)]
    for s in present:
        cells = []
        for t in tiers:
            rs = [by_sys[s][i] for i in order if by_sys[s][i]["tier"] == t]
            c = sum(r["decision_correct"] for r in rs)
            cells.append(f"{100 * c / len(rs):.1f}%" if rs else "—")
        lines.append(f"| {NICE.get(s, s)} | " + " | ".join(cells) + " |")
    lines.append("")

    # ── by slice
    slices = sorted({by_sys[next(iter(present))][i]["slice"] for i in order})
    lines += ["### Accuracy by slice", "", "| Slice | n | " + " | ".join(NICE.get(s, s).strip("*") for s in present) + " |",
              "|---|---|" + "---|" * len(present)]
    for sl in slices:
        ids_sl = [i for i in order if by_sys[next(iter(present))][i]["slice"] == sl]
        cells = []
        for s in present:
            c = sum(by_sys[s][i]["decision_correct"] for i in ids_sl)
            cells.append(f"{c}/{len(ids_sl)}")
        lines.append(f"| {sl} | {len(ids_sl)} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines), summary


def update_readme(table_md: str) -> None:
    text = README.read_text()
    start, end = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
    if start not in text:
        print("README has no results markers; skipping.")
        return
    head = table_md.split("### Accuracy by phrasing tier")[0].split("\n", 2)[2]
    new = f"{start}\n_Auto-generated by `python -m eval.compare --update-readme`._\n\n{head.strip()}\n{end}"
    README.write_text(re.sub(re.escape(start) + r".*?" + re.escape(end), new, text, flags=re.S))
    print("✓ README results block updated")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", nargs="+", default=DEFAULT_SYSTEMS)
    ap.add_argument("--reference", default="agent")
    ap.add_argument("--runs", default=str(RUNS))
    ap.add_argument("--update-readme", action="store_true")
    args = ap.parse_args()
    md, summary = build(args.systems, args.reference, Path(args.runs))
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "comparison.md").write_text(md + "\n")
    (REPORTS / "comparison.json").write_text(json.dumps(summary, indent=2))
    print(md)
    print(f"\n→ {REPORTS / 'comparison.md'}")
    if args.update_readme:
        update_readme(md)


if __name__ == "__main__":
    main()
