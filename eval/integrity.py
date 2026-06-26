"""
eval/integrity.py

Dataset integrity checks — run before any eval to verify:

1. CONTAMINATION CHECK
   Hash every eval case's claim_text and assert none of those strings
   (or substrings > 60 chars) appear in the agent source code (nodes.py,
   graph.py, state.py). Prevents the eval set from leaking into prompts.

2. DEDUPLICATION CHECK
   Assert no two eval cases share a claim_text fingerprint. Catches
   copy-paste errors in the dataset.

3. DATASET VERSION PINNING
   SHA-256 the entire serialised EVAL_DATASET and write it to
   eval/dataset.lock. On subsequent runs, compare against the lock —
   if labels or texts have changed without a deliberate version bump,
   the check fails loudly. Update the lock intentionally with --repin.

4. LABEL SANITY CHECK
   Assert all expected_decision values are in {APPROVED, REJECTED, ESCALATED}
   and all expected_fraud_band values are in {low, medium, high}.
   Catches typos before they silently skew metrics.

Usage:
    python -m eval.integrity          # check only — exits 1 if any check fails
    python -m eval.integrity --repin  # recompute and overwrite dataset.lock
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Source files whose content must not contain eval case text
_AGENT_SOURCE_FILES = [
    "agents/nodes.py",
    "agents/graph.py",
    "agents/state.py",
    "agents/tools.py",
]

LOCK_FILE = Path("eval/dataset.lock")
VALID_DECISIONS = {"APPROVED", "REJECTED", "ESCALATED"}
VALID_FRAUD_BANDS = {"low", "medium", "high"}

# Minimum substring length to flag as contamination.
# 60 chars is long enough to be unambiguous but short enough to
# catch partial inclusions (e.g. a sentence from a claim in a few-shot example).
_MIN_CONTAMINATION_LEN = 60


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _dataset_fingerprint(cases) -> str:
    """Stable fingerprint of the full dataset — serialise to canonical JSON then hash."""
    serialised = json.dumps(
        [
            {
                "id": c.id,
                "claim_text": c.claim_text,
                "expected_decision": c.expected_decision,
                "expected_fraud_band": c.expected_fraud_band,
                "slice": c.slice,
            }
            for c in sorted(cases, key=lambda c: c.id)
        ],
        sort_keys=True,
    )
    return _sha256(serialised)


def check_contamination(cases, project_root: Path) -> list[str]:
    """
    Return a list of violation strings (empty = clean).
    Checks whether any eval claim_text substring (>= _MIN_CONTAMINATION_LEN chars)
    appears verbatim in any agent source file.
    """
    violations = []
    source_contents: dict[str, str] = {}
    for rel in _AGENT_SOURCE_FILES:
        p = project_root / rel
        if p.exists():
            source_contents[rel] = p.read_text()

    for case in cases:
        text = case.claim_text
        # Check every sliding window of _MIN_CONTAMINATION_LEN chars
        # (checking the full text is sufficient since any match would show up,
        #  but we also check shorter substrings to catch partial inclusions)
        for start in range(0, len(text) - _MIN_CONTAMINATION_LEN + 1, 20):
            snippet = text[start : start + _MIN_CONTAMINATION_LEN]
            for filename, content in source_contents.items():
                if snippet in content:
                    violations.append(
                        f"CONTAMINATION: case '{case.id}' text found in {filename} "
                        f"at char {start}: {snippet[:40]!r}…"
                    )
                    break  # one violation per (case, file) pair is enough

    return violations


def check_duplicates(cases) -> list[str]:
    """Return violation strings for any duplicate claim_text fingerprints."""
    seen: dict[str, str] = {}
    violations = []
    for case in cases:
        fp = _sha256(case.claim_text)
        if fp in seen:
            violations.append(
                f"DUPLICATE: cases '{seen[fp]}' and '{case.id}' have identical claim_text"
            )
        else:
            seen[fp] = case.id
    return violations


def check_labels(cases) -> list[str]:
    """Return violation strings for invalid label values."""
    violations = []
    for case in cases:
        if case.expected_decision not in VALID_DECISIONS:
            violations.append(
                f"INVALID LABEL: case '{case.id}' expected_decision="
                f"'{case.expected_decision}' not in {VALID_DECISIONS}"
            )
        if case.expected_fraud_band not in VALID_FRAUD_BANDS:
            violations.append(
                f"INVALID LABEL: case '{case.id}' expected_fraud_band="
                f"'{case.expected_fraud_band}' not in {VALID_FRAUD_BANDS}"
            )
    return violations


def check_version(cases, repin: bool = False) -> list[str]:
    """
    Check dataset.lock matches current dataset fingerprint.
    If repin=True, write a new lock and return no violations.
    """
    fp = _dataset_fingerprint(cases)
    lock_data = {
        "fingerprint": fp,
        "n_cases": len(cases),
        "slices": sorted({c.slice for c in cases}),
    }

    if repin:
        LOCK_FILE.write_text(json.dumps(lock_data, indent=2))
        print(f"  ✓ Repinned dataset.lock  (fingerprint={fp[:16]}…, n={len(cases)})")
        return []

    if not LOCK_FILE.exists():
        # First run — create the lock automatically
        LOCK_FILE.write_text(json.dumps(lock_data, indent=2))
        print(f"  ✓ Created dataset.lock   (fingerprint={fp[:16]}…, n={len(cases)})")
        return []

    stored = json.loads(LOCK_FILE.read_text())
    if stored["fingerprint"] != fp:
        return [
            f"DATASET CHANGED: fingerprint mismatch — "
            f"stored={stored['fingerprint'][:16]}… current={fp[:16]}…\n"
            f"  If this was intentional, run: python -m eval.integrity --repin"
        ]
    return []


def run_all(repin: bool = False) -> bool:
    """
    Run all integrity checks. Returns True if all pass, False otherwise.
    Prints a clear report to stdout.
    """
    from eval.dataset import EVAL_DATASET

    project_root = Path(__file__).parent.parent
    all_violations: list[str] = []

    print(f"\n{'─'*60}")
    print(f"  Dataset Integrity Check  ({len(EVAL_DATASET)} cases)")
    print(f"{'─'*60}\n")

    checks = [
        ("Label sanity",    check_labels(EVAL_DATASET)),
        ("Deduplication",   check_duplicates(EVAL_DATASET)),
        ("Contamination",   check_contamination(EVAL_DATASET, project_root)),
        ("Version pin",     check_version(EVAL_DATASET, repin=repin)),
    ]

    for name, violations in checks:
        if violations:
            print(f"  ✗ {name}")
            for v in violations:
                print(f"      {v}")
            all_violations.extend(violations)
        else:
            print(f"  ✓ {name}")

    print()
    if all_violations:
        print(f"  {len(all_violations)} violation(s) found — fix before running eval.\n")
        return False
    else:
        print("  All checks passed.\n")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset integrity checks")
    parser.add_argument(
        "--repin",
        action="store_true",
        help="Recompute and overwrite dataset.lock (use after intentional dataset changes)",
    )
    args = parser.parse_args()
    ok = run_all(repin=args.repin)
    sys.exit(0 if ok else 1)
