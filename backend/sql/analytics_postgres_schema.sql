-- Run once in the Neon SQL editor as the project owner/admin, before assigning the
-- CRUD-only role used by the Render application. Do not use the owner URL in Render.
CREATE TABLE IF NOT EXISTS analytics_counter (
  org_id text NOT NULL,
  day text NOT NULL,
  kind text NOT NULL,
  k1 text NOT NULL,
  k2 text NOT NULL,
  device text NOT NULL,
  seg text NOT NULL,
  field text NOT NULL,
  n bigint NOT NULL,
  PRIMARY KEY (org_id, day, kind, k1, k2, device, seg, field)
);

CREATE TABLE IF NOT EXISTS analytics_heat (
  org_id text NOT NULL,
  page text NOT NULL,
  device text NOT NULL,
  seg text NOT NULL,
  kind text NOT NULL,
  gx integer NOT NULL,
  gy integer NOT NULL,
  n bigint NOT NULL,
  PRIMARY KEY (org_id, page, device, seg, kind, gx, gy)
);

CREATE INDEX IF NOT EXISTS analytics_heat_lookup_idx
  ON analytics_heat (org_id, page, kind);

-- Idempotency ledger for the one-off import. It is important for heat rows because
-- Mongo heat documents have cumulative counts but no day field; the history import
-- must add each Mongo document only once even if the command is rerun.
CREATE TABLE IF NOT EXISTS analytics_history_imports (
  source_collection text NOT NULL,
  source_id text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_collection, source_id)
);

-- Example least-privilege grants (replace analytics_app with the role you created):
-- GRANT USAGE ON SCHEMA public TO analytics_app;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON analytics_counter, analytics_heat TO analytics_app;
-- GRANT SELECT, INSERT ON analytics_history_imports TO analytics_app;
