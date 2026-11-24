"""
Offline retrieval evaluation (no LLM): for every gold question with gold_docs,
query the retriever AS THAT USER'S ROLE and measure doc-level recall@k and MRR
for fts / vector / hybrid. Also verifies the document ACL: for doc_acl
questions, the restricted document must never be returned in any mode.

    python -m eval.assistant.retrieval_eval            → eval/reports/retrieval.md
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from assistant import config, retrieval  # noqa: E402
from eval.assistant.harness import load_gold  # noqa: E402
from eval.assistant.report import REPORTS  # noqa: E402

MODES = ["fts", "vector", "hybrid"]
KS = [1, 3, 5]
ACL_TARGETS = {"a01": "underwriting_guidelines_2015", "a02": "siu_fraud_guide",
               "a03": "underwriting_guidelines_2015", "z06": "underwriting_guidelines_2015",
               "a04": "reserve_guidelines"}


def doc_ranking(role: str, q: str, mode: str, k: int = 10) -> list[str]:
    seen: list[str] = []
    for h in retrieval.search(role, q, k=k, mode=mode):
        if h["doc_id"] not in seen:
            seen.append(h["doc_id"])
    return seen


def main() -> None:
    gold = load_gold()
    items = [g for g in gold if g.get("gold_docs")]
    res = {m: {"recall": {k: 0.0 for k in KS}, "mrr": 0.0, "misses": []} for m in MODES}
    for it in items:
        role = config.USERS[it["user"]].db_role
        for m in MODES:
            ranked = doc_ranking(role, it["question"], m)
            golds = set(it["gold_docs"])
            for k in KS:
                res[m]["recall"][k] += len(golds & set(ranked[:k])) / len(golds)
            rr = next((1 / (i + 1) for i, d in enumerate(ranked) if d in golds), 0.0)
            res[m]["mrr"] += rr
            if not golds & set(ranked[:3]):
                res[m]["misses"].append(f"{it['id']} ({it['question'][:50]}…) → {ranked[:3]}")
    n = len(items)
    from assistant import db
    n_docs, n_chunks = db.run_query("cx_admin", "SELECT count(DISTINCT doc_id), count(*) FROM app.doc_chunks")["rows"][0]
    acl_checks = acl_leaks = 0
    for g in gold:
        target = ACL_TARGETS.get(g["id"])
        if not target:
            continue
        role = config.USERS[g["user"]].db_role
        for m in MODES:
            acl_checks += 1
            acl_leaks += target in doc_ranking(role, g["question"], m, k=50)

    L = ["# Retrieval evaluation (offline, no LLM)", "",
         f"{n} questions with gold documents; retrieval runs as the asking user's DB role. "
         f"Corpus: {n_docs} documents / {n_chunks} chunks; embeddings: `{config.EMBED_PROVIDER}`.", "",
         "| Mode | Recall@1 | Recall@3 | Recall@5 | MRR |", "|---|---|---|---|---|"]
    for m in MODES:
        r = res[m]
        L.append(f"| {m} | " + " | ".join(f"{r['recall'][k] / n:.2f}" for k in KS) + f" | {r['mrr'] / n:.2f} |")
    L += ["", f"**Document ACL:** restricted document returned in {acl_leaks} of {acl_checks} "
          f"(question × mode) checks, searching the top 50 chunks. Enforced by row-level security on `app.doc_chunks`.", ""]
    for m in MODES:
        if res[m]["misses"]:
            L += [f"**{m} misses @3**", ""] + [f"- {x}" for x in res[m]["misses"]] + [""]
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "retrieval.md"
    out.write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
