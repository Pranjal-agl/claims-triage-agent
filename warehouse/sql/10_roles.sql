-- ════════════════════════════════════════════════════════════════════════════
-- 10_roles.sql — one least-privilege LOGIN role per application role.
--
-- The assistant connects AS the user's role, so model-written SQL runs with
-- exactly that role's rights and cannot SET ROLE / set_config('role', …) into
-- another one (no login is a member of any other query role).
--
--   cx_admin         head of claims: everything
--   cx_analyst       actuarial / BI: all rows, NO personal data, sees fraud labels
--   cx_adjuster_oh   regional adjusters: only their policy state's rows,
--   cx_adjuster_il   personal data yes (they contact claimants), but NOT the
--   cx_adjuster_in   SIU fraud determination (avoids biasing adjustment)
--   cx_siu           special investigations: all rows, personal data, fraud labels
--   cx_triage        triage service: reads triage.policies + SIU guide, writes decisions
--   cx_obs           writes/reads assistant traces
-- ════════════════════════════════════════════════════════════════════════════

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['cx_admin','cx_analyst','cx_adjuster_oh','cx_adjuster_il','cx_adjuster_in',
                           'cx_siu','cx_triage','cx_obs'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN', r);
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cx_adjuster') THEN
    CREATE ROLE cx_adjuster NOLOGIN;
  END IF;
END $$;

ALTER ROLE cx_admin       PASSWORD '{{PW_ADMIN}}';
ALTER ROLE cx_analyst     PASSWORD '{{PW_ANALYST}}';
ALTER ROLE cx_adjuster_oh PASSWORD '{{PW_ADJUSTER}}';
ALTER ROLE cx_adjuster_il PASSWORD '{{PW_ADJUSTER}}';
ALTER ROLE cx_adjuster_in PASSWORD '{{PW_ADJUSTER}}';
ALTER ROLE cx_siu         PASSWORD '{{PW_SIU}}';
ALTER ROLE cx_triage      PASSWORD '{{PW_TRIAGE}}';
ALTER ROLE cx_obs         PASSWORD '{{PW_OBS}}';
GRANT cx_adjuster TO cx_adjuster_oh, cx_adjuster_il, cx_adjuster_in;

-- read-only + timeouts at the database level for every query role
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['cx_admin','cx_analyst','cx_adjuster_oh','cx_adjuster_il','cx_adjuster_in','cx_siu'] LOOP
    EXECUTE format('ALTER ROLE %I SET default_transaction_read_only = on', r);
    EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', r, '8s');
    EXECUTE format('ALTER ROLE %I SET work_mem = %L', r, '16MB');
    EXECUTE format('ALTER ROLE %I SET search_path = ins, triage, public', r);
  END LOOP;
  EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC');
END $$;

-- ── deny by default ─────────────────────────────────────────────────────────
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ins, triage, app FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public, ins, triage, app FROM PUBLIC;
GRANT USAGE ON SCHEMA ins, app TO cx_admin, cx_analyst, cx_adjuster, cx_siu, cx_triage;
GRANT USAGE ON SCHEMA public TO cx_admin, cx_analyst, cx_adjuster, cx_siu, cx_triage;
GRANT USAGE ON SCHEMA triage TO cx_admin, cx_analyst, cx_siu, cx_triage;

-- ── policies, vehicles: no personal data ───────────────────────────────────
GRANT SELECT ON ins.policies, ins.insured_vehicles TO cx_admin, cx_analyst, cx_adjuster, cx_siu;

-- ── policyholders: personal data by column ─────────────────────────────────
GRANT SELECT ON ins.policyholders TO cx_admin, cx_adjuster, cx_siu;
GRANT SELECT (policyholder_id, age, months_as_customer) ON ins.policyholders TO cx_analyst;

-- ── claims: street address is personal data; fraud label is SIU-restricted ──
GRANT SELECT ON ins.claims TO cx_admin, cx_siu;
GRANT SELECT (claim_id, policy_number, incident_date, incident_type, collision_type, incident_severity,
              authorities_contacted, incident_state, incident_city, incident_hour, vehicles_involved,
              property_damage, bodily_injuries, witnesses, police_report_available, total_claim_amount,
              injury_claim, property_claim, vehicle_claim, fraud_reported)
  ON ins.claims TO cx_analyst;
GRANT SELECT (claim_id, policy_number, incident_date, incident_type, collision_type, incident_severity,
              authorities_contacted, incident_state, incident_city, incident_location, incident_hour,
              vehicles_involved, property_damage, bodily_injuries, witnesses, police_report_available,
              total_claim_amount, injury_claim, property_claim, vehicle_claim)
  ON ins.claims TO cx_adjuster;

-- ── triage book and decision log ───────────────────────────────────────────
GRANT SELECT ON triage.policies, triage.decisions TO cx_admin, cx_analyst, cx_siu, cx_triage;
GRANT INSERT ON triage.decisions TO cx_triage;
GRANT USAGE ON SEQUENCE triage.decisions_decision_id_seq TO cx_triage;
