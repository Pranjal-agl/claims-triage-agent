import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.policies import POLICIES  # noqa: E402

DB_PATH = Path(__file__).parent.parent / "data" / "policies.db"


def seed(db_path: Path = DB_PATH) -> int:
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS policies (
        policy_id      TEXT PRIMARY KEY,
        holder_name    TEXT,
        policy_type    TEXT,
        coverage_limit REAL,
        deductible     REAL,
        start_date     TEXT,
        end_date       TEXT,
        status         TEXT
    )
    """)
    # status: "active" | "lapsed" | "cancelled". The decision node checks both
    # status AND the incident date against [start_date, end_date].
    cur.executemany("INSERT OR REPLACE INTO policies VALUES (?,?,?,?,?,?,?,?)", POLICIES)
    conn.commit()
    conn.close()
    return len(POLICIES)


if __name__ == "__main__":
    n = seed()
    print(f"✓ Seeded {n} policies → {DB_PATH}")
