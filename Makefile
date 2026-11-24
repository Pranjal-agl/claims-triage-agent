.PHONY: setup seed test integrity dataset eval-rules eval-agent eval-single eval-rag eval-ablations eval-all report \
        warehouse seed-log assistant-security assistant-retrieval assistant-controls assistant-eval assistant-ablations ask up

# ── stage 1: triage agent ───────────────────────────────────────────────────
setup:            ## install deps and seed the triage policy DB (SQLite)
	pip install -r requirements.txt && python scripts/seed_db.py
seed:
	python scripts/seed_db.py
test:             ## all offline tests (warehouse tests run when Postgres is up)
	python -m pytest -q
integrity:        ## labels vs rubric, leakage, dedup, generator repro, version pin
	python -m eval.integrity
dataset:          ## regenerate eval/data/claims_v2.jsonl (then: python -m eval.integrity --repin)
	python -m eval.generate_cases
eval-rules:       ## rules-only baseline (no API key)
	python -m eval.runner --system rules
eval-agent:       ## agent on all 231 cases (GROQ_API_KEY); resumable
	python -m eval.runner --system agent --resume
eval-single:      ## single-prompt LLM baseline; resumable
	python -m eval.runner --system single_prompt --resume
eval-rag:         ## agent + retrieved SIU guidance (needs the warehouse)
	python -m eval.runner --system agent_rag --resume
eval-ablations:
	for s in agent_no_fraud agent_no_policy agent_simple_prompt; do python -m eval.runner --system $$s --resume; done
eval-all: integrity eval-rules eval-agent eval-single report
report:           ## comparison table (+README block) and error analysis
	python -m eval.compare --systems agent single_prompt rules agent_rag --update-readme && python -m eval.error_analysis

# ── stage 2: claims analytics assistant ─────────────────────────────────────
up:               ## Postgres+pgvector → warehouse load → API :8000 + UI :8501
	docker compose up --build
warehouse:        ## build the Postgres warehouse (PG* env vars): data, roles, RLS, documents
	python -m warehouse.load
seed-log:         ## fill triage.decisions by running a triage system over the eval claims (SYSTEM=rules|agent)
	python -m scripts.seed_triage_log --system $(or $(SYSTEM),rules)
assistant-security:   ## 26 attacks, with and without the SQL guard
	python -m eval.assistant.rbac_suite
assistant-retrieval:  ## recall@k / MRR for fts, vector, hybrid + document ACL check
	python -m eval.assistant.retrieval_eval
assistant-controls:   ## scorer self-test (oracle must be 100%) and negative control
	python -m eval.assistant.harness --agent oracle --report && python -m eval.assistant.harness --agent null --report
assistant-eval:       ## the assistant on the 76-question gold set (GROQ_API_KEY); resumable
	python -m eval.assistant.harness --resume --report
assistant-ablations:
	python -m eval.assistant.harness --retrieval fts --resume --report
	python -m eval.assistant.harness --no-docs --resume --report
ask:              ## make ask USER=olivia Q="How many large-loss claims are there in my region?"
	python -m assistant.cli --user $(USER) "$(Q)"
