"""
Text embeddings.

local (default): deterministic feature-hashed character n-grams (3–5) plus word
unigrams, signed hashing into EMBED_DIM dims, L2-normalised. No model download,
no network, identical across machines. It is a *lexical* embedding: robust to
typos and morphology ("refunds"/"refund"), not a semantic one, and it complements
Postgres full-text search in the hybrid retriever rather than replacing it.

openai: any OpenAI-compatible /embeddings endpoint (OpenAI, Together, a local
Ollama `nomic-embed-text`, …). Set EMBED_PROVIDER=openai, EMBED_MODEL and
EMBED_DIM, then re-run `python -m scripts.setup_db --ingest-only`.
"""

from __future__ import annotations

import hashlib
import math
import re

from . import config

_TOKEN = re.compile(r"[a-z0-9]+")


def _hash(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")


def local_embed(text: str, dim: int = config.EMBED_DIM) -> list[float]:
    v = [0.0] * dim
    words = _TOKEN.findall(text.lower())
    feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
    for w in words:
        padded = f"#{w}#"
        for n in (3, 4, 5):
            for i in range(len(padded) - n + 1):
                feats.append((f"c{n}:{padded[i:i + n]}", 0.5))
    for f, wt in feats:
        h = _hash(f)
        v[h % dim] += wt if (h >> 32) & 1 else -wt
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def embed(texts: list[str]) -> list[list[float]]:
    if config.EMBED_PROVIDER == "openai":
        from openai import OpenAI
        client = OpenAI(base_url=config.EMBED_BASE_URL, api_key=config.EMBED_API_KEY)
        resp = client.embeddings.create(model=config.EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]
    return [local_embed(t) for t in texts]


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
