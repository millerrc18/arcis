"""v0.36.60 / Task #92 -- regression locks for public-schema ownership policy.

POLICY: every table and sequence in the public schema of halcyon-pg MUST be
owned by `halcyon_app`. Drift causes permission-denied restart loops at runtime
(the 2026-05-14 incident -- see memory `feedback_drop_schema_grant_pattern`),
because halcyon_app is the watch-loop runtime role and lacks ALTER/DROP rights
over tables owned by anyone else.

This file holds TWO regression tests with complementary coverage:

1. TestOwnershipReconciliationEphemeral -- BOUNDARY-TOUCH test against the
   ephemeral docker-compose.test.yml PG (port 5434). Real PG, no mocks at the
   seam. Creates the prod-mirror role topology (halcyon_app role), drops a few
   tables owned by the wrong role, runs `apply_ownership_reconciliation()`, and
   asserts every public table/sequence ends up owned by halcyon_app. This is
   the CI-runnable regression lock for the wire-up.

   Conforms to docs/standards/boundary-touch-tests.md:
   - Drives the FULL contract end-to-end (psycopg2 -> real PG -> pg_tables)
   - Asserts on actual database state (the OUTPUT of the contract)
   - Gold-standard question: would this test fail if apply_ownership_reconciliation
     were deleted? YES -- the assertion queries pg_tables directly and would
     show the drift.

2. TestLiveOwnershipPolicy -- skip-unless-flagged policy check against the
   operator's runtime PG (port 5433). NOT CI-runnable. Set
   ARCIS_LIVE_OWNERSHIP_CHECK=1 plus ARCIS_ALLOW_PROD_PG_IN_TESTS=1 (latter to
   bypass the conftest P0 guard) to run manually. Currently FAILs on operator's
   PG until the v0.36.60 migration is applied; passes thereafter. Forever
   useful as a policy assertion run on-demand.

   The conftest P0 guard (born from the 2026-05-14 prod-wipe incident) is
   defense-in-depth -- the test ALSO never writes to live PG, only SELECTs from
   pg_tables, but the bypass-flag pattern documents intentionality.

Both tests reference the wire-up at scripts/render_to_local_migrate.py:
apply_ownership_reconciliation -- changes there should make the ephemeral test
pass or change the policy this file enforces.
"""

from __future__ import annotations

import os
import sys

import psycopg2
import pytest

# scripts/ is not a Python package (no __init__.py) -- match the existing import
# pattern from tests/scripts/test_shared_migration_utils.py so sibling imports
# inside render_to_local_migrate.py (`from _shared_migration_utils import ...`)
# resolve correctly when invoked from pytest.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from render_to_local_migrate import apply_ownership_reconciliation  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: ephemeral-PG boundary-touch (CI-runnable regression lock)
# ---------------------------------------------------------------------------


# The exact 5 tables + 2 sequences fixed by v0.36.60. If these lists change,
# the migration SQL and the live-PG policy expectation change too -- this is
# the single source of truth for the v0.36.60 scope so reviewers can spot
# drift in either direction.
EXPECTED_FIXED_TABLES_2026_05_24 = [
    "recommendations",
    "shadow_trades",
    "sync_state",
    "traffic_light_state",
    "vix_term_structure",
]
EXPECTED_FIXED_SEQUENCES_2026_05_24 = [
    "traffic_light_state_id_seq",
    "vix_term_structure_id_seq",
]


@pytest.fixture
def ephemeral_pg_with_halcyon_app(pg_docker_url):
    """Provision the ephemeral PG (5434) with the prod role topology.

    Yields a connection URL for psycopg2. The ephemeral PG's `test` superuser
    CREATEs the `halcyon_app` role if absent (idempotent across pytest sessions
    because pg_docker_url is session-scoped and reuses the same container).
    Tables/sequences this test creates are dropped on teardown.
    """
    # `test:test@127.0.0.1:5434/halcyon` (when docker is up) -- test is SUPERUSER
    # per docker-compose.test.yml so it can CREATE ROLE + ALTER OWNER.
    url = pg_docker_url

    conn = psycopg2.connect(url, connect_timeout=10)
    conn.autocommit = True
    created_objects = {"tables": [], "sequences": []}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname='halcyon_app'")
            if not cur.fetchone():
                cur.execute("CREATE ROLE halcyon_app NOLOGIN")
        yield url, conn, created_objects
    finally:
        # Best-effort cleanup. autocommit=True so each DROP commits independently.
        # Drop tables FIRST: SERIAL-auto-created sequences are OWNED BY the table
        # and get dropped by CASCADE, so the explicit sequence drop is only for
        # standalone sequences not tied to a table (none currently, but kept for
        # future use). Tables-then-sequences avoids the column-default-references-
        # missing-sequence transient state if sequences were dropped first.
        try:
            with conn.cursor() as cur:
                for tname in created_objects["tables"]:
                    try:
                        cur.execute(f"DROP TABLE IF EXISTS public.{tname} CASCADE")
                    except Exception:
                        pass
                for sname in created_objects["sequences"]:
                    try:
                        cur.execute(f"DROP SEQUENCE IF EXISTS public.{sname} CASCADE")
                    except Exception:
                        pass
        finally:
            conn.close()


