"""
Build the claims warehouse in Postgres (16+ with pgvector).

    python -m warehouse.load                    # schema + data + roles + RLS + documents
    python -m warehouse.load --csv path.csv     # use a local copy of the dataset
    python -m warehouse.load --docs-only        # re-chunk / re-embed warehouse/docs/

Data provenance
───────────────
ins.* is loaded from `insurance_claims.csv` — the 1,000-claim US auto insurance
dataset widely used in fraud-detection research (Mendeley Data
doi:10.17632/992mh7dk9y, mirrored on GitHub). It is fetched from a pinned commit
and verified by SHA-256. The source has no names or emails, so two clearly
synthetic columns (full_name, email @example.com) are generated deterministically
to make personal-data access controls testable. Everything else is loaded as-is,
with '?' → NULL.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from assistant import config  # noqa: E402
from assistant.embeddings import embed, to_pgvector  # noqa: E402

DATA_REPO = "https://github.com/mwitiderrick/insurancedata"
DATA_COMMIT = "da55cd3aed3b29377049d2543154f62858264e18"
DATA_SHA256 = "309dae61bc98a5b3f5d137d922fe47ecf1aef1f522e0a2de373b2b21eb2b7b36"
SQL_DIR = ROOT / "warehouse" / "sql"
DOCS_DIR = ROOT / "warehouse" / "docs"

FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth",
         "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen",
         "Daniel", "Nancy", "Matthew", "Lisa", "Anthony", "Betty", "Mark", "Sandra", "Steven", "Ashley",
         "Paul", "Kimberly", "Andrew", "Emily", "Joshua", "Donna", "Kevin", "Michelle", "Brian", "Carol"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
        "Thompson", "White", "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen", "King"]


def superuser() -> psycopg.Connection:
    return psycopg.connect(config.dsn("superuser"), autocommit=True)


def fetch_csv(local: str | None) -> Path:
    if local:
        path = Path(local)
    else:
        tmp = Path(tempfile.mkdtemp(prefix="claims_data_"))
        print(f"• fetching {DATA_REPO}@{DATA_COMMIT[:7]} …")
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        subprocess.run(["git", "-C", str(tmp), "fetch", "-q", "--depth", "1", DATA_REPO, DATA_COMMIT], check=True)
        subprocess.run(["git", "-C", str(tmp), "checkout", "-q", "FETCH_HEAD"], check=True)
        path = tmp / "insurance_claims.csv"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != DATA_SHA256:
        raise SystemExit(f"insurance_claims.csv checksum mismatch ({digest}); refusing to load")
    return path


def _subs(sql: str) -> str:
    rp = config.ROLE_PASSWORDS
    for k, v in {"{{PW_ADMIN}}": rp["cx_admin"], "{{PW_ANALYST}}": rp["cx_analyst"],
                 "{{PW_ADJUSTER}}": rp["cx_adjuster_oh"], "{{PW_SIU}}": rp["cx_siu"],
                 "{{PW_TRIAGE}}": rp["cx_triage"], "{{PW_OBS}}": rp["cx_obs"],
                 "{{EMBED_DIM}}": str(config.EMBED_DIM)}.items():
        sql = sql.replace(k, v.replace("'", "''"))
    return sql


def apply_sql(name: str) -> None:
    with superuser() as c:
        c.execute(_subs((SQL_DIR / name).read_text()))
    print(f"• applied {name}")


def _yn(v: str):
    return {"YES": True, "NO": False}.get(v)


def synthetic_identity(i: int, policy_number: int) -> tuple[str, str]:
    h = int(hashlib.sha256(f"{policy_number}".encode()).hexdigest(), 16)
    first, last = FIRST[h % len(FIRST)], LAST[(h // 97) % len(LAST)]
    return f"{first} {last}", f"{first}.{last}{i:04d}@example.com".lower()


def load_data(csv_path: Path) -> None:
    import csv
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    holders, policies, vehicles, claims = [], [], [], []
    for i, r in enumerate(rows, 1):
        pn = int(r["policy_number"])
        name, email = synthetic_identity(i, pn)
        holders.append((i, name, email, int(r["age"]), r["insured_sex"], r["insured_education_level"],
                        r["insured_occupation"], r["insured_hobbies"], r["insured_relationship"],
                        r["insured_zip"], int(r["capital-gains"]), int(r["capital-loss"]), int(r["months_as_customer"])))
        per_person, per_acc = (int(x) * 1000 for x in r["policy_csl"].split("/"))
        policies.append((pn, i, r["policy_bind_date"], r["policy_state"], r["policy_csl"], per_person, per_acc,
                         int(r["policy_deductable"]), float(r["policy_annual_premium"]), int(r["umbrella_limit"])))
        vehicles.append((pn, r["auto_make"], r["auto_model"], int(r["auto_year"])))
        claims.append((i, pn, r["incident_date"], r["incident_type"],
                       None if r["collision_type"] == "?" else r["collision_type"], r["incident_severity"],
                       r["authorities_contacted"] or "None", r["incident_state"], r["incident_city"],
                       r["incident_location"], int(r["incident_hour_of_the_day"]),
                       int(r["number_of_vehicles_involved"]), _yn(r["property_damage"]), int(r["bodily_injuries"]),
                       int(r["witnesses"]), _yn(r["police_report_available"]), int(r["total_claim_amount"]),
                       int(r["injury_claim"]), int(r["property_claim"]), int(r["vehicle_claim"]),
                       r["fraud_reported"] == "Y"))
    with superuser() as c, c.cursor() as cur:
        cur.execute("TRUNCATE ins.claims, ins.insured_vehicles, ins.policies, ins.policyholders")
        cur.executemany("INSERT INTO ins.policyholders VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", holders)
        cur.executemany("INSERT INTO ins.policies VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", policies)
        cur.executemany("INSERT INTO ins.insured_vehicles VALUES (%s,%s,%s,%s)", vehicles)
        cur.executemany("INSERT INTO ins.claims VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        claims)
    print(f"• loaded {len(claims)} claims / policies / policyholders")


def load_triage_book() -> None:
    from scripts.policies import POLICIES
    with superuser() as c, c.cursor() as cur:
        cur.execute("TRUNCATE triage.policies")
        cur.executemany("INSERT INTO triage.policies VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", POLICIES)
    print(f"• loaded {len(POLICIES)} triage-book policies")


_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)


def parse_doc(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    text = path.read_text(encoding="utf-8")
    m = _FRONT.match(text)
    meta: dict = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        v = v.strip()
        meta[k.strip()] = [x.strip() for x in v.strip("[]").split(",")] if v.startswith("[") else v
    sections = []
    for block in re.split(r"(?m)^## ", text[m.end():]):
        block = block.strip()
        if block:
            heading, _, content = block.partition("\n")
            sections.append((heading.strip(), content.strip()))
    return meta, sections


def ingest_docs() -> int:
    rows = []
    for path in sorted(DOCS_DIR.glob("*.md")):
        meta, sections = parse_doc(path)
        for i, (section, content) in enumerate(sections):
            rows.append((f"{meta['id']}#{i}", meta["id"], meta["title"], section, content, meta["allowed_roles"]))
    vectors = embed([f"{r[2]} — {r[3]}\n{r[4]}" for r in rows])
    with superuser() as c, c.cursor() as cur:
        cur.execute("TRUNCATE app.doc_chunks")
        cur.executemany("INSERT INTO app.doc_chunks (chunk_id, doc_id, title, section, content, allowed_roles, embedding) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s::vector)", [(*r, to_pgvector(v)) for r, v in zip(rows, vectors)])
    print(f"• ingested {len(rows)} chunks from {len({r[1] for r in rows})} documents")
    return len(rows)


def ensure_database() -> None:
    admin = config.dsn("superuser").replace(f"dbname={config.PG_DB}", "dbname=postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config.PG_DB,)).fetchone():
            c.execute(f'CREATE DATABASE "{config.PG_DB}"')
            print(f"• created database {config.PG_DB}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--docs-only", action="store_true")
    args = ap.parse_args()
    if not args.docs_only:
        ensure_database()
        apply_sql("00_schema.sql")
        load_data(fetch_csv(args.csv))
        load_triage_book()
        for f in ("10_roles.sql", "20_rls.sql", "30_docs_traces.sql"):
            apply_sql(f)
    ingest_docs()
    print("✓ claims warehouse ready")


if __name__ == "__main__":
    main()
