# Insurance Claims Triage Agent

A production-grade multi-step agentic AI pipeline that autonomously processes
insurance claims — extracting structured data, querying a policy database,
assessing fraud risk, and making approve/reject/escalate decisions.

Built with **LangGraph** for agent orchestration and **Llama 3.1 70B** (Groq).
The engineering focus is on **proving** the system works: rigorous eval,
ablation studies, calibration analysis, shadow deployment, and a full
feedback loop from production back to offline metrics.

---

## Architecture

```
User Input (free-text claim)
        │
        ▼
┌───────────────┐
│    extract    │  LLM → structured fields (claimant, policy ID, amount, type)
└──────┬────────┘
       │
       ▼
┌───────────────┐
│ lookup_policy │  SQLite → coverage limit, status, deductible
└──────┬────────┘
       │
       ▼
┌───────────────┐
│ assess_fraud  │  LLM → fraud_score 0.0–1.0 + flag list
└──────┬────────┘
       │
    fraud > 0.75?
       ├─── YES ──► auto_reject ──┐
       │                          │
       └─── NO ───► decide ───────┤
                                  │
                                  ▼
                          generate_report
```

All LLM nodes are wrapped with `@_safe_node` — if any node fails (API down,
malformed output, timeout), it injects a safe ESCALATED default and sets an
error flag rather than crashing the pipeline.

---

## Benchmark Results

> Populated after running `python -m eval.runner` and `python -m eval.ablations`.
> Replace the placeholder rows with your actual numbers.

### Overall eval (25 held-out cases)

| Metric | Value |
|---|---|
| Overall accuracy | — / 25  (—%) |
| 95% Wilson CI | [—%, —%] |
| p50 latency (e2e) | —s |
| p99 latency (e2e) | —s |
| Est. cost per 25 cases | $— |

### Ablation study — component contribution

| Variant | Accuracy | Δ vs baseline | Description |
|---|---|---|---|
| baseline | —% | — | Full pipeline |
| no_fraud | —% | — | Fraud node bypassed (score=0) |
| no_policy | —% | — | Policy lookup bypassed |
| simple_prompt | —% | — | Minimal unstructured decision prompt |

> **How to read this:** the drop from `baseline` to `no_fraud` measures what
> the fraud assessment node contributes to decision accuracy independently of
> the LLM decision node. The drop from `baseline` to `no_policy` measures how
> much DB grounding matters vs pure LLM reasoning.

### Fraud score calibration

| Metric | Value |
|---|---|
| AUC-ROC | — |
| Brier score | — |
| Fraud vs legit mean separation | — |

---

## Eval Harness

### Dataset — 25 labeled held-out cases across 5 slices

| Slice | Cases | What it probes |
|---|---|---|
| `auto` | 5 | Vehicle claims at various amounts vs coverage limit |
| `health` | 5 | Health claims including partial/vague documentation |
| `property` | 5 | Property damage including grossly inflated amounts |
| `fraud` | 5 | High-confidence fraud — measures fraud detector TPR |
| `edge` | 5 | Expired policy, unknown policy ID, boundary amounts, missing info |

Cases are held out — they appear nowhere in prompts, few-shot examples,
or system messages. Verified by `eval/integrity.py`.

### What gets measured

| Layer | What | Tool |
|---|---|---|
| Decision accuracy | Overall + per-slice P/R/F1 | `eval/runner.py` |
| Confidence intervals | 95% Wilson CI (honest on n=25) | `eval/runner.py` |
| Failure mode taxonomy | wrong_extraction / wrong_fraud_band / wrong_decision | `eval/runner.py` |
| Fraud calibration | AUC-ROC, Brier score, score distribution by band | `eval/calibration.py` |
| Component contribution | 4-variant ablation suite with comparison table | `eval/ablations.py` |
| Dataset integrity | Contamination check, dedup, version pin, label sanity | `eval/integrity.py` |
| Drift detection | Decision distribution + fraud score mean shift | `eval/monitor.py` |
| Online accuracy | Labeled production sample vs offline baseline | `eval/feedback.py` + `eval/monitor.py` |
| Shadow deployment | Parallel primary/challenger with agreement rate | `eval/shadow.py` |
| Per-node latency | p50/p95/p99 per node and end-to-end | `eval/runner.py` |
| Cost tracking | Tokens in/out + estimated USD per run | `eval/runner.py` |
| Regression tracking | Per-case flip detection across runs | `eval/diff.py` |

---

## Running Everything

### Setup
```bash
git clone https://github.com/Pranjal-agl/claims-triage-agent
cd claims-triage-agent
cp .env.example .env          # add GROQ_API_KEY
pip install -r requirements.txt
python scripts/seed_db.py
```

### Eval pipeline (recommended order)

```bash
# 1. Verify dataset integrity before every eval run
python -m eval.integrity

# 2. Full eval — 25 cases, all metrics
python -m eval.runner

# 3. Ablation suite — isolate component contributions
python -m eval.ablations

# 4. Calibration analysis — fraud score quality
python -m eval.calibration --plot

# 5. Compare two runs for regression
python -m eval.diff eval/runs/run_A.json eval/runs/latest.json
```

### Production monitoring

```bash
# Start UI (normal mode)
streamlit run ui/app.py

# Enable shadow mode via the sidebar toggle in the UI
# Shadow decisions log to data/shadow_log.jsonl automatically

# After accumulating shadow traffic:
python -m eval.shadow --report --window 50

# Label a sample of production decisions for online accuracy:
python -m eval.feedback --n 20

# Check drift against offline baseline:
python -m eval.monitor --baseline eval/runs/latest.json
```

### Docker
```bash
docker-compose up --build
```

---

## Project Structure

```
claims-triage-agent/
├── agents/
│   ├── state.py          # TypedDict state + Pydantic output schemas
│   ├── tools.py          # SQLite policy lookup
│   ├── nodes.py          # LangGraph nodes; @_safe_node guardrail decorator
│   └── graph.py          # StateGraph + conditional fraud routing
├── eval/
│   ├── dataset.py        # 25 labeled held-out cases across 5 slices
│   ├── runner.py         # Eval harness: accuracy, CI, latency, cost, failure taxonomy
│   ├── ablations.py      # 4-variant ablation suite: baseline/no_fraud/no_policy/simple_prompt
│   ├── calibration.py    # AUC-ROC, Brier score, calibration curve
│   ├── integrity.py      # Contamination check, dedup, version pin, label sanity
│   ├── shadow.py         # Parallel shadow deployment + agreement report
│   ├── monitor.py        # Production logger + drift detection
│   ├── feedback.py       # Human labeling CLI → closes monitor feedback loop
│   ├── diff.py           # Regression diff between two run manifests
│   └── runs/             # Timestamped JSON run manifests (git-ignored)
├── ui/
│   └── app.py            # Streamlit UI with shadow mode toggle
├── scripts/
│   └── seed_db.py        # Seed SQLite with 8 mock policies
├── data/                 # policies.db, production_log.jsonl (git-ignored)
├── docker-compose.yml
└── requirements.txt
```

---

## Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph |
| LLM | Llama 3.1 70B via Groq (free tier) |
| Structured output | Pydantic + `.with_structured_output()` |
| Policy database | SQLite |
| REST API | FastAPI |
| UI | Streamlit |
| Containers | Docker + Docker Compose |
