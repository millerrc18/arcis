"""Tests for email notifier hardening (Sprint 4 T11.5 Group B).

Module: tests.email.test_notifier
Purpose: Unit tests for C4/C5/C17/N1 fixes in src.email.notifier.
Called by: pytest
Owns tables: none
Config keys: none
"""
import importlib
import os
import smtplib
import sys
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_EMAIL_CFG = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "use_tls": True,
    "username": "user@example.com",
    "from_address": "user@example.com",
    "to_address": "dest@example.com",
}


def _make_config(extra_email=None):
    cfg = dict(BASE_EMAIL_CFG)
    if extra_email:
        cfg.update(extra_email)
    return {"email": cfg}


# ---------------------------------------------------------------------------
# Test 1 (C5): cc_addresses=None must not raise TypeError
# ---------------------------------------------------------------------------

class TestCcAddressesNone:
    def test_cc_none_does_not_raise(self):
        """cc_addresses=None (from YAML omission) must not cause TypeError."""
        config = _make_config({"cc_addresses": None})

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.return_value = {}  # {} = all accepted (no failures)

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            result = send_email("Subject", "Body")

        assert result is True


# ---------------------------------------------------------------------------
# Test 2 (C4): EMAIL_PASSWORD required; YAML fallback removed;
#              startup warning emitted when YAML key non-empty
# ---------------------------------------------------------------------------

class TestEmailPasswordEnvRequired:
    def test_yaml_password_not_used_when_env_absent(self):
        """When EMAIL_PASSWORD env var absent, function returns False (incomplete config)."""
        config = _make_config({"password": "yaml-secret"})

        env_without_email_pw = {k: v for k, v in os.environ.items() if k != "EMAIL_PASSWORD"}

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, env_without_email_pw, clear=True):
            import importlib
            import src.email.notifier as mod
            importlib.reload(mod)
            result = mod.send_email("Subject", "Body")

        assert result is False

    def test_yaml_password_warns_when_nonempty(self):
        """When YAML password key is non-empty, a warning is logged even if env var present."""
        config = _make_config({"password": "yaml-secret"})

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.return_value = {}

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "env-secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance), \
             patch("src.email.notifier.logger") as mock_logger:
            from src.email.notifier import send_email
            send_email("Subject", "Body")

        # A warning must have been emitted about the YAML password key
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("password" in w.lower() or "yaml" in w.lower() for w in warning_calls), \
            f"Expected a warning about YAML password key, got: {warning_calls}"


# ---------------------------------------------------------------------------
# Test 3 (C17): SMTP returns False → telegram fallback via safe_send
# ---------------------------------------------------------------------------

class TestSmtpFalseTriggersTegramFallback:
    def test_smtp_false_invokes_safe_send(self):
        """When sendmail returns {recipient: (code, msg)}, safe_send is called as fallback."""
        config = _make_config()

        # sendmail returning a dict with any entry means failures
        smtp_failures = {"dest@example.com": (550, b"User unknown")}
        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.return_value = smtp_failures

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance), \
             patch("src.email.notifier.safe_send") as mock_safe_send:
            from src.email.notifier import send_email
            result = send_email("Alert: test", "Body content here")

        mock_safe_send.assert_called_once()
        call_kwargs = mock_safe_send.call_args
        # Check subject is passed
        args, kwargs = call_kwargs
        # safe_send("system_event", message=...) or similar
        assert "Alert: test" in str(args) + str(kwargs)
        assert result is False


# ---------------------------------------------------------------------------
# Test 4: ConnectionRefusedError caught, returns False
# ---------------------------------------------------------------------------

class TestConnectionRefusedCaught:
    def test_connection_refused_returns_false(self):
        """ConnectionRefusedError from SMTP must be caught and return False."""
        config = _make_config()

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", side_effect=ConnectionRefusedError("Connection refused")):
            from src.email.notifier import send_email
            result = send_email("Subject", "Body")

        assert result is False


# ---------------------------------------------------------------------------
# Test 5: TLS path — starttls() called when port 587
# ---------------------------------------------------------------------------

class TestTlsPath:
    def test_starttls_called_when_use_tls_true(self):
        """When use_tls=True (port 587), server.starttls() must be called."""
        config = _make_config({"use_tls": True, "smtp_port": 587})

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.return_value = {}

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            send_email("Subject", "Body")

        mock_smtp_instance.starttls.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6: Envelope — To/Cc/Subject correctly populated
# ---------------------------------------------------------------------------

class TestEnvelopePopulation:
    def test_envelope_to_cc_subject(self):
        """MIMEText envelope must include correct To, Cc, Subject headers."""
        config = _make_config({"cc_addresses": ["cc1@example.com", "cc2@example.com"]})

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.return_value = {}
        captured_msg = {}

        def capture_sendmail(from_addr, to_addrs, msg_str):
            captured_msg["to_addrs"] = to_addrs
            captured_msg["msg_str"] = msg_str
            return {}

        mock_smtp_instance.sendmail.side_effect = capture_sendmail

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            send_email("My Subject", "Body text")

        assert "dest@example.com" in captured_msg["to_addrs"]
        assert "cc1@example.com" in captured_msg["to_addrs"]
        assert "cc2@example.com" in captured_msg["to_addrs"]
        assert "My Subject" in captured_msg["msg_str"]
        assert "cc1@example.com" in captured_msg["msg_str"]


# ---------------------------------------------------------------------------
# Test N1: digest_builder re-exported from src.email
# ---------------------------------------------------------------------------

class TestDigestBuilderReexport:
    def test_digest_builder_importable_from_src_email(self):
        """digest_builder must be importable from src.email (N1 re-export)."""
        import src.email as email_pkg
        assert hasattr(email_pkg, "digest_builder"), \
            "src.email must re-export 'digest_builder' module attribute"
