# Email Setup Guide

This guide explains how to configure SMTP email delivery for the Systematic Equity Research so trade packets, watchlists, and recaps reach Ryan's inbox.

## Recommended: Gmail with an App Password

1. **Enable 2-Step Verification** on the Google account you want to send from.
   - Go to <https://myaccount.google.com/security> and turn on 2-Step Verification.
2. **Create an App Password.**
   - Go to <https://myaccount.google.com/apppasswords>.
   - Select **Mail** as the app and **Other** as the device (name it something like "arcis").
   - Click **Generate**. Google will show a 16-character password — copy it.
3. **Fill in `config/settings.local.yaml`** (see below for the template).
   - `smtp_server`: `smtp.gmail.com`
   - `smtp_port`: `587`
   - `use_tls`: `true`
   - `username`: your full Gmail address
   - `password`: the 16-character App Password from step 2
   - `from_address`: same Gmail address
   - `to_address`: Ryan's work email

## Alternative: Any SMTP Provider

Any provider that supports SMTP with STARTTLS on port 587 (or SSL on port 465) will work. Use the host, port, and credentials your provider gives you and fill them into `settings.local.yaml` the same way.

## Filling in `settings.local.yaml`

Copy the email section from `config/settings.example.yaml` into `config/settings.local.yaml` and replace the placeholder values:

```yaml
email:
  smtp_server: smtp.gmail.com
  smtp_port: 587
  use_tls: true
  username: your.address@gmail.com
  password: abcd efgh ijkl mnop   # App Password — no quotes needed
  from_address: your.address@gmail.com
  to_address: ryan@workdomain.com
```

> **Never commit `settings.local.yaml`.** It contains credentials. The file is already listed in `.gitignore`, but double-check before pushing.

## Verifying Your Setup

Once the `send-test-email` CLI command is available (coming in the next milestone), run it to confirm delivery end-to-end:

```bash
python -m src.main send-test-email
```

If the test email does not arrive, check:
- App Password is correct (no extra spaces).
- 2-Step Verification is enabled (required for App Passwords).
- Your provider allows SMTP access (some orgs disable it).
- Firewall or VPN is not blocking outbound port 587.
