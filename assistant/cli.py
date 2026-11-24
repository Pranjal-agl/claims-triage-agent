"""
Ask a question from the terminal and see the answer, the SQL and the trace.

    python -m assistant.cli --user olivia "How many Ohio claims are large losses?"
"""

import argparse

from .agent import Agent
from .config import USERS
from .tracing import render_tree


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--user", default="ana", choices=sorted(USERS))
    ap.add_argument("--retrieval", default="hybrid", choices=["hybrid", "fts", "vector"])
    args = ap.parse_args()
    r = Agent(retrieval_mode=args.retrieval).ask(args.user, args.question)
    print(f"\n{USERS[args.user].display}: {args.question}\n\n{r.answer}\n")
    for q in r.queries:
        print(("✓ " if q.get("ok") else "✗ ") + (q.get("executed_sql") or q["sql"]).replace("\n", " ")
              + ("" if q.get("ok") else f"   → {q.get('error')}"))
    if r.retrieved:
        print("docs:", ", ".join(sorted({h['chunk_id'] for h in r.retrieved})))
    print(f"\ntrace {r.trace_id}\n" + render_tree(r.trace))


if __name__ == "__main__":
    main()