class TestOwnershipReconciliationEphemeral:
    """Boundary-touch: drive apply_ownership_reconciliation against real PG."""

    def _create_tables_owned_by(self, conn, owner: str, names: list[str]) -> None:
        """CREATE small tables, then ALTER OWNER to land at `owner`.

        CREATE TABLE assigns ownership to current_user, so to seed a misowner
        state we follow each CREATE with an explicit ALTER TABLE ... OWNER TO
        {owner}. (SET ROLE would also work but requires the caller to have
        membership in the target role; ALTER OWNER works whenever the caller
        has WRITE privilege, which is the common ephemeral-PG test case.)
        """
        with conn.cursor() as cur:
            for tname in names:
                cur.execute(f"CREATE TABLE public.{tname} (id SERIAL PRIMARY KEY, payload TEXT)")
                cur.execute(f"ALTER TABLE public.{tname} OWNER TO {owner}")

    def test_reconciliation_transfers_table_ownership_to_halcyon_app(
        self, ephemeral_pg_with_halcyon_app
    ):
        """The seam: tables owned by `test` (superuser) should become halcyon_app."""
        url, setup_conn, created = ephemeral_pg_with_halcyon_app
        misowned = ["t_ownership_a", "t_ownership_b", "t_ownership_c"]
        created["tables"].extend(misowned)
        # Sequences auto-created by SERIAL also need to be tracked for cleanup
        created["sequences"].extend(f"{n}_id_seq" for n in misowned)
        self._create_tables_owned_by(setup_conn, "test", misowned)

        # Sanity: before reconciliation, ownership is `test` (not halcyon_app).
        with setup_conn.cursor() as cur:
            cur.execute(
                "SELECT tableowner FROM pg_tables "
                "WHERE schemaname='public' AND tablename = ANY(%s) "
                "ORDER BY tablename",
                (misowned,),
            )
            pre_owners = {row[0] for row in cur.fetchall()}
        assert pre_owners == {"test"}, (
            f"Test setup invariant: misowned tables must start as `test`, got {pre_owners}"
        )

        # Drive the contract.
        result = apply_ownership_reconciliation(url)

        assert not result["skipped"], (
            f"Reconciliation skipped (expected to run as test superuser): {result}"
        )
        assert set(misowned).issubset(set(result["tables_altered"])), (
            f"All misowned tables should appear in tables_altered. "
            f"Expected superset of {misowned}, got {result['tables_altered']}"
        )

        # Post-condition assertion -- the policy: every table in public is halcyon_app.
        with setup_conn.cursor() as cur:
            cur.execute(
                "SELECT tablename, tableowner FROM pg_tables "
                "WHERE schemaname='public' AND tableowner != 'halcyon_app' "
                "ORDER BY tablename"
            )
            still_misowned = cur.fetchall()
        assert still_misowned == [], (
            f"Policy violation post-reconciliation: tables still not owned by "
            f"halcyon_app: {still_misowned}"
        )

    def test_reconciliation_transfers_standalone_sequence_to_halcyon_app(
        self, ephemeral_pg_with_halcyon_app
    ):
        """Regression-lock the ALTER SEQUENCE OWNER code path.

        PG behaviour discovered 2026-05-24 (see CHANGELOG v0.36.60): ALTER TABLE
        OWNER CASCADES the owner change to any SERIAL-auto-created sequence
        linked to the table (via pg_depend deptype='a'); a standalone non-linked
        sequence drifts independently. The prod state (5 tables + 2 sequences
        all owned by halcyon) is consistent with this: ALTER TABLE owner-changes
        on the 5 tables would auto-cascade the 2 linked sequences. The function's
        explicit ALTER SEQUENCE loop is for STANDALONE sequences only -- this
        test locks that path. Also note: trying to ALTER OWNER on a linked
        sequence to a role different from its table's owner raises
        "Sequence X is linked to table Y", so the linked-sequence drift
        scenario this test originally tried to construct is impossible in PG.
        """
        url, setup_conn, created = ephemeral_pg_with_halcyon_app
        sname = "_seq_standalone_x"
        created["sequences"].append(sname)
        with setup_conn.cursor() as cur:
            cur.execute(f"CREATE SEQUENCE public.{sname}")
            # CREATE SEQUENCE assigns owner=current_user (test) by default;
            # no explicit ALTER needed to establish the misownership.

        # Sanity: sequence starts as test (not halcyon_app).
        with setup_conn.cursor() as cur:
            cur.execute(
                "SELECT r.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_authid r ON r.oid=c.relowner "
                "WHERE c.relkind='S' AND n.nspname='public' AND c.relname=%s",
                (sname,),
            )
            seq_owner_pre = cur.fetchone()[0]
        assert seq_owner_pre == "test", (
            f"Test setup invariant: standalone sequence should start as `test`, "
            f"got {seq_owner_pre!r}"
        )

        result = apply_ownership_reconciliation(url)

        assert sname in result["sequences_altered"], (
            f"Sequence should appear in sequences_altered, got "
            f"{result['sequences_altered']}"
        )

        # Policy post-condition for sequences.
        with setup_conn.cursor() as cur:
            cur.execute(
                "SELECT c.relname, r.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_authid r ON r.oid=c.relowner "
                "WHERE c.relkind='S' AND n.nspname='public' "
                "AND r.rolname != 'halcyon_app' ORDER BY c.relname"
            )
            still_misowned = cur.fetchall()
        assert still_misowned == [], (
            f"Policy violation post-reconciliation: sequences still not owned "
            f"by halcyon_app: {still_misowned}"
        )

    def test_table_alter_cascades_to_linked_sequence(
        self, ephemeral_pg_with_halcyon_app
    ):
        """Lock the PG behaviour the migration SQL relies on: ALTER TABLE OWNER
        cascades to the SERIAL-linked sequence. If this ever changes (PG version
        upgrade, etc.), the prod migration would silently leave linked sequences
        misowned -- and this test would fail to warn us.
        """
        url, setup_conn, created = ephemeral_pg_with_halcyon_app
        tname = "_serial_cascade_check"
        created["tables"].append(tname)
        created["sequences"].append(f"{tname}_id_seq")
        with setup_conn.cursor() as cur:
            cur.execute(f"CREATE TABLE public.{tname} (id SERIAL PRIMARY KEY)")

        # Pre-state: both table and linked sequence owned by test.
        with setup_conn.cursor() as cur:
            cur.execute(
                "SELECT c.relname, c.relkind, r.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_authid r ON r.oid=c.relowner "
                "WHERE n.nspname='public' AND c.relname IN (%s, %s) "
                "ORDER BY c.relname",
                (tname, f"{tname}_id_seq"),
            )
            pre = {row[0]: row[2] for row in cur.fetchall()}
        assert pre == {tname: "test", f"{tname}_id_seq": "test"}

        result = apply_ownership_reconciliation(url)

        # The TABLE is altered explicitly; the linked SEQUENCE follows by cascade
        # (so it should NOT appear in sequences_altered -- discovery query returns
        # empty for it after the table cascade landed).
        assert tname in result["tables_altered"]
        assert f"{tname}_id_seq" not in result["sequences_altered"], (
            f"Linked sequence appeared in sequences_altered -- cascade may have "
            f"failed or the discovery-then-alter ordering changed: {result}"
        )

        # Post-state: BOTH table AND linked sequence owned by halcyon_app.
        with setup_conn.cursor() as cur:
            cur.execute(
                "SELECT c.relname, r.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_authid r ON r.oid=c.relowner "
                "WHERE n.nspname='public' AND c.relname IN (%s, %s) "
                "ORDER BY c.relname",
                (tname, f"{tname}_id_seq"),
            )
            post = {row[0]: row[1] for row in cur.fetchall()}
        assert post == {tname: "halcyon_app", f"{tname}_id_seq": "halcyon_app"}

    def test_reconciliation_is_idempotent(self, ephemeral_pg_with_halcyon_app):
        """Second call should be a no-op: zero tables/sequences altered."""
        url, setup_conn, created = ephemeral_pg_with_halcyon_app
        tname = "t_idempotent"
        created["tables"].append(tname)
        created["sequences"].append(f"{tname}_id_seq")
        self._create_tables_owned_by(setup_conn, "test", [tname])

        first = apply_ownership_reconciliation(url)
        assert tname in first["tables_altered"]

        second = apply_ownership_reconciliation(url)
        assert second["tables_altered"] == [], (
            f"Idempotency violation: second call altered {second['tables_altered']}"
        )
        assert second["sequences_altered"] == [], (
            f"Idempotency violation: second call altered sequences {second['sequences_altered']}"
        )
        assert second["grants_applied"] is True, (
            "GRANTs are unconditionally idempotent and should always be applied"
        )

    # NOTE: there is intentionally no test for the "halcyon_app role missing"
    # RuntimeError branch in apply_ownership_reconciliation. The guard remains
    # in the source as defensive code, but exercising it from a test requires
    # DROP ROLE halcyon_app, which fails after any earlier test in the same
    # session has GRANTed privileges to halcyon_app (default privileges /
    # cluster-wide dependencies that REASSIGN/DROP OWNED cannot clear). The
    # cost of test fragility outweighs the regression-lock value of testing
    # a five-line defensive raise.


