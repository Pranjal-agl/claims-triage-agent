import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import streamlit as st
from eval.monitor import ProductionLogger
from eval.shadow import ShadowRunner

_logger = ProductionLogger()
_shadow_runner = None  # ShadowRunner instance, lazy-init when shadow mode is on

st.set_page_config(
    page_title="Claims Triage Agent",
    page_icon="🛡️",
    layout="wide",
)

# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")
    shadow_mode = st.toggle(
        "Shadow Mode",
        value=False,
        help=(
            "Run PRIMARY and SHADOW graphs in parallel on every claim. "
            "Only the PRIMARY result is shown. Shadow decisions are logged "
            "to data/shadow_log.jsonl for comparison.\n\n"
            "Use to validate a prompt change before rolling it out.\n\n"
            "Run `python -m eval.shadow --report` to see divergence."
        ),
    )
    if shadow_mode:
        st.info(
            "🔀 **Shadow mode ON**\n\n"
            "Two versions running in parallel. "
            "You see primary only. Shadow is logged silently.",
            icon="🔀",
        )
    st.divider()
    st.markdown("**Eval tools**")
    st.code(
        "python -m eval.runner\n"
        "python -m eval.ablations\n"
        "python -m eval.shadow --report\n"
        "python -m eval.monitor\n"
        "python -m eval.calibration\n"
        "python -m eval.feedback",
        language="bash",
    )

