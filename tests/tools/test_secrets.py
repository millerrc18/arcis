"""Tests for src.tools._secrets — credential-pattern scanner.

Per spec §2.3 (DA3 extended pattern coverage) + T1 cycle-1 Security fix
multi-match contract. 17 cases (a)-(q): 15 known-prefix positives
(covering all _BODY_SECRET_PATTERNS), 1 high-entropy AWS-shape baseline,
2 clean baselines, and 1 multi-match case (q) that locks the T1 Security
fix contract (both known-prefix AND high-entropy regions must be redacted).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ── Parametrized cases (a)-(p) ─────────────────────────────────────────
#
# Tuple layout: (body, expected_is_leak, expected_kind, expect_body_in_redacted)
# expect_body_in_redacted: False = the body must NOT appear verbatim in redacted_preview
#                           True  = the body SHOULD appear verbatim (clean text baseline)

_CASES = [
    # (a) GitHub personal access token — ghp_ + 20+ alphanumeric
    pytest.param(
        "ghp_abcdefghij1234567890",
        True,
        "known_prefix",
        False,
        id="(a) github_personal_access_token",
    ),
    # (b) GitHub fine-grained PAT — github_pat_ + 20+ alphanumeric/underscore
    pytest.param(
        "github_pat_AB12345CD67890EF12345",
        True,
        "known_prefix",
        False,
        id="(b) github_fine_grained_pat",
    ),
    # (c) OpenAI / Anthropic key — sk- + 20+ alphanumeric
    pytest.param(
        "sk-abc123def456ghi789jkl0",
        True,
        "known_prefix",
        False,
        id="(c) openai_anthropic_key",
    ),
    # (d) password=xyz shape — matches password= sentinel regex
    pytest.param(
        "password=hunter2supersecret",
        True,
        "known_prefix",
        False,
        id="(d) password_equals_shape",
    ),
    # (e) Authorization: Bearer header
    pytest.param(
        "Authorization: Bearer xyzABC123token456",
        True,
        "known_prefix",
        False,
        id="(e) authorization_bearer_header",
    ),
    # (f) PEM private key block — exact sentinel string
    pytest.param(
        "-----BEGIN RSA PRIVATE KEY-----",
        True,
        "known_prefix",
        False,
        id="(f) pem_private_key_block",
    ),
    # (g) AWS access key ID — AKIA + 16 uppercase alphanumeric
    pytest.param(
        "AKIA1234567890ABCDEF",
        True,
        "known_prefix",
        False,
        id="(g) aws_access_key_id",
    ),
    # (h) GitHub server-to-server token — ghs_ + 36+ alphanumeric (DA3)
    # Verify-by-mutation: comment out the ghs_ regex in _BODY_SECRET_PATTERNS → this test fails.
    pytest.param(
        "ghs_" + "a" * 36,
        True,
        "known_prefix",
        False,
        id="(h) github_server_to_server_da3",
    ),
    # (i) GitHub user-to-server token — ghu_ + 36+ alphanumeric (DA3)
    pytest.param(
        "ghu_" + "b" * 36,
        True,
        "known_prefix",
        False,
        id="(i) github_user_to_server_da3",
    ),
    # (j) GitLab PAT — glpat- + 20+ alphanumeric/hyphen/underscore (DA3)
    pytest.param(
        "glpat-" + "X" * 20,
        True,
        "known_prefix",
        False,
        id="(j) gitlab_pat_da3",
    ),
    # (k) Stripe live secret key — sk_live_ + 24+ alphanumeric (DA3)
    pytest.param(
        "sk_live_" + "Y" * 24,
        True,
        "known_prefix",
        False,
        id="(k) stripe_live_secret_da3",
    ),
    # (l) Stripe live publishable key — pk_live_ + 24+ alphanumeric (DA3)
    pytest.param(
        "pk_live_" + "Z" * 24,
        True,
        "known_prefix",
        False,
        id="(l) stripe_live_publishable_da3",
    ),
    # (m) JWT 3-segment — eyJ...eyJ...signature (DA3)
    pytest.param(
        "eyJabcdef.eyJxyz0123.signaturepart1234567890123",
        True,
        "known_prefix",
        False,
        id="(m) jwt_three_segment_da3",
    ),
    # (n) AWS secret access key shape — 40 chars, mixed case + slash, no known prefix
    # → classified as high_entropy_unknown (no matching known-prefix pattern)
    # Verify-by-mutation: comment out _HIGH_ENTROPY_PATTERN → this test fails.
    pytest.param(
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        True,
        "high_entropy_unknown",
        False,
        id="(n) aws_secret_access_key_high_entropy",
    ),
    # (o) Clean text — no credential patterns, body returned unchanged
    pytest.param(
        "looks good to me",
        False,
        "none",
        True,
        id="(o) clean_text_baseline",
    ),
    # (p) Empty string — no patterns possible, body returned unchanged
    pytest.param(
        "",
        False,
        "none",
        True,
        id="(p) empty_string_baseline",
    ),
]


@pytest.mark.parametrize("body,expected_is_leak,expected_kind,expect_body_in_redacted", _CASES)
def test_detect_secret_parametrized(body, expected_is_leak, expected_kind, expect_body_in_redacted):
    """Parametrized cases (a)-(p): known-prefix positives, high-entropy, and clean baselines."""
    from src.tools._secrets import detect_secret_in_text

    is_leak, redacted_preview, kind = detect_secret_in_text(body)

    assert is_leak == expected_is_leak, f"is_leak mismatch for body {body!r}"
    assert kind == expected_kind, f"kind mismatch for body {body!r}: got {kind!r}"

    if expect_body_in_redacted:
        # Clean baseline: body must appear verbatim in redacted_preview (unchanged)
        assert body in redacted_preview, (
            f"clean body {body!r} must appear unchanged in redacted_preview"
        )
    else:
        # Leaked: the original token must NOT appear verbatim
        assert body not in redacted_preview, (
            f"leaked body {body!r} must not appear verbatim in redacted_preview"
        )
        assert "***REDACTED***" in redacted_preview, (
            f"redacted_preview must contain '***REDACTED***' for body {body!r}"
        )


# ── Case (q): multi-match — locks T1 cycle-1 Security fix contract ──────
#
# Verify-by-mutation: revert detect_secret_in_text to early-return-on-known-hit
# (pre-cycle-1-fix behavior) → high-entropy substring remains in redacted_preview
# → this test fails.


def test_detect_secret_multi_match_both_regions_redacted():
    """Case (q): body containing a known-prefix token AND a separate high-entropy secret.

    Both regions MUST be redacted. Kind label stays 'known_prefix' because the
    HIGH-confidence known-prefix match takes precedence in the label, but the
    high-entropy fallback MUST have fired too (defense-in-depth, T1 Security fix).
    """
    from src.tools._secrets import detect_secret_in_text

    known_token = "ghp_abcdefghij1234567890"
    high_entropy_token = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    body = f"{known_token} and also {high_entropy_token}"

    is_leak, redacted_preview, kind = detect_secret_in_text(body)

    assert is_leak is True, "multi-match body must be flagged as a leak"
    assert kind == "known_prefix", (
        "kind must be 'known_prefix' when any known-prefix pattern matched "
        f"(got {kind!r})"
    )
    # Known-prefix token must be redacted
    assert known_token not in redacted_preview, (
        f"known-prefix token {known_token!r} must not appear in redacted_preview"
    )
    # High-entropy token must ALSO be redacted (T1 Security fix contract)
    assert high_entropy_token not in redacted_preview, (
        f"high-entropy token {high_entropy_token!r} must not appear in redacted_preview "
        "(T1 cycle-1 Security fix: always run high-entropy fallback)"
    )
    # At least 2 REDACTED markers — one for each token
    assert redacted_preview.count("***REDACTED***") >= 2, (
        f"expected >= 2 '***REDACTED***' markers, got "
        f"{redacted_preview.count('***REDACTED***')} in {redacted_preview!r}"
    )


# ── Config validation smoke tests ─────────────────────────────────────────


def test_paths_watchdog_heartbeat_in_config():
    """Config smoke: cfg.paths.watchdog_heartbeat resolves to watchdog.txt (DD-10 / FB2)."""
    from src.tools._config import load_arcis_config

    cfg = load_arcis_config()

    assert cfg.paths.watchdog_heartbeat.name == "watchdog.txt", (
        f"expected 'watchdog.txt', got {cfg.paths.watchdog_heartbeat.name!r}"
    )
    assert isinstance(cfg.paths.watchdog_heartbeat, Path), (
        "watchdog_heartbeat must be a pathlib.Path instance"
    )


def test_watchdog_heartbeat_in_yaml():
    """YAML round-trip: 'watchdog_heartbeat' key present and points to correct path."""
    repo_root = Path(__file__).resolve().parents[2]
    yaml_path = repo_root / "config" / "arcis_config.yaml"

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "watchdog_heartbeat" in data["paths"], (
        "arcis_config.yaml[paths] must contain 'watchdog_heartbeat'"
    )
    assert "C:/arcis/halcyon-lab/data/watchdog.txt" in str(data["paths"]["watchdog_heartbeat"]), (
        f"watchdog_heartbeat must be 'C:/arcis/halcyon-lab/data/watchdog.txt', "
        f"got {data['paths']['watchdog_heartbeat']!r}"
    )
