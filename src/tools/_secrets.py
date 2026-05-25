"""Content-based secret scanner for the tool suite.

Purpose: Detect high-confidence credential patterns (and high-entropy
         fallback) in arbitrary text bodies before they touch log files,
         PR comment bodies, or any external surface.

Called by: src.tools.pr_comments (PRComments.post — blocks on PRCommentLeakError)
Calls:     re (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/tools/test_secrets.py  (T2's responsibility)
"""

from __future__ import annotations

import re


# ── Known-prefix patterns (ordered: more-specific first) ──────────────

_BODY_SECRET_PATTERNS = [
    re.compile(r'\bghp_[A-Za-z0-9]{20,}\b'),                          # GitHub personal access token
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),                  # GitHub fine-grained PAT
    re.compile(r'\bgho_[A-Za-z0-9]{20,}\b'),                          # GitHub OAuth
    re.compile(r'\bghs_[A-Za-z0-9]{36,}\b'),                          # GitHub server-to-server (DA3)
    re.compile(r'\bghu_[A-Za-z0-9]{36,}\b'),                          # GitHub user-to-server (DA3)
    re.compile(r'\bglpat-[A-Za-z0-9_\-]{20,}\b'),                     # GitLab PAT (DA3)
    re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'),                           # OpenAI / Anthropic
    re.compile(r'\bsk_live_[A-Za-z0-9]{24,}\b'),                      # Stripe live secret (DA3)
    re.compile(r'\bpk_live_[A-Za-z0-9]{24,}\b'),                      # Stripe live publishable (DA3)
    re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}\b'),                  # Slack tokens
    re.compile(r'\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]{20,}\b'),  # JWT 3-segment (DA3)
    re.compile(r'(?i)\b(password|api[_-]?key|secret|token)\s*[=:]\s*[^\s]{6,}'),     # password=xyz shapes
    re.compile(r'(?i)\bauthorization:\s*bearer\s+[^\s]{10,}'),        # Bearer headers
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),                 # PEM key blocks
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),                              # AWS access key id
]

_HIGH_ENTROPY_PATTERN = re.compile(r'\b[A-Za-z0-9+/]{40,}\b')


# ── Public API ────────────────────────────────────────────────────────


def detect_secret_in_text(body: str) -> tuple[bool, str, str]:
    """Scan `body` for credential patterns and return a 3-tuple.

    Returns:
        (is_leak, redacted_preview, kind)

        is_leak:          True if any pattern matched.
        redacted_preview: Copy of `body` with matched spans replaced by
                          '***REDACTED***'. Equals `body` unchanged when
                          is_leak is False.
        kind:             One of 'known_prefix', 'high_entropy_unknown', 'none'.

    Scan order:
        1. All 15 known-prefix patterns are applied (all matches redacted).
        2. High-entropy fallback is ALWAYS applied next — defense-in-depth
           per T1 Security review: a body containing BOTH a known-prefix
           token AND a separate high-entropy secret previously had only
           the known token redacted (the secondary secret leaked via
           audit-log preview). Always running the fallback redacts both.
        3. `kind` label reflects whether ANY known-prefix matched (takes
           precedence in the label since known-prefix is HIGH-confidence);
           else 'high_entropy_unknown'; else 'none'.
    """
    redacted = body
    known_hit = False
    for pat in _BODY_SECRET_PATTERNS:
        if pat.search(redacted):
            known_hit = True
            redacted = pat.sub('***REDACTED***', redacted)
    # ALWAYS run the high-entropy fallback (T1 Security cycle-1 fix).
    high_entropy_hit = bool(_HIGH_ENTROPY_PATTERN.search(redacted))
    if high_entropy_hit:
        redacted = _HIGH_ENTROPY_PATTERN.sub('***REDACTED***', redacted)
    if known_hit:
        return True, redacted, 'known_prefix'
    if high_entropy_hit:
        return True, redacted, 'high_entropy_unknown'
    return False, body, 'none'
