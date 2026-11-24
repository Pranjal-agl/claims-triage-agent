-- ════════════════════════════════════════════════════════════════════════════
-- 20_rls.sql — regional adjusters see only their policy state.
-- The role → state map is a table (not a forgeable session variable); claims,
-- vehicles and policyholders are scoped through ins.policies, so the policies
-- compose automatically.
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS app.role_scope (role_name text PRIMARY KEY, state text NOT NULL);
INSERT INTO app.role_scope VALUES ('cx_adjuster_oh','OH'), ('cx_adjuster_il','IL'), ('cx_adjuster_in','IN')
ON CONFLICT (role_name) DO UPDATE SET state = EXCLUDED.state;
GRANT SELECT ON app.role_scope TO cx_adjuster;
-- each role may read only its own mapping row (found by eval/assistant/rbac_suite.py:
-- without this, an adjuster could enumerate every role's region)
ALTER TABLE app.role_scope ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_row ON app.role_scope;
CREATE POLICY own_row ON app.role_scope FOR SELECT TO cx_adjuster USING (role_name = current_user);

CREATE OR REPLACE FUNCTION app.my_states() RETURNS SETOF text
LANGUAGE sql STABLE AS $$ SELECT state FROM app.role_scope WHERE role_name = current_user $$;
REVOKE ALL ON FUNCTION app.my_states() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.my_states() TO cx_adjuster;

CREATE OR REPLACE FUNCTION pg_temp.policy(tbl text, name text, roles text, expr text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('DROP POLICY IF EXISTS %I ON %s', name, tbl);
  EXECUTE format('CREATE POLICY %I ON %s FOR SELECT TO %s USING (%s)', name, tbl, roles, expr);
END $$;

ALTER TABLE ins.policies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE ins.policyholders   ENABLE ROW LEVEL SECURITY;
ALTER TABLE ins.claims          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ins.insured_vehicles ENABLE ROW LEVEL SECURITY;

SELECT pg_temp.policy(t, 'all_rows', 'cx_admin, cx_analyst, cx_siu', 'true')
FROM unnest(ARRAY['ins.policies','ins.policyholders','ins.claims','ins.insured_vehicles']) t;

SELECT pg_temp.policy('ins.policies', 'own_region', 'cx_adjuster', 'state IN (SELECT app.my_states())');
SELECT pg_temp.policy('ins.policyholders', 'own_region', 'cx_adjuster',
  'EXISTS (SELECT 1 FROM ins.policies p WHERE p.policyholder_id = policyholders.policyholder_id)');
SELECT pg_temp.policy('ins.claims', 'own_region', 'cx_adjuster',
  'EXISTS (SELECT 1 FROM ins.policies p WHERE p.policy_number = claims.policy_number)');
SELECT pg_temp.policy('ins.insured_vehicles', 'own_region', 'cx_adjuster',
  'EXISTS (SELECT 1 FROM ins.policies p WHERE p.policy_number = insured_vehicles.policy_number)');
