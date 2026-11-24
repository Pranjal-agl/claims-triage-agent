"""
scripts/policies.py

Single source of truth for the mock policy table.

Imported by:
  - scripts/seed_db.py          (writes data/policies.db)
  - eval/generate_cases.py      (picks policies when generating eval cases)
  - baselines/single_prompt.py  (dumps the table into the prompt)

POL-001 … POL-008 are the original eight policies and are unchanged, so the
v1 hand-written eval cases keep their meaning. POL-009 … POL-030 were added for
the v2 eval set and deliberately include:
  - expired policies             (end_date before some incident dates)
  - not-yet-started policies     (start_date after some incident dates)
  - non-active statuses          ("lapsed", "cancelled")
  - a wide spread of coverage limits / deductibles per line
"""

# (policy_id, holder_name, policy_type, coverage_limit, deductible, start_date, end_date, status)
POLICIES: list[tuple[str, str, str, float, float, str, str, str]] = [
    # ── original 8 (do not edit — v1 cases depend on them) ─────────────────
    ("POL-001", "Ramesh Kumar",    "auto",      500000.0,  10000.0, "2023-01-01", "2026-01-01", "active"),
    ("POL-002", "Priya Sharma",    "health",   1000000.0,   5000.0, "2024-03-15", "2025-03-15", "active"),
    ("POL-003", "Anil Verma",      "property", 2000000.0,  25000.0, "2022-06-01", "2026-06-01", "active"),
    ("POL-004", "Sunita Patel",    "auto",      300000.0,  15000.0, "2024-01-01", "2027-01-01", "active"),
    ("POL-005", "Vikram Singh",    "health",    750000.0,   7500.0, "2023-09-01", "2026-09-01", "active"),
    ("POL-006", "Deepa Nair",      "property", 5000000.0,  50000.0, "2021-11-01", "2026-11-01", "active"),
    ("POL-007", "Rahul Gupta",     "auto",      400000.0,  20000.0, "2024-07-01", "2027-07-01", "active"),
    ("POL-008", "Meera Joshi",     "health",    500000.0,   5000.0, "2025-01-01", "2026-01-01", "active"),
    # ── auto ────────────────────────────────────────────────────────────────
    ("POL-009", "Arjun Mehta",     "auto",      800000.0,  15000.0, "2024-04-01", "2027-04-01", "active"),
    ("POL-010", "Kavita Reddy",    "auto",      250000.0,   5000.0, "2023-05-15", "2026-05-15", "active"),
    ("POL-011", "Imran Shaikh",    "auto",      600000.0,  10000.0, "2025-02-01", "2028-02-01", "active"),
    ("POL-012", "Neha Kapoor",     "auto",      350000.0,   7500.0, "2022-03-01", "2025-03-01", "active"),
    ("POL-013", "Suresh Iyer",     "auto",      450000.0,  10000.0, "2024-01-10", "2027-01-10", "lapsed"),
    ("POL-014", "Pooja Desai",     "auto",     1200000.0,  25000.0, "2024-09-01", "2027-09-01", "active"),
    ("POL-030", "Aditi Chauhan",   "auto",      200000.0,   5000.0, "2024-02-15", "2027-02-15", "cancelled"),
    # ── health ──────────────────────────────────────────────────────────────
    ("POL-015", "Farhan Qureshi",  "health",    300000.0,   3000.0, "2024-02-01", "2027-02-01", "active"),
    ("POL-016", "Lakshmi Menon",   "health",   1500000.0,  10000.0, "2023-07-01", "2026-07-01", "active"),
    ("POL-017", "Rohit Bansal",    "health",    500000.0,   5000.0, "2025-04-01", "2026-04-01", "active"),
    ("POL-018", "Ananya Ghosh",    "health",   2000000.0,  20000.0, "2024-01-01", "2027-01-01", "active"),
    ("POL-019", "Gurpreet Kaur",   "health",    400000.0,   4000.0, "2022-10-01", "2024-10-01", "active"),
    ("POL-020", "Manoj Tiwari",    "health",    600000.0,   6000.0, "2024-06-01", "2027-06-01", "cancelled"),
    ("POL-021", "Sneha Kulkarni",  "health",   1000000.0,  10000.0, "2024-11-01", "2027-11-01", "active"),
    ("POL-028", "Zoya Khan",       "health",    800000.0,   8000.0, "2023-03-01", "2026-03-01", "active"),
    # ── property ────────────────────────────────────────────────────────────
    ("POL-022", "Harish Chandra",  "property", 3000000.0,  30000.0, "2024-03-01", "2027-03-01", "active"),
    ("POL-023", "Fatima Begum",    "property", 1000000.0,  10000.0, "2023-08-01", "2026-08-01", "active"),
    ("POL-024", "Kiran Rao",       "property", 7500000.0,  75000.0, "2025-01-15", "2028-01-15", "active"),
    ("POL-025", "Sanjay Malhotra", "property", 1500000.0,  15000.0, "2021-04-01", "2024-04-01", "active"),
    ("POL-026", "Ritu Agarwal",    "property", 2500000.0,  25000.0, "2024-05-01", "2027-05-01", "lapsed"),
    ("POL-027", "Thomas Mathew",   "property", 4000000.0,  40000.0, "2023-12-01", "2026-12-01", "active"),
    ("POL-029", "Venkat Rao",      "property",  600000.0,  10000.0, "2024-08-01", "2027-08-01", "active"),
]

COLUMNS = (
    "policy_id", "holder_name", "policy_type", "coverage_limit",
    "deductible", "start_date", "end_date", "status",
)


def policy_dicts() -> list[dict]:
    return [dict(zip(COLUMNS, row)) for row in POLICIES]


def by_id() -> dict[str, dict]:
    return {p["policy_id"]: p for p in policy_dicts()}
