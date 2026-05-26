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

        import src.email.notifier as mod
        importlib.reload(mod)
        mod._yaml_password_warning_emitted = False

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "env-secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance), \
             patch("src.email.notifier.logger") as mock_logger:
            mod.send_email("Subject", "Body")

        # A warning must have been emitted about the YAML password key
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("password" in w.lower() or "yaml" in w.lower() for w in warning_calls), \
            f"Expected a warning about YAML password key, got: {warning_calls}"

    def test_yaml_password_warning_is_once_per_process(self):
        """Repeated sends should not spam the same YAML password warning."""
        config = _make_config({"password": "yaml-secret"})

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.return_value = {}

        import src.email.notifier as mod
        importlib.reload(mod)
        mod._yaml_password_warning_emitted = False

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "env-secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance), \
             patch("src.email.notifier.logger") as mock_logger:
            mod.send_email("Subject 1", "Body")
            mod.send_email("Subject 2", "Body")

        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        yaml_warnings = [
            w for w in warning_calls
            if "password" in w.lower() or "yaml" in w.lower()
        ]
        assert len(yaml_warnings) == 1


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


# ---------------------------------------------------------------------------
# Spec #115 Section 4.1 (DD-03 revised + DA-CRIT-2 fix):
#   send_email html_body + attachments support
# ---------------------------------------------------------------------------

class TestSendEmailHtmlAndAttachments:
    """Tests for new keyword-only params html_body + attachments on send_email."""

    def _capture_msg(self):
        """Build an SMTP mock that captures the (from_addr, to_addrs, msg_str)."""
        captured = {}

        def capture_sendmail(from_addr, to_addrs, msg_str):
            captured["from_addr"] = from_addr
            captured["to_addrs"] = to_addrs
            captured["msg_str"] = msg_str
            return {}

        mock_smtp_instance = MagicMock()
        mock_smtp_instance.sendmail.side_effect = capture_sendmail
        return mock_smtp_instance, captured

    def test_send_email_with_html_body_builds_multipart_alternative(self):
        """html_body provided + no attachments → MIMEMultipart('alternative') with plain + html parts."""
        config = _make_config()
        mock_smtp_instance, captured = self._capture_msg()

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            result = send_email("Subject", "plain text body", html_body="<p>HI</p>")

        assert result is True
        msg_str = captured["msg_str"]
        # Outer envelope is multipart/alternative
        assert "multipart/alternative" in msg_str.lower()
        # Both content types appear in the parts
        assert "text/plain" in msg_str.lower()
        assert "text/html" in msg_str.lower()
        # Round-trip via email.parser to verify structure
        import email.parser
        parsed = email.parser.Parser().parsestr(msg_str)
        assert parsed.is_multipart()
        assert parsed.get_content_subtype() == "alternative"
        parts = parsed.get_payload()
        subtypes = sorted(p.get_content_subtype() for p in parts)
        assert subtypes == ["html", "plain"]

    def test_send_email_html_param_default_none_uses_mimetext(self):
        """Backward-compat: when html_body=None and attachments=None, MIMEText behavior is preserved."""
        config = _make_config()
        mock_smtp_instance, captured = self._capture_msg()

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            result = send_email("Subject", "plain body only")

        assert result is True
        msg_str = captured["msg_str"]
        # Should NOT be multipart — plain MIMEText
        assert "multipart" not in msg_str.lower()
        import email.parser
        parsed = email.parser.Parser().parsestr(msg_str)
        assert not parsed.is_multipart()
        assert parsed.get_content_type() == "text/plain"

    def test_send_email_with_attachment_builds_mixed_multipart(self):
        """attachments provided → MIMEMultipart('mixed') with attachment having Content-Disposition."""
        config = _make_config()
        mock_smtp_instance, captured = self._capture_msg()

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            result = send_email(
                "Subject",
                "plain body",
                attachments=[("overflow.txt", b"row1\nrow2")],
            )

        assert result is True
        msg_str = captured["msg_str"]
        assert "multipart/mixed" in msg_str.lower()
        import email.parser
        parsed = email.parser.Parser().parsestr(msg_str)
        assert parsed.is_multipart()
        assert parsed.get_content_subtype() == "mixed"

        # Find attachment part
        parts = parsed.get_payload()
        attachment_parts = [p for p in parts if p.get("Content-Disposition", "").startswith("attachment")]
        assert len(attachment_parts) == 1
        att = attachment_parts[0]
        disposition = att.get("Content-Disposition", "")
        assert "attachment" in disposition
        assert "overflow.txt" in disposition

    def test_send_email_html_plus_attachment_nests_alternative_inside_mixed(self):
        """When BOTH html_body and attachments provided → 'mixed' outer wrapping 'alternative' inner."""
        config = _make_config()
        mock_smtp_instance, captured = self._capture_msg()

        with patch("src.email.notifier.load_config", return_value=config), \
             patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=False), \
             patch("smtplib.SMTP", return_value=mock_smtp_instance):
            from src.email.notifier import send_email
            result = send_email(
                "Subject",
                "plain body",
                html_body="<p>HTML body</p>",
                attachments=[("data.csv", b"a,b,c\n1,2,3")],
            )

        assert result is True
        msg_str = captured["msg_str"]
        import email.parser
        parsed = email.parser.Parser().parsestr(msg_str)
        assert parsed.is_multipart()
        assert parsed.get_content_subtype() == "mixed"

        parts = parsed.get_payload()
        # One alternative subpart + one attachment subpart
        alt_parts = [p for p in parts if p.is_multipart() and p.get_content_subtype() == "alternative"]
        att_parts = [p for p in parts if p.get("Content-Disposition", "").startswith("attachment")]
        assert len(alt_parts) == 1, f"Expected 1 alternative subpart, got: {[p.get_content_type() for p in parts]}"
        assert len(att_parts) == 1

        # The alternative inside should have both plain + html
        inner = alt_parts[0]
        inner_subtypes = sorted(p.get_content_subtype() for p in inner.get_payload())
        assert inner_subtypes == ["html", "plain"]

        # Attachment filename preserved
        assert "data.csv" in att_parts[0].get("Content-Disposition", "")

    def test_build_message_helper_exposes_multipart(self):
        """build_message helper must build MIME structures without sending."""
        from src.email.notifier import build_message

        # Case 1: plain only → MIMEText
        msg = build_message("Sub", "plain")
        assert not msg.is_multipart()
        assert msg.get_content_type() == "text/plain"
        assert msg["Subject"] == "Sub"

        # Case 2: plain + html → alternative
        msg = build_message("Sub", "plain", html_body="<p>html</p>")
        assert msg.is_multipart()
        assert msg.get_content_subtype() == "alternative"
        subtypes = sorted(p.get_content_subtype() for p in msg.get_payload())
        assert subtypes == ["html", "plain"]

        # Case 3: plain + attachment → mixed
        msg = build_message("Sub", "plain", attachments=[("x.txt", b"data")])
        assert msg.is_multipart()
        assert msg.get_content_subtype() == "mixed"

        # Case 4: plain + html + attachment → mixed wrapping alternative
        msg = build_message(
            "Sub",
            "plain",
            html_body="<p>html</p>",
            attachments=[("x.txt", b"data")],
        )
        assert msg.is_multipart()
        assert msg.get_content_subtype() == "mixed"
        parts = msg.get_payload()
        alt_parts = [p for p in parts if p.is_multipart() and p.get_content_subtype() == "alternative"]
        att_parts = [p for p in parts if p.get("Content-Disposition", "").startswith("attachment")]
        assert len(alt_parts) == 1
        assert len(att_parts) == 1
