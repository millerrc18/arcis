"""Email subsystem — SMTP notifier + digest builder.

Public API:
    send_email: send a plain-text email via SMTP.
    digest_builder: module providing build_* digest functions.
"""

from src.email import digest_builder
from src.email.notifier import send_email

__all__ = ["digest_builder", "send_email"]
