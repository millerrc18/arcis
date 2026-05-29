"""PR-E2 T43 — suite green-gate sentinel (DD-42 §46).

The green-gate policy: every test must PASS, or carry a skip reason in a
DD-42 allowlisted category. Zero failures; zero xpass.

Enforcement is split:

* ``xfail_strict = true`` (pytest.ini) turns any XPASS (an xfail that
  unexpectedly passes — a stale xfail) into a FAILURE.
* Test failures fail the run via pytest's own non-zero exit code.
* The ``pytest_sessionfinish`` hook in ``tests/conftest.py`` fails the run if
  any skip that ACTUALLY FIRED carries a reason outside the allowlist below.
  (Checking *fired* skips — not static markers — correctly ignores conditional
  skips whose gate isn't met in a given environment, e.g. an engine-aware skip
  that doesn't fire when PG is configured.)

DD-42 §46 categories:
  1. platform        — OS/arch-specific (Windows-only / POSIX-only / a tool
                       only present on one OS).
  2. optional-dep    — requires an uninstalled optional dependency or an
                       unavailable external fixture (package, binary, data file).
  3. engine-aware    — PG-vs-SQLite behavioural divergence (gated on whether a
                       real Postgres / TEST_DATABASE_URL is wired).
  4. tracked-upstream-bug (#N) — a real defect tracked by issue #N.
  5. integration(authoritative-coverage:<job>) — covered by a dedicated CI job.

The matcher accepts a reason that EITHER names a category keyword explicitly
OR uses an environment/dependency/engine gate phrase that maps unambiguously to
categories 1-3. It REJECTS (with precedence) the "broke / deferred / not in
scope / run-it-manually" anti-pattern this gate exists to ban — even if the
reason also contains an allow phrase.

This module owns the matcher and proves it non-vacuous. The end-to-end mutation
proof (inject a real unjustified skip; confirm the run goes RED) lives in the
commit that wired the conftest hook.
"""
from __future__ import annotations

import re

# Anti-pattern phrases — a skip whose reason matches ANY of these is REJECTED
# (checked FIRST, with precedence). These are the "it broke and wasn't the
# current scope / deferred / disabled / run-it-by-hand" reasons DD-42 §46 bans.
_ANTIPATTERN = re.compile(
    r"defer"
    r"|\bbroke\b|\bbroken\b"
    r"|todo|fixme|fix later|fix-later"
    r"|incomplete|unfinished|refile|\bwip\b|work in progress"
    r"|flaky|disabled|skipping for now|skip for now"
    r"|not in scope|out of scope|wasn'?t .*scope"
    r"|run (it )?(the )?cli manually|run .*manually|manual(ly)? run"
    r"|removed from this file|see comment above"
    r"|temporarily|for now\b",
    re.IGNORECASE,
)

# Allow phrases — map an environment/dependency/engine/platform gate to a
# DD-42 category. Specific enough that a vague punt does not match.
_ALLOW = re.compile(
    # explicit category keywords
    r"\bplatform\b"
    r"|\boptional-dep\b"
    r"|\bengine-aware\b"
    r"|tracked-upstream-bug\s*\(#\d+\)"
    r"|integration\(authoritative-coverage:[^)]+\)"
    # category 2 (optional-dep): missing package / binary / external fixture
    r"|not installed|not available|not present|not on path"
    r"|not provisioned|not reachable|not wired|no cached|fixture (un)?available"
    # category 3 (engine-aware): PG / engine gating
    r"|test_database_url|database_url|\bpostgres\b|postgresql|live pg|pg fixture"
    r"|cannot run\b.*\b(pg|postgres)|not postgres"
    # category 1 (platform): OS-specific tool / runner
    r"|not on this runner|on this runner|\bpwsh\b|\bnssm\b|windows-only|posix-only"
    r"|not authenticated",
    re.IGNORECASE,
)


def is_justified_skip(reason: str | None) -> bool:
    """Return True iff ``reason`` is a DD-42 §46 allowlisted skip.

    Anti-pattern phrases are rejected with precedence: a reason that smells of
    "broke / deferred / run-manually" is never justified, even if it also names
    an environment gate.
    """
    if not reason:
        return False
    if _ANTIPATTERN.search(reason):
        return False
    return bool(_ALLOW.search(reason))


# ── Non-vacuity self-tests ────────────────────────────────────────────────
# Accept a representative reason from each category / gate; reject the
# "broke, deferred" anti-pattern. If the regex is ever loosened to match
# everything, the reject cases fail (the matcher is provably non-vacuous).
import pytest

_ACCEPTED = [
    # explicit category keywords
    "Windows-only path semantics — platform skip",
    "eslint not installed in node_modules — DD-42 optional-dep skip",
    "PG-only ON CONFLICT upsert — engine-aware skip",
    "blocked by tracked-upstream-bug (#1234)",
    "integration(authoritative-coverage:lifecycle-full-gate): full scenario",
    # environment / dependency / engine gates that map to categories 1-3
    "scikit-learn not installed",
    "ib_async not installed",
    "nssm.exe not on PATH",
    "pwsh not available on this runner",
    "TEST_DATABASE_URL not set or not postgres://",
    "requires live PG fixture; TEST_DATABASE_URL not wired in this env",
    "no cached AAPL data — optional-dep skip",
]

_REJECTED = [
    "deferred: live-trade mock setup incomplete in Round 5b — refile",
    "deferred: see comment above",
    "integration-level — requires real data; run CLI manually",
    "pysentiment block removed from this file",
    "broke and wasn't in the current scope",
    "TODO: fix later",
    "skipping for now",
    "flaky, disabled",
    "temporarily skipped",
    "",
    None,
]


@pytest.mark.parametrize("reason", _ACCEPTED)
def test_allowlist_accepts_dd42_categories_and_env_gates(reason):
    assert is_justified_skip(reason), f"DD-42 reason rejected: {reason!r}"


@pytest.mark.parametrize("reason", _REJECTED)
def test_allowlist_rejects_antipattern_reasons(reason):
    assert not is_justified_skip(reason), f"anti-pattern reason accepted: {reason!r}"
