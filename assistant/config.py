"""Configuration for the claims analytics assistant and the user → database-role map."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

PG_HOST = os.getenv("PGHOST", "localhost")
PG_PORT = int(os.getenv("PGPORT", "5432"))
PG_DB = os.getenv("PGDATABASE", "claims")
PG_ADMIN_USER = os.getenv("PG_SUPERUSER", "postgres")          # warehouse setup only
PG_ADMIN_PASSWORD = os.getenv("PG_SUPERUSER_PASSWORD", "postgres")

ROLE_PASSWORDS = {
    "cx_admin": os.getenv("PW_ADMIN", "dev-admin-pw"),
    "cx_analyst": os.getenv("PW_ANALYST", "dev-analyst-pw"),
    "cx_adjuster_oh": os.getenv("PW_ADJUSTER", "dev-adjuster-pw"),
    "cx_adjuster_il": os.getenv("PW_ADJUSTER", "dev-adjuster-pw"),
    "cx_adjuster_in": os.getenv("PW_ADJUSTER", "dev-adjuster-pw"),
    "cx_siu": os.getenv("PW_SIU", "dev-siu-pw"),
    "cx_triage": os.getenv("PW_TRIAGE", "dev-triage-pw"),
    "cx_obs": os.getenv("PW_OBS", "dev-obs-pw"),
}

# LLM: any OpenAI-compatible chat-completions endpoint with tool calling (default Groq).
LLM_BASE_URL = os.getenv("ASSISTANT_LLM_BASE_URL", os.getenv("LLM_BASE_URL") or "https://api.groq.com/openai/v1")
LLM_API_KEY = os.getenv("ASSISTANT_LLM_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY", "")
LLM_MODEL = os.getenv("ASSISTANT_LLM_MODEL", os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))
LLM_CACHE = os.getenv("LLM_CACHE", str(ROOT / ".cache" / "assistant_llm_cache.sqlite"))

EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://api.openai.com/v1")
EMBED_API_KEY = os.getenv("EMBED_API_KEY", os.getenv("OPENAI_API_KEY", ""))
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))

QUERY_SCHEMAS = ("ins", "triage")   # the only schemas model-written SQL may touch
MAX_ROWS_TO_LLM = 50
DEFAULT_LIMIT = 200
MAX_AGENT_STEPS = 8


@dataclass(frozen=True)
class AppUser:
    username: str
    display: str
    db_role: str
    description: str


# Demo identities. In production these come from your IdP; only the
# claim → db_role mapping lives here, because authorization lives in Postgres.
USERS: dict[str, AppUser] = {
    "alice": AppUser("alice", "Alice (Head of Claims)", "cx_admin",
                     "Head of claims: all regions, personal data, SIU fraud determinations, all documents"),
    "ana": AppUser("ana", "Ana (Claims analyst)", "cx_analyst",
                   "Actuarial analyst: all regions and fraud determinations, but NO personal data "
                   "(names, emails, addresses, zip codes, demographics)"),
    "olivia": AppUser("olivia", "Olivia (Ohio adjuster)", "cx_adjuster_oh",
                      "Regional adjuster for Ohio: only Ohio policies and their claims, including claimant "
                      "contact details; no SIU fraud determinations; no triage log"),
    "ian": AppUser("ian", "Ian (Illinois adjuster)", "cx_adjuster_il",
                   "Regional adjuster for Illinois: only Illinois policies and their claims, including claimant "
                   "contact details; no SIU fraud determinations; no triage log"),
    "isha": AppUser("isha", "Isha (Indiana adjuster)", "cx_adjuster_in",
                    "Regional adjuster for Indiana: only Indiana policies and their claims, including claimant "
                    "contact details; no SIU fraud determinations; no triage log"),
    "sam": AppUser("sam", "Sam (SIU investigator)", "cx_siu",
                   "Special investigations unit: all regions, personal data and fraud determinations, SIU documents"),
}


def dsn(role: str) -> str:
    if role == "superuser":
        return f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} user={PG_ADMIN_USER} password={PG_ADMIN_PASSWORD}"
    return f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} user={role} password={ROLE_PASSWORDS[role]}"


def warehouse_available() -> bool:
    try:
        import psycopg
        with psycopg.connect(dsn("cx_admin"), connect_timeout=2) as c:
            c.execute("SELECT 1 FROM ins.claims LIMIT 1")
        return True
    except Exception:
        return False
