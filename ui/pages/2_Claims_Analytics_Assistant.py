"""
Stage 2 — claims analytics assistant (Streamlit page).

Pick who you are, ask a question; see the answer, the SQL that ran AS your
database role, the documents used, and the trace.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from assistant.config import USERS, warehouse_available

st.set_page_config(page_title="Claims analytics assistant", page_icon="📊", layout="wide")
st.title("📊 Claims analytics assistant")

if not warehouse_available():
    st.error("The claims warehouse isn't reachable. Start Postgres and run `python -m warehouse.load`.")
    st.stop()


@st.cache_resource
def get_agent():
    from assistant.agent import Agent
    return Agent()


with st.sidebar:
    st.header("Signed in as")
    user = st.radio("user", list(USERS), format_func=lambda u: USERS[u].display, label_visibility="collapsed")
    st.caption(USERS[user].description)
    st.caption(f"Database role: `{USERS[user].db_role}`")
    st.divider()
    st.markdown("**Try**")
    for ex in ["What is our fraud rate by policy state?",
               "How many Ohio claims exceed an adjuster's settlement authority?",
               "How many claims did the triage agent escalate last week, by reason?",
               "List the names and emails of claimants with total-loss claims.",
               "Which red flags trigger an SIU referral?",
               "Summarize the March 2015 repair network bulletin."]:
        st.code(ex, language=None)

q = st.text_input("Ask about claims, policies, fraud, the triage log, or company policy")
if q:
    with st.spinner("Thinking…"):
        r = get_agent().ask(user, q, tags={"source": "ui"})
    st.markdown(r.answer)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("SQL (executed as your role)")
        for qq in r.queries:
            st.code(qq.get("executed_sql") or qq["sql"], language="sql")
            if qq.get("ok"):
                st.dataframe(pd.DataFrame(qq["rows"][:50], columns=qq["columns"]), use_container_width=True)
            else:
                st.error(qq.get("error"))
    with c2:
        st.subheader("Sources")
        for h in r.retrieved:
            with st.expander(f"{h['doc_id']} — {h['section']}"):
                st.write(h["content"])
        st.subheader("Trace")
        t = r.trace
        st.caption(f"{t['llm_calls']} LLM calls · {t['tool_calls']} tool calls · "
                   f"{t['tokens_in'] + t['tokens_out']} tokens · {t['duration_ms']} ms · trace {r.trace_id[:8]}")
        st.dataframe(pd.DataFrame([{"span": s["name"], "ms": s["duration_ms"], "status": s["status"],
                                    "detail": {k: v for k, v in s["attrs"].items() if k != "args"}}
                                   for s in t["spans"]]), use_container_width=True)
