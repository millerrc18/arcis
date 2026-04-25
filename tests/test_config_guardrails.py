"""T1.04 side-feature (F-3): CI guardrail for risk_governor.enabled regression.

A `risk_governor.enabled: false` config silently disables ALL 8 risk
checks (kill switch, daily loss, position size, max positions, sector,
correlation, volatility, duplicate). Approves every trade as long as
allocation > 0. The runtime alert in `src/risk/governor.py` covers
*detection*; this guardrail prevents accidental commit of a config
that flips it off.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_GLOB = str(REPO_ROOT / "config" / "settings*.yaml")


def _committed_settings_files() -> list[Path]:
    """Return all config/settings*.yaml files in the repo (excludes .bak)."""
    paths = []
    for raw in glob.glob(CONFIG_GLOB):
        p = Path(raw)
        # .bak files are not configs the loader reads; skip
        if p.suffix == ".bak":
            continue
        if p.name.endswith(".bak.yaml"):
            continue
        paths.append(p)
    return paths


def _is_governor_disabled(cfg: dict) -> bool:
    """Return True iff cfg has risk_governor.enabled: false (explicitly)."""
    rg = cfg.get("risk_governor")
    if not isinstance(rg, dict):
        return False
    if "enabled" not in rg:
        return False
    return rg["enabled"] is False


def test_no_committed_settings_yaml_disables_risk_governor():
    """No checked-in config/settings*.yaml may set risk_governor.enabled: false."""
    offenders = []
    for path in _committed_settings_files():
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        if _is_governor_disabled(cfg):
            offenders.append(str(path))
    assert not offenders, (
        "risk_governor.enabled: false detected in committed config(s): "
        + ", ".join(offenders)
        + ". This silently disables every risk check — restore enabled: true."
    )


def test_settings_yaml_glob_finds_at_least_one_real_config():
    """Sanity: the glob actually picks up the real configs (avoid silent skip).

    If this fails, the test above is vacuous and wouldn't catch a regression.
    """
    files = _committed_settings_files()
    assert files, f"No config/settings*.yaml files found via glob {CONFIG_GLOB}"
    names = {p.name for p in files}
    assert "settings.example.yaml" in names, (
        f"settings.example.yaml expected in {sorted(names)}"
    )


def test_synthetic_disabled_config_is_detected(tmp_path):
    """A synthetic settings file with enabled: false MUST be flagged."""
    synthetic = tmp_path / "settings.fake.yaml"
    synthetic.write_text(
        "risk_governor:\n  enabled: false\n",
        encoding="utf-8",
    )
    cfg = yaml.safe_load(synthetic.read_text(encoding="utf-8"))
    assert _is_governor_disabled(cfg) is True


def test_real_configs_pass_the_disabled_check():
    """The real committed configs must NOT be flagged (no false positives)."""
    for path in _committed_settings_files():
        with open(path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        assert not _is_governor_disabled(cfg), (
            f"{path} unexpectedly flagged as disabled — false positive in detector"
        )


def test_enabled_true_or_missing_is_not_flagged():
    """enabled: true and absent risk_governor section must both pass."""
    assert _is_governor_disabled({"risk_governor": {"enabled": True}}) is False
    assert _is_governor_disabled({"risk_governor": {}}) is False
    assert _is_governor_disabled({}) is False
