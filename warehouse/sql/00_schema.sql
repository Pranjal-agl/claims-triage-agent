-- ════════════════════════════════════════════════════════════════════════════
-- 00_schema.sql — claims warehouse.
--
--   ins.*     historical US auto book: 1,000 policies / claims loaded from the
--             public insurance_claims.csv (see warehouse/load.py for provenance)
--   triage.*  the triage agent's retail book (scripts/policies.py) and its
--             decision log, written by the triage API / UI / scripts.seed_triage_log
--   app.*     role → scope mapping and the document store (30_docs_traces.sql)
--   obs.*     assistant traces (30_docs_traces.sql)
-- ════════════════════════════════════════════════════════════════════════════

CREATE SCHEMA IF NOT EXISTS ins;
CREATE SCHEMA IF NOT EXISTS triage;
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS ins.policyholders (
  policyholder_id     int PRIMARY KEY,
  full_name           text NOT NULL,       -- synthetic overlay (source data has no names)
  email               text NOT NULL,       -- synthetic overlay
  age                 int  NOT NULL,
  sex                 text,
  education_level     text,
  occupation          text,
  hobbies             text,
  relationship        text,
  insured_zip         text,
  capital_gains       int,
  capital_loss        int,
  months_as_customer  int  NOT NULL
);

CREATE TABLE IF NOT EXISTS ins.policies (
  policy_number       int PRIMARY KEY,
  policyholder_id     int NOT NULL REFERENCES ins.policyholders,
  bind_date           date NOT NULL,
  state               text NOT NULL,       -- OH | IL | IN  (drives regional access)
  csl                 text NOT NULL,       -- combined single limit, e.g. '250/500' ($k per person / per accident)
  bi_limit_per_person int  NOT NULL,       -- dollars, parsed from csl
  bi_limit_per_accident int NOT NULL,
  deductible          int  NOT NULL,
  annual_premium      numeric(10,2) NOT NULL,
  umbrella_limit      int  NOT NULL
);

CREATE TABLE IF NOT EXISTS ins.insured_vehicles (
  policy_number int PRIMARY KEY REFERENCES ins.policies,
  make  text NOT NULL,
  model text NOT NULL,
  year  int  NOT NULL
);

CREATE TABLE IF NOT EXISTS ins.claims (
  claim_id                int PRIMARY KEY,
  policy_number           int NOT NULL REFERENCES ins.policies,
  incident_date           date NOT NULL,
  incident_type           text NOT NULL,
  collision_type          text,            -- NULL = unknown ('?' in source)
  incident_severity       text NOT NULL,
  authorities_contacted   text NOT NULL,   -- 'None' means nobody was contacted
  incident_state          text NOT NULL,
  incident_city           text NOT NULL,
  incident_location       text NOT NULL,   -- street address (PII)
  incident_hour           int  NOT NULL,
  vehicles_involved       int  NOT NULL,
  property_damage         boolean,         -- NULL = unknown
  bodily_injuries         int  NOT NULL,
  witnesses               int  NOT NULL,
  police_report_available boolean,         -- NULL = unknown
  total_claim_amount      int  NOT NULL,
  injury_claim            int  NOT NULL,
  property_claim          int  NOT NULL,
  vehicle_claim           int  NOT NULL,
  fraud_reported          boolean NOT NULL -- SIU determination
);
CREATE INDEX IF NOT EXISTS claims_policy_idx ON ins.claims(policy_number);

CREATE TABLE IF NOT EXISTS triage.policies (
  policy_id      text PRIMARY KEY,
  holder_name    text NOT NULL,
  policy_type    text NOT NULL,
  coverage_limit numeric(12,2) NOT NULL,
  deductible     numeric(12,2) NOT NULL,
  start_date     date NOT NULL,
  end_date       date NOT NULL,
  status         text NOT NULL
);

CREATE TABLE IF NOT EXISTS triage.decisions (
  decision_id     bigserial PRIMARY KEY,
  decided_at      timestamptz NOT NULL DEFAULT now(),
  source          text NOT NULL,           -- api | ui | seed
  system          text NOT NULL,           -- agent | rules | single_prompt | …
  model           text,
  claim_text_sha  text NOT NULL,
  policy_id       text,                    -- as extracted (normalised)
  policy_found    boolean,
  claimed_amount  numeric(14,2),           -- INR
  incident_type   text,
  fraud_score     real,
  decision        text NOT NULL,           -- APPROVED | REJECTED | ESCALATED
  reason          text,                    -- short machine reason (see triage_runbook)
  payout          numeric(14,2),
  latency_ms      int,
  tokens          int,
  degraded        boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS decisions_time_idx ON triage.decisions(decided_at);
