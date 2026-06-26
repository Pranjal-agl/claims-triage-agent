import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "policies.db"

def lookup_policy(policy_id: str) -> dict:
    if not DB_PATH.exists():
        return {"found": False, "policy_id": policy_id, "error": "Database not initialized"}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id.strip().upper(),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"found": False, "policy_id": policy_id}
    return {"found": True, **dict(row)}
