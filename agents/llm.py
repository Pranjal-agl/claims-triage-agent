"""
agents/llm.py

One place to construct the chat model, so the agent, the baselines and the
ablations all use the same model and settings.

Environment variables
─────────────────────
LLM_PROVIDER   groq (default) | openai
               "openai" means any OpenAI-compatible endpoint: OpenAI, OpenRouter,
               Together, Fireworks, a local Ollama / vLLM server, etc.
LLM_MODEL      default: openai/gpt-oss-120b  (Groq retired llama-3.3-70b-versatile on 2026-08-16;
               qwen/qwen3.6-27b is the other recommended replacement)
LLM_BASE_URL   only for provider=openai (e.g. http://localhost:11434/v1 for Ollama)
LLM_API_KEY    only for provider=openai (GROQ_API_KEY is used for groq)
LLM_CACHE      path to a SQLite response cache, or "0" to disable.
               Default: .cache/llm_cache.sqlite. With temperature=0 a cached
               re-run is free and identical, and a run killed by a rate limit
               resumes without re-spending tokens.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "openai/gpt-oss-120b"
_ROOT = Path(__file__).parent.parent
_cache_installed = False


def model_name() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_MODEL)


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "groq").lower()


def install_cache() -> None:
    global _cache_installed
    if _cache_installed:
        return
    path = os.getenv("LLM_CACHE", str(_ROOT / ".cache" / "llm_cache.sqlite"))
    if path and path != "0":
        from langchain_core.globals import set_llm_cache
        from .cache import SQLiteLLMCache
        set_llm_cache(SQLiteLLMCache(path))
    _cache_installed = True


def make_chat_model(temperature: float = 0.0):
    install_cache()
    if provider() == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name(),
            temperature=temperature,
            base_url=os.getenv("LLM_BASE_URL") or None,
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "not-needed",
            max_retries=6,
        )
    from langchain_groq import ChatGroq
    return ChatGroq(model=model_name(), temperature=temperature, max_retries=6)
