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

# Update when cutting a release. Latest CHANGELOG header: v0.36.70 (#110
# arcis:strategy skill ships — research-desk capstone with 4 verbs).
# Versioning policy: see docs/versioning-policy.md.
VERSION = "v0.36.70"