# ---------------------------------------------------------------------------
# Test 2: live-PG policy check (skip-unless-flagged)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("ARCIS_LIVE_OWNERSHIP_CHECK") != "1",
    reason="Live-PG policy check; set ARCIS_LIVE_OWNERSHIP_CHECK=1 to run "
    "(also requires ARCIS_ALLOW_PROD_PG_IN_TESTS=1 to bypass conftest P0 guard).",
)
class TestLiveOwnershipPolicy:
    """On-demand policy assertion against the operator's runtime PG.

    Run this AFTER applying schema/migrations/2026-05-24_table_ownership_fix.sql
    to verify the live state is policy-compliant. Pre-migration this is RED
    (the 5 historical tables show owner=halcyon); post-migration this is GREEN.

    To run:
        $env:ARCIS_LIVE_OWNERSHIP_CHECK="1"
        $env:ARCIS_ALLOW_PROD_PG_IN_TESTS="1"
        $env:DATABASE_URL="postgresql://halcyon:***@localhost:5433/halcyon"
        pytest tests/test_table_ownership.py::TestLiveOwnershipPolicy -v
    """

    def _live_url(self) -> str:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            pytest.skip("DATABASE_URL not set; cannot probe live PG")
        return url

    def test_all_public_tables_owned_by_halcyon_app(self):
        """Policy: every table in public schema owned by halcyon_app."""
        url = self._live_url()
        conn = psycopg2.connect(url, connect_timeout=10)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename, tableowner FROM pg_tables "
                    "WHERE schemaname='public' AND tableowner != 'halcyon_app' "
                    "ORDER BY tablename"
                )
                misowned = cur.fetchall()
        finally:
            conn.close()
        assert misowned == [], (
            f"Live PG policy violation: {len(misowned)} public table(s) not "
            f"owned by halcyon_app: {misowned}. Apply "
            f"schema/migrations/2026-05-24_table_ownership_fix.sql as halcyon."
        )

    def test_all_public_sequences_owned_by_halcyon_app(self):
        """Policy: every sequence in public schema owned by halcyon_app.

        Uses pg_get_userbyid(relowner) instead of joining pg_authid because
        this test connects as halcyon_app (from operator's DATABASE_URL),
        and pg_authid SELECT requires superuser. pg_get_userbyid() is a
        public function that resolves owner OID -> rolname without exposing
        the underlying catalog table. The ephemeral test
        (test_reconciliation_transfers_standalone_sequence_to_halcyon_app)
        keeps the pg_authid join because IT connects as `test` superuser.
        Surfaced 2026-05-24 when initial live-policy run failed with
        "permission denied for table pg_authid" while the migration itself
        had succeeded -- a test query bug, not a policy violation.
        """
        url = self._live_url()
        conn = psycopg2.connect(url, connect_timeout=10)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT c.relname, pg_get_userbyid(c.relowner) AS rolname "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE c.relkind='S' AND n.nspname='public' "
                    "AND pg_get_userbyid(c.relowner) != 'halcyon_app' "
                    "ORDER BY c.relname"
                )
                misowned = cur.fetchall()
        finally:
            conn.close()
        assert misowned == [], (
            f"Live PG policy violation: {len(misowned)} public sequence(s) not "
            f"owned by halcyon_app: {misowned}."
        )
