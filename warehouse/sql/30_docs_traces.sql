-- ════════════════════════════════════════════════════════════════════════════
-- 30_docs_traces.sql — document store (FTS + pgvector) with a per-chunk ACL
-- enforced by row-level security, and the assistant's trace tables.
-- ════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;
-- 10_roles.sql revoked EXECUTE on every function in `public`; re-grant only the
-- pgvector extension's own functions/operators.
DO $$
DECLARE f regprocedure;
BEGIN
  FOR f IN SELECT p.oid::regprocedure FROM pg_proc p
           JOIN pg_depend d ON d.objid = p.oid AND d.deptype = 'e'
           JOIN pg_extension e ON e.oid = d.refobjid AND e.extname = 'vector' LOOP
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO PUBLIC', f);
  END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS app.doc_chunks (
  chunk_id      text PRIMARY KEY,
  doc_id        text NOT NULL,
  title         text NOT NULL,
  section       text NOT NULL,
  content       text NOT NULL,
  allowed_roles text[] NOT NULL,
  embedding     vector({{EMBED_DIM}}),
  tsv           tsvector GENERATED ALWAYS AS
                  (setweight(to_tsvector('english', title || ' ' || section), 'A') ||
                   setweight(to_tsvector('english', content), 'B')) STORED
);
CREATE INDEX IF NOT EXISTS doc_chunks_tsv_idx ON app.doc_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS doc_chunks_emb_idx ON app.doc_chunks USING hnsw (embedding vector_cosine_ops);
ALTER TABLE app.doc_chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acl ON app.doc_chunks;
CREATE POLICY acl ON app.doc_chunks FOR SELECT TO cx_admin, cx_analyst, cx_adjuster, cx_siu, cx_triage
  USING (EXISTS (SELECT 1 FROM unnest(allowed_roles) r
                 WHERE r = 'public' OR pg_has_role(current_user, r, 'MEMBER')));
GRANT SELECT ON app.doc_chunks TO cx_admin, cx_analyst, cx_adjuster, cx_siu, cx_triage;

CREATE SCHEMA IF NOT EXISTS obs;
REVOKE ALL ON SCHEMA obs FROM PUBLIC;
GRANT USAGE ON SCHEMA obs TO cx_obs;
CREATE TABLE IF NOT EXISTS obs.traces (
  trace_id uuid PRIMARY KEY, started_at timestamptz NOT NULL DEFAULT now(),
  app_user text NOT NULL, db_role text NOT NULL, question text NOT NULL, answer text,
  status text NOT NULL, duration_ms int, llm_calls int, tool_calls int,
  tokens_in int, tokens_out int, model text, tags jsonb DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS obs.spans (
  span_id uuid PRIMARY KEY, trace_id uuid NOT NULL REFERENCES obs.traces ON DELETE CASCADE,
  parent_id uuid, name text NOT NULL, started_at timestamptz NOT NULL,
  duration_ms real NOT NULL, status text NOT NULL, attrs jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS spans_trace_idx ON obs.spans(trace_id);
GRANT SELECT, INSERT ON obs.traces, obs.spans TO cx_obs;
