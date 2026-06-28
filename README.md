# Insurance Claims Triage Agent

A production-grade multi-step agentic AI pipeline that autonomously processes
insurance claims - extracting structured data, querying a policy database,
assessing fraud risk, and making approve/reject/escalate decisions.

Built with **LangGraph** for agent orchestration and **Llama 3.3 70B** (Groq).
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

All LLM nodes are wrapped with `@_safe_node` - if any node fails (API down,
malformed output, timeout), it injects a safe ESCALATED default and sets an
error flag rather than crashing the pipeline.

---

## Benchmark Results

### Overall eval (25 held-out cases)

| Metric | Value |
|---|---|
| Overall accuracy | 24 / 25  (96.0%) |
| 95% Wilson CI | [80.5%, 99.3%] |
| p50 latency (e2e) | 1.4s |
| p95 latency (e2e) | 6.3s |
| p99 latency (e2e) | 271.8s (Groq cold-start on first request) |

### Per-slice accuracy

| Slice | Accuracy | Cases |
|---|---|---|
| Auto | 5/5 (100%) | Vehicle claims at various amounts vs coverage limit |
| Health | 5/5 (100%) | Health claims including partial/vague documentation |
| Property | 5/5 (100%) | Property damage including inflated amounts |
| Fraud | 4/5 (80%) | High-confidence fraud - tests fraud detector TPR |
| Edge | 5/5 (100%) | Expired policy, unknown ID, boundary amounts, missing info |

### Ablation study - component contribution

| Variant | Accuracy | Δ vs baseline | Description |
|---|---|---|---|
| baseline | 92.0% | - | Full pipeline |
| no_fraud | 52.0% | -40.0pp | Fraud node bypassed (score=0) |
| no_policy | 40.0% | -52.0pp | Policy lookup bypassed |
| simple_prompt | - | - | Rate-limited; rerun pending |

> **How to read this:** the -40pp drop from `baseline` to `no_fraud` means the fraud assessment node contributes 40 percentage points of accuracy independently of the decision node - it is genuinely load-bearing, not redundant. The -52pp drop from `baseline` to `no_policy` shows that without DB grounding, the decision node cannot distinguish valid from invalid policies and defaults to rejection.

### Fraud score calibration

| Metric | Value |
|---|---|
| AUC-ROC | 0.9933 (1.0 = perfect, 0.5 = random) |
| Brier score | 0.0588 (0.0 = perfect, 0.25 = random) |
| Fraud vs legit mean separation | +0.613 (low mean=0.215, high mean=0.828) |

The fraud scorer achieves near-perfect discrimination between legitimate and fraudulent claims. Score distribution is well-separated: low-risk claims cluster tightly at 0.20–0.30, high-risk claims at 0.80–0.98 with no overlap in the 0.50–0.75 range.

### Known calibration gap

`auto_05` (near-limit theft claim with FIR) consistently receives fraud scores of 0.90–0.98 despite having legitimate documentation. The model conflates "claiming near coverage limit" with fraud risk. This is a documented model limitation - in production, a secondary rule could cap fraud scores for theft claims with same-day FIR filings.

---

## Eval Harness

### Dataset - 25 labeled held-out cases across 5 slices

| Slice | Cases | What it probes |
|---|---|---|
| `auto` | 5 | Vehicle claims at various amounts vs coverage limit |
| `health` | 5 | Health claims including partial/vague documentation |
| `property` | 5 | Property damage including grossly inflated amounts |
| `fraud` | 5 | High-confidence fraud - measures fraud detector TPR |
| `edge` | 5 | Expired policy, unknown policy ID, boundary amounts, missing info |

Cases are held out - they appear nowhere in prompts, few-shot examples,
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

# 2. Full eval - 25 cases, all metrics
python -m eval.runner

# 3. Ablation suite - isolate component contributions
python -m eval.ablations

# 4. Calibration analysis - fraud score quality
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
