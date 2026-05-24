-- v0.36.60 / Task #92 — Reconcile public-schema table + sequence ownership to halcyon_app.
--
-- Background
-- ----------
-- The 2026-05-14 incident (see memory feedback_drop_schema_grant_pattern) DROPped
-- the public schema and restored from a snapshot; the restore created all tables
-- owned by the `halcyon` superuser. The watch-loop runtime user is `halcyon_app`,
-- which cannot ALTER/DROP these tables -- only SELECT via PG's default PUBLIC
-- role. The immediate symptom (permission-denied restart loop) was addressed on
-- 2026-05-14 by GRANTing privileges; this migration completes that recovery by
-- transferring OWNERSHIP for the 5 tables that remained owned by halcyon, plus
-- the 2 sequences that drifted alongside.
--
-- Scope (discovered 2026-05-24 on live halcyon-pg via the queries documented in
-- the regression test in tests/test_table_ownership.py)
-- ----------------------------------------------------------------------------
--   5 tables: recommendations, shadow_trades, sync_state, traffic_light_state,
--             vix_term_structure
--   2 sequences: traffic_light_state_id_seq, vix_term_structure_id_seq
--
-- How to apply (operator-gated -- NOT auto-applied by the runtime)
-- ---------------------------------------------------------------
--   docker exec -i halcyon-pg psql -U halcyon -d halcyon \
--     < schema/migrations/2026-05-24_table_ownership_fix.sql
--
-- Verification post-apply (expected: zero rows)
-- ---------------------------------------------
--   docker exec halcyon-pg psql -U halcyon -d halcyon -t -c \
--     "SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public' \
--      AND tableowner != 'halcyon_app';"
--
--   docker exec halcyon-pg psql -U halcyon -d halcyon -t -c \
--     "SELECT c.relname, r.rolname FROM pg_class c \
--      JOIN pg_namespace n ON n.oid=c.relnamespace \
--      JOIN pg_authid r ON r.oid=c.relowner \
--      WHERE c.relkind='S' AND n.nspname='public' AND r.rolname != 'halcyon_app';"
--
-- Prevention against future restore-induced drift
-- -----------------------------------------------
-- scripts/render_to_local_migrate.py now calls apply_ownership_reconciliation()
-- after create_all_tables, so a future render->local restore (the 2026-05-14
-- code path) will not leave ownership skewed. See tests/test_table_ownership.py
-- for the ephemeral-PG boundary-touch regression lock + the live-PG policy
-- check (skip-unless-flagged).
--
-- Privilege requirement
-- ---------------------
-- ALTER TABLE OWNER requires superuser OR membership in BOTH current_user and
-- the target role. Run this migration as `halcyon` (superuser; member of
-- halcyon_app by virtue of superuser bypass). Running as halcyon_app will fail.

BEGIN;

-- Tables (5)
ALTER TABLE public.recommendations     OWNER TO halcyon_app;
ALTER TABLE public.shadow_trades       OWNER TO halcyon_app;
ALTER TABLE public.sync_state          OWNER TO halcyon_app;
ALTER TABLE public.traffic_light_state OWNER TO halcyon_app;
ALTER TABLE public.vix_term_structure  OWNER TO halcyon_app;

-- Sequences (2 -- the other 3 tables have non-SERIAL PKs and no associated sequence).
-- Note: ALTER TABLE OWNER above already CASCADES owner to a SERIAL-auto-created
-- linked sequence (pg_depend deptype='a'). These lines are therefore typically
-- no-ops on top of the cascade -- kept as belt-and-suspenders to (a) document
-- the policy explicitly, (b) cover any future migration where someone re-runs
-- ONLY the sequence block, and (c) recover from any post-cascade re-drift.
-- Order matters: they MUST come AFTER the matching ALTER TABLE to satisfy PG's
-- "linked sequence owner must match table owner" invariant.
ALTER SEQUENCE public.traffic_light_state_id_seq OWNER TO halcyon_app;
ALTER SEQUENCE public.vix_term_structure_id_seq  OWNER TO halcyon_app;

-- Belt-and-suspenders GRANT block per memory feedback_drop_schema_grant_pattern.
-- The 2026-05-14 recovery already applied these; re-running is idempotent + cheap,
-- and locks them in for the future-restore scenario where the operator runs this
-- migration in isolation.
GRANT ALL ON ALL TABLES    IN SCHEMA public TO halcyon_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO halcyon_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES    TO halcyon_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO halcyon_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO halcyon_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO halcyon_readonly;

COMMIT;
