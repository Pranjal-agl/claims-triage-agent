import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "policies.db"

_POL_RE = re.compile(r"\bPOL[\s\-_.#:]*0*(\d{1,5})\b", re.IGNORECASE)


def normalize_policy_id(raw: str) -> str:
    """
    Canonicalise free-text policy references to the DB key format POL-NNN.
      "pol012" / "POL 12" / "pol-012" / "Policy POL-012" → "POL-012"
    Anything that doesn't look like a POL id is returned stripped and upper-cased.
    """
    if not raw:
        return ""
    m = _POL_RE.search(str(raw))
    if m:
        return f"POL-{int(m.group(1)):03d}"
    return str(raw).strip().upper()


def lookup_policy(policy_id: str) -> dict:
    if not DB_PATH.exists():
        return {"found": False, "policy_id": policy_id, "error": "Database not initialized"}
    key = normalize_policy_id(policy_id)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM policies WHERE policy_id = ?", (key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"found": False, "policy_id": key}
    return {"found": True, **dict(row)}


def all_policies() -> list[dict]:
    """Full policy table (used by the single-prompt baseline)."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM policies ORDER BY policy_id")]
    conn.close()
    return rows
