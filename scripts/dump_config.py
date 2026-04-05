"""Dump settings.local.yaml with sensitive values redacted.

When to run:
    Ad-hoc for debugging configuration issues. Safe to paste the default
    (redacted) output into issues or chat. Use --raw only in a secure terminal.

What it reads:
    - config/settings.local.yaml (gitignored — contains secrets)

What it writes:
    - Nothing — stdout only (redacted by default)

Prerequisites:
    - PyYAML installed
    - config/settings.local.yaml must exist

Usage:
    python scripts/dump_config.py
    python scripts/dump_config.py --raw  # Show raw values (CAREFUL — contains secrets)
"""

import argparse
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

SENSITIVE_KEYS = {
    "api_key", "secret_key", "bot_token", "chat_id", "password",
    "database_url", "api_secret", "token", "secret", "smtp_password",
    "smtp_user", "from_email", "to_email", "fred_api_key",
    "anthropic_api_key", "finnhub_api_key", "openai_api_key",
    "polygon_api_key", "alpaca_api_key", "alpaca_secret_key",
}


def redact(data, raw=False):
    if raw:
        return data
    if isinstance(data, dict):
        return {k: redact(v, raw) if k.lower() not in SENSITIVE_KEYS
                else f"***REDACTED*** ({len(str(v))} chars)" if v else "(not set)"
                for k, v in data.items()}
    if isinstance(data, list):
        return [redact(item, raw) for item in data]
    return data


def main():
    parser = argparse.ArgumentParser(description="Dump config (redacted)")
    parser.add_argument("--raw", action="store_true", help="Show raw values (contains secrets!)")
    args = parser.parse_args()

    config_path = Path(__file__).resolve().parent.parent / "config" / "settings.local.yaml"

    if not config_path.exists():
        print(f"❌ {config_path} not found")
        return

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    redacted = redact(config, args.raw)
    print(yaml.dump(redacted, default_flow_style=False, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
