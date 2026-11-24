from collections import Counter

from eval.dataset import EVAL_DATASET, V1_CASES, V2_CASES, V1_RELABELS
from eval.integrity import check_contamination, check_duplicates, check_generator, check_labels, check_rubric
from pathlib import Path


def test_sizes_and_ids():
    assert len(V1_CASES) == 25 and len(V2_CASES) >= 200
    assert len({c.id for c in EVAL_DATASET}) == len(EVAL_DATASET)


def test_every_label_matches_rubric():
    assert check_rubric(EVAL_DATASET) == []


def test_integrity_checks_clean():
    assert check_labels(EVAL_DATASET) == []
    assert check_duplicates(EVAL_DATASET) == []
    assert check_contamination(EVAL_DATASET, Path(__file__).parent.parent) == []
    assert check_generator() == []


def test_coverage_of_dataset():
    tiers = Counter(c.tier for c in V2_CASES)
    assert set(tiers) == {"canonical", "paraphrase", "noisy"}
    decisions = Counter(c.expected_decision for c in EVAL_DATASET)
    assert min(decisions.values()) >= 30
    assert sum("prompt_injection" in c.truth["flags"] for c in EVAL_DATASET) >= 10


def test_relabels_applied():
    by = {c.id: c for c in V1_CASES}
    for cid, (dec, band, _) in V1_RELABELS.items():
        assert (by[cid].expected_decision, by[cid].expected_fraud_band) == (dec, band)
