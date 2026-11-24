"""
eval/error_analysis.py

Error-analysis report from run manifests.

  1. Root-cause breakdown per system (stage attribution from eval/attribution.py)
  2. Failure table for the focal system — every wrong case with expected vs got,
     fraud score vs expected band, root cause and concrete evidence
  3. Where the focal system beats / loses to each baseline, by root cause
  4. Extraction accuracy per field × phrasing tier

Usage:
    python -m eval.error_analysis                         # focal=agent, vs rules & single_prompt
    python -m eval.error_analysis --system rules --vs agent
Writes eval/reports/error_analysis.md.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.compare import NICE, REPORTS, RUNS, load  # noqa: E402

CAUSE_HELP = {
    "extraction_policy_id": "wrong policy ID extracted → wrong DB row / not found",
    "extraction_amount": "amount mis-parsed (lakh/crore, words, multiple numbers)",
    "extraction_date": "incident date mis-parsed → wrong in-force verdict",
    "fraud_overscore": "legit claim scored too risky (auto-reject / needless escalation)",
    "fraud_underscore": "suspicious story scored too safe (fraud let through)",
    "injection_followed": "embedded instruction in the claim flipped the outcome to APPROVED",
    "decision_logic": "inputs fine, but the final rule application was wrong",
    "api_error": "system crashed / no decision",
}
ORDER = list(CAUSE_HELP)


def _short(s: str, n: int = 90) -> str:
    s = (s or "").replace("|", "/").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def build(focal: str, versus: list[str], max_rows: int = 80, runs: Path = RUNS) -> str:
    m = load(focal, runs)
    if m is None:
        raise SystemExit(f"No manifest for '{focal}'. Run: python -m eval.runner --system {focal}")
    others = {s: load(s, runs) for s in versus}
    others = {s: o for s, o in others.items() if o is not None}
    rows = m["per_case_results"]
    fails = [r for r in rows if not r["decision_correct"]]

    out = [f"# Error analysis — {NICE.get(focal, focal).strip('*')}",
           "", f"{len(fails)} wrong decisions out of {len(rows)} cases "
           f"({m['overall_accuracy_pct']:.1f}% accuracy, 95% CI "
           f"[{m['confidence_interval_95pct']['lower']}, {m['confidence_interval_95pct']['upper']}]).", ""]

    # 1. root causes across systems
    systems = {focal: m, **others}
    out += ["## 1. Root cause of wrong decisions", "",
            "| Root cause | What it means | " + " | ".join(NICE.get(s, s).strip("*") for s in systems) + " |",
            "|---|---|" + "---|" * len(systems)]
    per = {s: Counter(r["failure_mode"] for r in mm["per_case_results"] if not r["decision_correct"])
           for s, mm in systems.items()}
    for cause in ORDER:
        if any(per[s][cause] for s in systems):
            out.append(f"| `{cause}` | {CAUSE_HELP[cause]} | " + " | ".join(str(per[s][cause]) for s in systems) + " |")
    out.append("| **total wrong** | | " + " | ".join(f"**{sum(per[s].values())}**" for s in systems) + " |")
    out.append("")

    # 2. failure table
    out += [f"## 2. Every failure of {NICE.get(focal, focal).strip('*')}", "",
            "| Case | Slice | Tier | Expected | Got | Fraud score (exp. band) | Root cause | Evidence |",
            "|---|---|---|---|---|---|---|---|"]
    fails_sorted = sorted(fails, key=lambda r: (ORDER.index(r["failure_mode"]) if r["failure_mode"] in ORDER else 99, r["id"]))
    for r in fails_sorted[:max_rows]:
        sc = f"{r['actual_fraud_score']:.2f}" if r["actual_fraud_score"] is not None else "—"
        out.append(f"| `{r['id']}` | {r['slice']} | {r['tier']} | {r['expected_decision']} | {r['actual_decision']} | "
                   f"{sc} ({r['expected_fraud_band']}) | `{r['failure_mode']}` | {_short(r['evidence'])} |")
    if len(fails) > max_rows:
        out.append(f"| … | {len(fails) - max_rows} more in the run manifest | | | | | | |")
    out.append("")

    # Concentration: where do failures cluster?
    by_slice = Counter(r["slice"] for r in fails)
    by_tier = Counter(r["tier"] for r in fails)
    tier_n = Counter(r["tier"] for r in rows)
    slice_n = Counter(r["slice"] for r in rows)
    out += ["**Where failures concentrate**", ""]
    for sl, c in by_slice.most_common(5):
        out.append(f"- slice `{sl}`: {c}/{slice_n[sl]} wrong")
    for t, c in sorted(by_tier.items(), key=lambda x: -x[1] / tier_n[x[0]]):
        out.append(f"- tier `{t}`: {c}/{tier_n[t]} wrong ({100 * c / tier_n[t]:.0f}%)")
    out.append("")

    # 3. wins / losses vs each baseline
    focal_by_id = {r["id"]: r for r in rows}
    for s, o in others.items():
        ob = {r["id"]: r for r in o["per_case_results"]}
        common = [i for i in focal_by_id if i in ob]
        wins = [i for i in common if focal_by_id[i]["decision_correct"] and not ob[i]["decision_correct"]]
        losses = [i for i in common if not focal_by_id[i]["decision_correct"] and ob[i]["decision_correct"]]
        out += [f"## 3. {NICE.get(focal, focal).strip('*')} vs {NICE.get(s, s).strip('*')}", "",
                f"- {focal} right, {s} wrong: **{len(wins)}** — by {s}'s root cause: "
                + (", ".join(f"`{k}` {v}" for k, v in Counter(ob[i]['failure_mode'] for i in wins).most_common()) or "—"),
                f"- {s} right, {focal} wrong: **{len(losses)}**"
                + (" — " + ", ".join(f"`{i}`" for i in losses[:15]) if losses else ""), ""]
        win_slices = Counter(ob[i]["slice"] for i in wins).most_common(6)
        if win_slices:
            out.append("  Wins concentrated in: " + ", ".join(f"{k} ({v})" for k, v in win_slices))
            out.append("")

    # 4. extraction × tier
    out += ["## 4. Extraction accuracy by phrasing tier", "",
            "| System | Field | canonical | paraphrase | noisy |", "|---|---|---|---|---|"]
    for s, mm in systems.items():
        agg: dict = defaultdict(lambda: defaultdict(list))
        for r in mm["per_case_results"]:
            for f, v in (r.get("field_correct") or {}).items():
                if v is not None:
                    agg[f][r["tier"]].append(v)
        for f in ("policy_id", "amount", "date"):
            cells = []
            for t in ("canonical", "paraphrase", "noisy"):
                v = agg[f][t]
                cells.append(f"{100 * sum(v) / len(v):.0f}%" if v else "—")
            out.append(f"| {NICE.get(s, s).strip('*')} | {f} | " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="agent")
    ap.add_argument("--vs", nargs="*", default=["rules", "single_prompt"])
    ap.add_argument("--max-rows", type=int, default=80)
    args = ap.parse_args()
    md = build(args.system, [v for v in args.vs if v != args.system], args.max_rows)
    REPORTS.mkdir(parents=True, exist_ok=True)
    name = "error_analysis.md" if args.system == "agent" else f"error_analysis_{args.system}.md"
    (REPORTS / name).write_text(md + "\n")
    print(md)
    print(f"\n→ {REPORTS / name}")


if __name__ == "__main__":
    main()
