"""
eval/feedback.py

Human feedback loop — closes the online monitoring loop started by monitor.py.

Reads unlabeled production decisions from data/production_log.jsonl, presents
each one for review, and writes labeled records to data/production_labels.jsonl.
Once labels accumulate, monitor.py's drift_report() uses them to compute
online accuracy and flag offline/online metric gaps.

WHY THIS EXISTS
───────────────
eval/monitor.py can detect distribution drift without labels (via decision
distribution shifts and fraud score mean drift). But it can only compute
*accuracy* — the most meaningful metric — if you have ground truth for at
least a sample of production cases. This CLI is how you build that sample
without an external annotation tool.

USAGE
─────
    python -m eval.feedback              # label all unlabeled cases
    python -m eval.feedback --n 20       # label at most 20 cases
    python -m eval.feedback --summary    # show labeling progress

WORKFLOW
────────
1. Process some live claims through the UI (shadow mode or normal)
2. Run: python -m eval.feedback --n 20
3. For each claim, the tool shows you the agent's decision and asks:
   Was it correct? (y/n) — if wrong, what should it have been?
4. Labels are written to production_labels.jsonl
5. Run: python -m eval.monitor --baseline eval/runs/latest.json
   → now shows online accuracy alongside distribution drift
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("data/production_log.jsonl")
LABELS_PATH = Path("data/production_labels.jsonl")
VALID_DECISIONS = ["APPROVED", "REJECTED", "ESCALATED"]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _already_labeled_prefixes(labels: list[dict]) -> set[str]:
    """Use claim_prefix as a dedup key — not perfect but sufficient for a feedback tool."""
    return {l.get("claim_prefix", "") for l in labels}


def _append_label(record: dict) -> None:
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LABELS_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def label_session(max_cases: int | None = None) -> None:
    prod_log = _load_jsonl(LOG_PATH)
    existing_labels = _load_jsonl(LABELS_PATH)
    labeled_prefixes = _already_labeled_prefixes(existing_labels)

    unlabeled = [
        r for r in prod_log
        if r.get("claim_prefix", "") not in labeled_prefixes
    ]

    if not unlabeled:
        print("\n  No unlabeled production decisions found.")
        print(f"  Log   : {LOG_PATH}  ({len(prod_log)} total records)")
        print(f"  Labels: {LABELS_PATH}  ({len(existing_labels)} labeled)\n")
        return

    to_label = unlabeled[:max_cases] if max_cases else unlabeled

    print(f"\n{'─'*60}")
    print(f"  Human Feedback Session")
    print(f"  {len(to_label)} claims to label  ({len(existing_labels)} already labeled)")
    print(f"  Press Ctrl+C at any time to stop — progress is saved after each label.")
    print(f"{'─'*60}\n")

    labeled_this_session = 0

    try:
        for i, record in enumerate(to_label, 1):
            ts = record.get("ts", "unknown time")
            prefix = record.get("claim_prefix", "")
            agent_decision = record.get("decision", "UNKNOWN")
            fraud_score = record.get("fraud_score", -1.0)
            latency = record.get("e2e_latency_s", "?")

            print(f"  [{i}/{len(to_label)}]  {ts[:19]}")
            print(f"  Claim    : \"{prefix}…\"")
            print(f"  Agent    : {agent_decision}  (fraud={fraud_score:.2f}, {latency}s)")
            print()

            # Get correct/incorrect
            while True:
                answer = input("  Was the agent correct? [y/n/skip]: ").strip().lower()
                if answer in ("y", "yes"):
                    correct_decision = agent_decision
                    break
                elif answer in ("n", "no"):
                    print(f"  Options: {', '.join(VALID_DECISIONS)}")
                    while True:
                        correction = input("  Correct decision: ").strip().upper()
                        if correction in VALID_DECISIONS:
                            correct_decision = correction
                            break
                        print(f"  Must be one of {VALID_DECISIONS}")
                    break
                elif answer in ("s", "skip", ""):
                    correct_decision = None
                    break
                else:
                    print("  Please enter y, n, or skip.")

            if correct_decision is None:
                print("  Skipped.\n")
                continue

            label_record = {
                "ts_labeled": datetime.now(timezone.utc).isoformat(),
                "ts_original": ts,
                "claim_prefix": prefix,
                "actual_decision": agent_decision,
                "expected_decision": correct_decision,
                "fraud_score": fraud_score,
                "correct": agent_decision == correct_decision,
            }
            _append_label(label_record)
            labeled_this_session += 1

            status = "✓ correct" if agent_decision == correct_decision else f"✗ should be {correct_decision}"
            print(f"  Saved — {status}\n")

    except KeyboardInterrupt:
        print("\n\n  Session interrupted.")

    print(f"{'─'*60}")
    print(f"  Session complete: {labeled_this_session} label(s) added")
    total = len(existing_labels) + labeled_this_session
    print(f"  Total labeled   : {total}")
    print(f"  Labels file     : {LABELS_PATH}")
    print(f"\n  Run drift report:")
    print(f"    python -m eval.monitor --baseline eval/runs/latest.json\n")


def summary() -> None:
    prod_log = _load_jsonl(LOG_PATH)
    labels = _load_jsonl(LABELS_PATH)
    labeled_prefixes = _already_labeled_prefixes(labels)
    unlabeled = [r for r in prod_log if r.get("claim_prefix", "") not in labeled_prefixes]

    correct = sum(1 for l in labels if l.get("correct", False))
    total_labeled = len(labels)
    online_acc = round(100 * correct / total_labeled, 1) if total_labeled else None

    print(f"\n{'─'*60}")
    print(f"  Feedback Summary")
    print(f"{'─'*60}")
    print(f"  Production log    : {len(prod_log)} total decisions")
    print(f"  Labeled           : {total_labeled}")
    print(f"  Unlabeled         : {len(unlabeled)}")
    if online_acc is not None:
        print(f"  Online accuracy   : {correct}/{total_labeled}  ({online_acc}%)")

    if labels:
        from collections import Counter
        decision_counts = Counter(l["actual_decision"] for l in labels)
        error_counts = Counter(
            f"{l['actual_decision']}→{l['expected_decision']}"
            for l in labels if not l.get("correct")
        )
        print(f"\n  Decision distribution (labeled sample):")
        for dec, count in decision_counts.most_common():
            print(f"    {dec:<12} {count}")
        if error_counts:
            print(f"\n  Error types:")
            for err, count in error_counts.most_common():
                print(f"    {err:<25} {count}")
    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Human feedback labeling tool")
    parser.add_argument("--n", type=int, default=None, help="Max cases to label this session")
    parser.add_argument("--summary", action="store_true", help="Show labeling progress and stats")
    args = parser.parse_args()

    if args.summary:
        summary()
    else:
        label_session(max_cases=args.n)
