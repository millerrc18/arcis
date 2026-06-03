"""Shared exception types for the clean-slate wipe (#95).

CleanSlateAbort   — a hard ABORT before any irreversible mutation (Phase 0
                    reconciliation drift, watch-loop running, broker not flat).
                    Carries a machine-readable `code` (e.g. ABORT_FK_DRIFT).
BackupVerifyError — a backup/verify REFUSE (Phase 1); also carries a `code`
                    (REFUSE_BACKUP / REFUSE_SCHEMA_DRIFT / REFUSE_VERIFY).

Both subclass RuntimeError. They are distinct from src.tools._safety.SafetyError
(which @safe_op classifies for log-dedup) — these fire INSIDE the wrapped
function, on the read path, before the mutation the decorators gate.
"""

from __future__ import annotations


class CleanSlateAbort(RuntimeError):
    """Hard abort before any irreversible mutation. `code` is the audit verdict."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


class BackupVerifyError(RuntimeError):
    """Backup/verify failure → REFUSE the TRUNCATE. `code` is the audit verdict."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)
