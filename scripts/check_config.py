"""Config sync checker — compares settings.local.yaml against settings.example.yaml.

Shows missing sections, missing keys, and changed defaults. Run after any sprint
that adds new config sections to ensure your local config is up to date.

Usage:
    python scripts/check_config.py              # Show diff only
    python scripts/check_config.py --fix        # Add missing sections with defaults
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


def deep_diff(example: dict, local: dict, path: str = "") -> list[dict]:
    """Find keys in example that are missing from local."""
    diffs = []
    for key, value in example.items():
        full_path = f"{path}.{key}" if path else key
        if key not in local:
            diffs.append({
                "path": full_path,
                "type": "missing_section" if isinstance(value, dict) else "missing_key",
                "default_value": value,
            })
        elif isinstance(value, dict) and isinstance(local.get(key), dict):
            diffs.extend(deep_diff(value, local[key], full_path))
    return diffs


def main():
    parser = argparse.ArgumentParser(description="Check config sync")
    parser.add_argument("--fix", action="store_true",
                        help="Add missing sections with example defaults")
    args = parser.parse_args()

    config_dir = Path(__file__).resolve().parent.parent / "config"
    example_path = config_dir / "settings.example.yaml"
    local_path = config_dir / "settings.local.yaml"

    if not example_path.exists():
        print(f"❌ Example config not found: {example_path}")
        return

    if not local_path.exists():
        print(f"❌ Local config not found: {local_path}")
        print(f"   Copy the example: cp {example_path} {local_path}")
        return

    with open(example_path) as f:
        example = yaml.safe_load(f) or {}

    with open(local_path) as f:
        local = yaml.safe_load(f) or {}

    diffs = deep_diff(example, local)

    if not diffs:
        print("✅ Local config is in sync with example config.")
        return

    print(f"\n{'='*60}")
    print(f" CONFIG SYNC CHECK")
    print(f" Example: {example_path.name}")
    print(f" Local:   {local_path.name}")
    print(f"{'='*60}\n")

    missing_sections = [d for d in diffs if d["type"] == "missing_section"]
    missing_keys = [d for d in diffs if d["type"] == "missing_key"]

    if missing_sections:
        print(f"⚠️  MISSING SECTIONS ({len(missing_sections)}):\n")
        for d in missing_sections:
            print(f"  {d['path']}:")
            if isinstance(d["default_value"], dict):
                for k, v in d["default_value"].items():
                    print(f"    {k}: {v}")
            else:
                print(f"    {d['default_value']}")
            print()

    if missing_keys:
        print(f"⚠️  MISSING KEYS ({len(missing_keys)}):\n")
        for d in missing_keys:
            print(f"  {d['path']}: {d['default_value']}")
        print()

    print(f"Total: {len(diffs)} differences found.\n")

    if args.fix:
        print("Applying missing defaults to local config...\n")

        def deep_merge(base: dict, additions: dict) -> dict:
            """Merge additions into base without overwriting existing keys."""
            for key, value in additions.items():
                if key not in base:
                    base[key] = value
                    print(f"  Added: {key}")
                elif isinstance(value, dict) and isinstance(base.get(key), dict):
                    deep_merge(base[key], value)
            return base

        merged = deep_merge(local, example)

        # Write back
        with open(local_path, "w") as f:
            yaml.dump(merged, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)

        print(f"\n✅ Updated {local_path.name} with {len(diffs)} missing defaults.")
        print("   Review the file and update placeholder values (API keys, URLs, etc.)")
    else:
        print("Run with --fix to add missing sections with example defaults:")
        print(f"  python scripts/check_config.py --fix")


if __name__ == "__main__":
    main()
