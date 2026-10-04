#!/usr/bin/env python3
"""Recompute the SHA-256 of config/incumbent_v1.yaml to verify the freeze.

Usage: python tools/verify_incumbent_freeze.py

Exits 0 if the computed hash matches the frozen hash in the YAML.
Exits 1 with a diagnostic if it does not.
"""
import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = REPO_ROOT / "config" / "incumbent_v1.yaml"


def main() -> int:
    text = YAML_PATH.read_text()
    m = re.search(r"^\s*sha256:\s*([0-9a-f]{64})\s*$", text, re.M)
    if not m:
        print("FAIL: no frozen sha256 found in config/incumbent_v1.yaml")
        return 1
    frozen = m.group(1)

    # Hash the normalized content (excluding the sha256 line itself,
    # mirroring how the freeze was computed).
    lines = [ln for ln in text.split("\n") if not re.match(r"^\s*sha256:\s*[0-9a-f]{64}\s*$", ln)]
    normalized = "\n".join(lines)
    computed = hashlib.sha256(normalized.encode()).hexdigest()

    if computed == frozen:
        print(f"OK: incumbent_v1.yaml freeze verified ({computed[:12]}...)")
        return 0
    print(f"FAIL: hash mismatch\n  frozen:   {frozen}\n  computed: {computed}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
