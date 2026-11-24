"""
Populate triage.decisions by running a triage system over the 231 eval claims,
with timestamps spread deterministically over one week (2026-11-16 … 2026-11-22),
so the analytics assistant has a realistic decision log to answer questions about.

    python -m scripts.seed_triage_log                 # rules baseline (no API key)
    python -m scripts.seed_triage_log --system agent  # the LLM agent (needs GROQ_API_KEY)

Rows are tagged source='seed' and system=<name>; re-running replaces earlier seed rows.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.decision_log import log_decision  # noqa: E402

WEEK_START = datetime(2026, 11, 16, tzinfo=timezone.utc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="rules")
    args = ap.parse_args()

    import psycopg

    from assistant import config
    from eval.dataset import EVAL_DATASET
    from eval.systems import run_system

    with psycopg.connect(config.dsn("superuser"), autocommit=True) as c:
        c.execute("DELETE FROM triage.decisions WHERE source = 'seed'")
    n = 0
    for i, case in enumerate(EVAL_DATASET):
        t0 = time.perf_counter()
        out = run_system(args.system, case.claim_text)
        # 9:00–20:59 UTC on day i % 7, minute offsets deterministic in i
        when = WEEK_START + timedelta(days=i % 7, hours=9 + (i * 5) % 12, minutes=(i * 17) % 60)
        n += log_decision(out["state"], case.claim_text, source="seed", system=args.system,
                          model=None if args.system == "rules" else config.LLM_MODEL,
                          latency_ms=int((time.perf_counter() - t0) * 1000),
                          tokens=out["token_usage"].get("tokens_total"), decided_at=when)
    print(f"✓ logged {n} decisions from system={args.system}")


if __name__ == "__main__":
    main()
