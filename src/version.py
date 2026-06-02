"""Single source of truth for the app version (#631 item 15).

Called by: api.cloud_routes.core, services.system_service
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_version.py

Pre-fix the version "v0.17.2" was hardcoded in three places (cloud_routes/
core.py, services/system_service.py, frontend/Layout.jsx fallback) while
the actual deployed version was v0.24.0-alpha1 — confusing operators reading
the dashboard who saw a header version that didn't match the What's New
section.

The frontend reads `status.version` from /api/system/status; that endpoint
now reads VERSION from this module. The frontend fallback constant has
also been updated to match. Bump VERSION here when cutting a release;
update CHANGELOG.md alongside.
"""

# Update when cutting a release. Latest CHANGELOG header: v0.36.82
# (#129 forward-fix: the v0.36.81 PG self-heal halted the watch loop on the
# split-ownership prod schema — ALTER/INDEX on tables owned by role 'halcyon'
# raised "must be owner" → fatal "cannot continue" → startup crash-loop. The
# self-heal now SKIPS that benign InsufficientPrivilege like startup_checks,
# instead of halting. Prod was rolled back to v0.36.80 during the incident.)
# Versioning policy: see docs/versioning-policy.md.
VERSION = "v0.36.82"
