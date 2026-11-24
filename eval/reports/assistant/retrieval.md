# Retrieval evaluation (offline, no LLM)

24 questions with gold documents; retrieval runs as the asking user's DB role. Corpus: 10 documents / 40 chunks; embeddings: `local`.

| Mode | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|---|
| fts | 0.88 | 1.00 | 1.00 | 0.93 |
| vector | 0.79 | 1.00 | 1.00 | 0.89 |
| hybrid | 0.92 | 1.00 | 1.00 | 0.96 |

**Document ACL:** restricted document returned in 0 of 15 (question × mode) checks, searching the top 50 chunks. Enforced by row-level security on `app.doc_chunks`.

