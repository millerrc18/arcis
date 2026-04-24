"""Single source of truth for the app version (#631 item 15).

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

# Update when cutting a release. Latest CHANGELOG header: v0.26.0.
VERSION = "v0.26.0"
