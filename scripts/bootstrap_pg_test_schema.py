"""Bootstrap PostgreSQL test schema from src/schema/registry.

Called by: .github/workflows/pg-tests.yml in CI
Calls: src.schema.postgres.create_all_tables
Owns tables: none (idempotently materializes registry-defined tables)
Config keys: TEST_DATABASE_URL (env)
Tests: none (CI infrastructure script; first green run is the verification)

Prepares a freshly-spun `postgres:16-alpine` sidecar for the test suite by
invoking the registry-driven DDL generator against $TEST_DATABASE_URL. The
operation is idempotent — repeat invocations are no-ops on existing tables /
columns / indexes — so CI re-runs after retry-on-failure are safe.

Exits non-zero with a clear stderr message when TEST_DATABASE_URL is absent;
the workflow YAML always sets this env var, so a missing value indicates a
mis-configured CI job, not a coding error.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.schema.postgres import create_all_tables  # noqa: E402


def main() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        print("TEST_DATABASE_URL not set; aborting", file=sys.stderr)
        sys.exit(1)
    create_all_tables(url)
    print("PG test schema bootstrapped from registry")


if __name__ == "__main__":
    main()
