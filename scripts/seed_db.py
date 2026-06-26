import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "policies.db"
DB_PATH.parent.mkdir(exist_ok=True)

conn = sqlite3.connect(DB_PATH)
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

# status = "active" means the policy was valid during its coverage window.
# The decision node compares incident_date against start_date/end_date
# directly — do NOT rely on status alone for validity checks.
policies = [
    ("POL-001", "Ramesh Kumar",  "auto",      500000.0,  10000.0, "2023-01-01", "2026-01-01", "active"),
    ("POL-002", "Priya Sharma",  "health",   1000000.0,   5000.0, "2024-03-15", "2025-03-15", "active"),
    ("POL-003", "Anil Verma",    "property", 2000000.0,  25000.0, "2022-06-01", "2026-06-01", "active"),
    ("POL-004", "Sunita Patel",  "auto",      300000.0,  15000.0, "2024-01-01", "2027-01-01", "active"),
    ("POL-005", "Vikram Singh",  "health",    750000.0,   7500.0, "2023-09-01", "2026-09-01", "active"),
    ("POL-006", "Deepa Nair",    "property", 5000000.0,  50000.0, "2021-11-01", "2026-11-01", "active"),
    ("POL-007", "Rahul Gupta",   "auto",      400000.0,  20000.0, "2024-07-01", "2027-07-01", "active"),
    ("POL-008", "Meera Joshi",   "health",    500000.0,   5000.0, "2025-01-01", "2026-01-01", "active"),
]

cur.executemany("INSERT OR REPLACE INTO policies VALUES (?,?,?,?,?,?,?,?)", policies)
conn.commit()
conn.close()
print(f"✓ Seeded {len(policies)} policies → {DB_PATH}")
