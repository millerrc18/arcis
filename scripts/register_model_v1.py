#!/usr/bin/env python3
"""Register the current halcyonlatest model as halcyon-v1.0.0 and update config.

When to run:
    One-time, to bootstrap semver model versioning. After this initial
    registration, the Saturday retrain pipeline auto-increments
    (v1.1.0, v1.2.0, etc.) and updates config automatically.

What it reads:
    - model_versions table (checks if already registered)
    - config/settings.local.yaml (to update the active model name)

What it writes:
    - Updates model_versions table (rename or insert)
    - Creates an Ollama tag via `ollama cp`
    - Updates config/settings.local.yaml model field

Prerequisites:
    - Ollama running with the halcyonlatest model loaded
    - Database at src/config.DB_PATH with model_versions table

Usage:
    python scripts/register_model_v1.py
    python scripts/register_model_v1.py --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH
from src.training.versioning import (
    get_active_model_version,
    get_next_semver,
    register_model_version,
    update_config_model,
    init_training_tables,
)


def main():
    parser = argparse.ArgumentParser(description="Register current model with semver")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--version", default=None, help="Override version name (default: auto)")
    args = parser.parse_args()

    db_path = DB_PATH
    config_path = "config/settings.local.yaml"
    init_training_tables(db_path)

    # Check current state
    active = get_active_model_version(db_path)
    if active and active["version_name"].startswith("halcyon-v1."):
        print(f"Active model already registered with semver: {active['version_name']}")
        print(f"  Created: {active['created_at']}")
        print(f"  Examples: {active.get('training_examples_count', 'unknown')}")
        return

    version_name = args.version or "halcyon-v1.0.0"

    if active:
        # Rename existing registration (e.g. "halcyonlatest" → "halcyon-v1.0.0")
        print(f"Current active model: {active['version_name']} (will rename to {version_name})")
    else:
        print(f"Current active model: None (will register as {version_name})")

    next_ver = get_next_semver(db_path)
    print(f"Next retrain will be: halcyon-v1.1.0")

    if args.dry_run:
        print("\n(dry run — no changes made)")
        return

    if active:
        # Rename in DB
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE model_versions SET version_name = ? WHERE version_id = ?",
                (version_name, active["version_id"]),
            )
        print(f"\n✅ Renamed {active['version_name']} → {version_name} in model_versions")
    else:
        # Register new
        vid = register_model_version(
            version_name=version_name,
            examples_count=969,
            synthetic_count=0,
            outcome_count=0,
            model_file_path="halcyonlatest",
            db_path=db_path,
        )
        print(f"\n✅ Registered {version_name} in model_versions (id={vid})")

    # Create Ollama tag
    try:
        result = subprocess.run(
            ["ollama", "cp", "halcyonlatest", version_name],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            print(f"✅ Created Ollama tag: {version_name}")
        else:
            print(f"⚠️  Ollama tag failed: {result.stderr.strip()}")
            print(f"   Run manually: ollama cp halcyonlatest {version_name}")
    except FileNotFoundError:
        print(f"⚠️  Ollama not found. Run manually: ollama cp halcyonlatest {version_name}")

    # Update config
    config = Path(config_path)
    if config.exists():
        updated = update_config_model(version_name, config_path)
        if updated:
            print(f"✅ Updated {config_path} → model: {version_name}")
        else:
            print(f"⚠️  Could not update {config_path} — update model field manually")
    else:
        print(f"⚠️  {config_path} not found — update model field manually")

    print(f"\nDone. Dashboard will show '{version_name}' after restart.")
    print(f"Next Saturday retrain will auto-create halcyon-v1.1.0.")


if __name__ == "__main__":
    main()