st.set_page_config(
    page_title="Claims Triage Agent",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ Insurance Claims Triage Agent")
st.caption("Multi-step agentic pipeline · LangGraph + Llama 3.1 70B (Groq) · SQLite policy DB")

SAMPLES = {
    "Auto Accident — Normal": (
        "Policy number POL-004. I am Sunita Patel. On December 15, 2024, I was involved in a "
        "rear-end collision on NH-44 near Nagpur. The other driver ran a red light and hit my car. "
        "My Honda City sustained damage to the rear bumper, trunk, and exhaust. Repair estimates "
        "from two authorised workshops total Rs. 85,000. I have photos and a police FIR. "
        "Requesting claim for Rs. 85,000."
    ),
    "Medical — High Amount": (
        "This is Vikram Singh, policy POL-005. I was hospitalised at Apollo Hospital Hyderabad "
        "from Nov 20–28, 2024 for emergency appendectomy followed by complications including "
        "post-op infection. Total bill is Rs. 6,80,000 covering surgery, 3-day ICU stay, "
        "medications, and follow-up. Attaching all original bills. Please process urgently."
    ),
    "Suspicious Theft — Likely Fraud": (
        "My name is John Doe, policy POL-001. My car was stolen last night. I am not sure of "
        "the exact date, maybe 3 weeks ago. I only realised when I needed it today. The car was "
        "a brand new luxury SUV worth Rs. 2,00,00,000. I did not file a police report because I "
        "was busy travelling. Please approve my full claim of Rs. 2,00,00,000 immediately."
    ),
    "Property Damage — Flood": (
        "Policy: POL-006, policyholder Deepa Nair. Heavy rainfall on August 14, 2024 caused "
        "severe flooding in my residential property in Bangalore. Ground floor submerged for "
        "36 hours; damage to flooring, furniture, electrical fittings, and appliances. Municipal "
        "corporation declared the area a natural disaster zone. Licensed surveyor assessed "
        "damage at Rs. 8,50,000. Claiming Rs. 8,50,000."
    ),
}

col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.subheader("Submit Claim")
    sample_choice = st.selectbox("Load sample", ["— type your own —"] + list(SAMPLES.keys()))
    claim_text = st.text_area(
        "Claim description",
        value=SAMPLES.get(sample_choice, ""),
        height=260,
        placeholder="Describe the claim in plain language…",
    )
    go = st.button("⚡ Process Claim", type="primary", use_container_width=True)

with col_right:
    st.subheader("Agent Pipeline")

    if go:
        if not claim_text.strip():
            st.error("Please enter or select a claim.")
        else:
            from agents.graph import claims_graph

            accumulated = {}
            node_latencies: dict[str, float] = {}

            if shadow_mode:
                # Shadow mode: run both graphs in parallel, show primary only
                global _shadow_runner
                if _shadow_runner is None:
                    _shadow_runner = ShadowRunner()
                with st.status("Running agent (shadow mode)…", expanded=True) as status_box:
                    st.write("🔀 Running PRIMARY + SHADOW in parallel…")
                    primary_state, primary_latency = _shadow_runner.run(claim_text)
                    accumulated = primary_state

                    # Reconstruct node display from final state
                    if accumulated.get("extracted"):
                        ext = accumulated["extracted"]
                        st.write(f"🔍 **Extracted** — {ext.get('claimant_name','?')} · "
                                 f"{ext.get('incident_type','?').replace('_',' ').title()} · "
                                 f"₹{ext.get('claimed_amount',0):,.0f}")
                    pol = accumulated.get("policy") or {}
                    if pol.get("found"):
                        st.write(f"📋 **Policy found** — {pol.get('policy_type','').title()} · "
                                 f"Limit ₹{pol.get('coverage_limit',0):,.0f}")
                    else:
                        st.write("⚠️ **Policy not found** in database")
                    fraud = accumulated.get("fraud") or {}
                    score = fraud.get("fraud_score", 0)
                    icon = "🔴" if score > 0.7 else "🟡" if score > 0.4 else "🟢"
                    st.write(f"{icon} **Fraud score** — {score:.0%}")
                    dec = (accumulated.get("decision") or {}).get("decision", "")
                    icon = "✅" if dec == "APPROVED" else "❌" if dec == "REJECTED" else "⚠️"
                    st.write(f"{icon} **Decision (primary)** — {dec}")
                    st.write(f"📄 Report generated  |  🔀 Shadow logged → `data/shadow_log.jsonl`")
                    status_box.update(label="✅ Done (shadow logged)", state="complete", expanded=False)
            else:
                # Normal mode: stream the graph node by node
                with st.status("Running agent…", expanded=True) as status_box:
                    import time as _time
                    t_prev = _time.perf_counter()
                    for chunk in claims_graph.stream(initial, stream_mode="updates"):
                        t_now = _time.perf_counter()
                        node_name = list(chunk.keys())[0]
                        node_latencies[node_name] = round(t_now - t_prev, 3)
                        updates = chunk[node_name]
                        accumulated.update(updates)
                        t_prev = t_now

                        if node_name == "extract":
                            ext = updates.get("extracted", {})
                            st.write(
                                f"🔍 **Extracted** — {ext.get('claimant_name', '?')} · "
                                f"{ext.get('incident_type','?').replace('_',' ').title()} · "
                                f"₹{ext.get('claimed_amount', 0):,.0f}"
                            )
                        elif node_name == "lookup_policy":
                            pol = updates.get("policy", {})
                            if pol.get("found"):
                                st.write(
                                    f"📋 **Policy found** — {pol.get('policy_type','').title()} · "
                                    f"Limit ₹{pol.get('coverage_limit', 0):,.0f} · {pol.get('status','').title()}"
                                )
                            else:
                                st.write("⚠️ **Policy not found** in database")
                        elif node_name == "assess_fraud":
                            fraud = updates.get("fraud", {})
                            score = fraud.get("fraud_score", 0)
                            icon = "🔴" if score > 0.7 else "🟡" if score > 0.4 else "🟢"
                            st.write(f"{icon} **Fraud score** — {score:.0%}")
                        elif node_name in ("decide", "auto_reject"):
                            dec = updates.get("decision", {})
                            d = dec.get("decision", "")
                            icon = "✅" if d == "APPROVED" else "❌" if d == "REJECTED" else "⚠️"
                            st.write(f"{icon} **Decision** — {d}")
                        elif node_name == "generate_report":
                            st.write("📄 Report generated")

                    status_box.update(label="✅ Done", state="complete", expanded=False)

            # Log to production monitor (for drift tracking)
            _logger.log_decision(claim_text, accumulated, node_latencies)

            # Surface any node-level error gracefully
            if accumulated.get("error"):
                st.warning(
                    f"⚠️ One or more processing steps encountered an error and "
                    f"fell back to safe defaults. The claim has been escalated "
                    f"for manual review.\n\n`{accumulated['error']}`"
                )

            final_decision = accumulated.get("decision", {}).get("decision", "")
            payout = accumulated.get("decision", {}).get("recommended_payout", 0)

            if final_decision == "APPROVED":
                st.success(f"**APPROVED** — Recommended payout: ₹{payout:,.0f}")
            elif final_decision == "REJECTED":
                st.error("**REJECTED** — See justification in report below")
            elif final_decision == "ESCALATED":
                st.warning("**ESCALATED** — Requires human review")

            if accumulated.get("final_report"):
                with st.expander("📄 Full Triage Report", expanded=True):
                    st.code(accumulated["final_report"], language=None)

            with st.expander("🔬 Raw agent state"):
                st.json({k: accumulated.get(k) for k in ("extracted", "policy", "fraud", "decision")})
    else:
        st.info("Select a sample or write a claim, then click **Process Claim**.")
        st.markdown("""
**Pipeline steps:**
1. `extract` — LLM parses free-text into structured fields  
2. `lookup_policy` — SQLite query by policy ID  
3. `assess_fraud` — LLM scores fraud risk 0–100%  
4. `route` — auto-reject if score > 75%, else proceed  
5. `decide` — LLM makes APPROVED / REJECTED / ESCALATED call  
6. `generate_report` — structured triage report  
""")
