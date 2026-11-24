"""
Hybrid document retrieval over app.doc_chunks.

Both retrievers run AS THE USER'S ROLE, so the row-level-security ACL on
doc_chunks decides what can be retrieved: a chunk the user may not read is
never ranked, never returned and never reaches the prompt.

  fts     Postgres full-text search, ts_rank_cd over a weighted tsvector
          (title/section weight A, body weight B), websearch_to_tsquery with an
          OR-relaxed fallback so long natural-language questions still match
  vector  pgvector cosine distance (HNSW index)
  hybrid  Reciprocal Rank Fusion of the two lists (k = 60)
"""

from __future__ import annotations

import re

from . import db
from .embeddings import embed, to_pgvector

RRF_K = 60
_STOP = set("a an the of to in on for and or is are was were be by with at from as it this that what which "
            "how many much do does did our we you your i my me show give list tell about please".split())


def _or_query(q: str) -> str:
    words = [w for w in re.findall(r"[a-zA-Z0-9]+", q.lower()) if w not in _STOP and len(w) > 1]
    return " | ".join(words[:12]) or "nothing"


def fts(role: str, query: str, k: int = 8) -> list[dict]:
    sql = """
      SELECT chunk_id, doc_id, title, section, content,
             ts_rank_cd(tsv, to_tsquery('english', %(q)s), 32) AS score
      FROM app.doc_chunks
      WHERE tsv @@ to_tsquery('english', %(q)s)
      ORDER BY score DESC, chunk_id
      LIMIT %(k)s
    """
    res = db.run_query(role, sql, {"q": _or_query(query), "k": k})
    return [dict(zip(res["columns"], r)) for r in res["rows"]]


def vector(role: str, query: str, k: int = 8) -> list[dict]:
    qv = to_pgvector(embed([query])[0])
    sql = """
      SELECT chunk_id, doc_id, title, section, content, 1 - (embedding <=> %(v)s::vector) AS score
      FROM app.doc_chunks
      ORDER BY embedding <=> %(v)s::vector, chunk_id
      LIMIT %(k)s
    """
    res = db.run_query(role, sql, {"v": qv, "k": k})
    return [dict(zip(res["columns"], r)) for r in res["rows"]]


def search(role: str, query: str, k: int = 4, mode: str = "hybrid") -> list[dict]:
    if mode == "fts":
        return fts(role, query, k)
    if mode == "vector":
        return vector(role, query, k)
    lists = [fts(role, query, 3 * k), vector(role, query, 3 * k)]
    scores: dict[str, float] = {}
    by_id: dict[str, dict] = {}
    for lst in lists:
        for rank, row in enumerate(lst):
            scores[row["chunk_id"]] = scores.get(row["chunk_id"], 0.0) + 1.0 / (RRF_K + rank + 1)
            by_id[row["chunk_id"]] = row
    ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
    return [dict(by_id[c], score=round(scores[c], 5)) for c in ranked]
