"""Ollama-on-GPU1 lifecycle owner (dual-GPU workload separation, T1).

Called by: NSSM service ArcisOllamaWatchdog (python -m src.scheduler.ollama_watchdog)
Calls: config, scheduler.metrics, notifications.telegram
Owns tables: none
Owns files: none
Config keys: llm.base_url, llm.expected_model_tag
Tests: tests/test_ollama_watchdog.py

This process is the SINGLE owner of the Ollama inference server, pinned to GPU1.
Per the 2026-05-22 dual-GPU separation design, training runs isolated on GPU0
(RTX 3090) so the prior shared-GPU VRAM handoff failures cannot recur.

Single-owner pre-flight (MAJOR-3): before launching, terminate or adopt any
pre-existing Ollama so exactly ONE owner results. All process kills are
PID-scoped — never /im name-kill, never by name, never a non-Ollama PID.

MAJOR-4 (steady-state empty-store invariant): GET /api/version returns 200
even against an EMPTY model store. So BOTH the adopt branch AND post-launch
MUST additionally assert the store is non-empty via GET /api/tags and confirm
the expected model tag (default halcyon-v1, configurable) is present.
If absent: emit gpu_health_ollama_ok=False with detail and fail loud via safe_send.

Why OLLAMA_MODELS: under LocalSystem ~/.ollama resolves to
C:\\Windows\\system32\\config\\systemprofile\\.ollama (empty). Set it in
_launch()'s env as defense-in-depth (the NSSM env is T2's job).

Ollama exe resolution: OLLAMA_EXE / OLLAMA_PATH env override > PATH >
per-user install glob C:\\Users\\*\\AppData\\Local\\Programs\\Ollama\\ollama.exe.
Under LocalSystem %LOCALAPPDATA% points at the systemprofile, so the glob
(not %LOCALAPPDATA% expansion) finds the operator's per-user install.
"""

import glob
import json
import logging
import os
import platform
import shutil
import subprocess
import time

import requests

from src.config import load_config
from src.notifications.telegram import safe_send
from src.scheduler.metrics import upsert_daily_metric

logger = logging.getLogger(__name__)

_OLLAMA_USER_GLOB = r"C:\Users\*\AppData\Local\Programs\Ollama\ollama.exe"
_OLLAMA_MODELS_PATH = r"C:\Users\mille\.ollama\models"
# v0.36.52: track current production model. The fallback chain in __init__
# prefers (a) explicit param, (b) config llm.expected_model_tag, (c) config
# llm.model — so the watchdog stays in sync with the LLM client's actual
# model. This default is the last-resort floor when no config is reachable.
_DEFAULT_MODEL_TAG = "arcis:v1.0.0"
_HEALTH_POLL_SEC = 30
_STARTUP_GRACE_SEC = 8


def resolve_ollama_exe() -> str | None:
    """Resolve the ollama executable.

    Order:
      1. OLLAMA_EXE / OLLAMA_PATH env override
      2. PATH lookup (shutil.which)
      3. per-user install glob C:\\Users\\*\\AppData\\Local\\Programs\\Ollama\\ollama.exe

    Returns None if nothing resolves.
    """
    override = os.environ.get("OLLAMA_EXE") or os.environ.get("OLLAMA_PATH")
    if override:
        is_valid = os.path.isfile(override)
        if platform.system() == "Windows":
            is_valid = is_valid and override.lower().endswith("ollama.exe")
        if is_valid:
            return override
        logger.warning("[OLLAMA-WD] OLLAMA_EXE/OLLAMA_PATH override %r is not a valid exe — falling through", override)
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in glob.glob(_OLLAMA_USER_GLOB):
        if os.path.isfile(candidate):
            return candidate
    return None


class OllamaWatchdog:
    """Single-owner lifecycle manager for the GPU1-pinned Ollama server."""

    def __init__(self, base_url: str | None = None, expected_model_tag: str | None = None):
        # v0.36.52: decouple base_url and expected_model_tag resolution. The
        # original code gated BOTH lookups on `base_url is None`, so callers
        # that passed base_url explicitly silently fell through to the default
        # tag. Now each param falls back to config independently.
        config = load_config() if (base_url is None or expected_model_tag is None) else None
        if base_url is None:
            base_url = (config or {}).get("llm", {}).get("base_url", "http://localhost:11434")
        if expected_model_tag is None:
            # Fallback chain: explicit override -> llm.expected_model_tag ->
            # llm.model (DRY with the LLM client) -> hardcoded default.
            llm_cfg = (config or {}).get("llm", {})
            expected_model_tag = (
                llm_cfg.get("expected_model_tag")
                or llm_cfg.get("model")
                or _DEFAULT_MODEL_TAG
            )
        self.base_url = base_url.rstrip("/")
        self.expected_model_tag = expected_model_tag or _DEFAULT_MODEL_TAG
        self._exe = resolve_ollama_exe()
        self._launched_pid: int | None = None

    # ── version health ────────────────────────────────────────────────────────

    def _is_version_ok(self) -> bool:
        """True if Ollama answers /api/version at the configured base_url."""
        try:
            resp = requests.get(f"{self.base_url}/api/version", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    # ── model-store health (MAJOR-4) ──────────────────────────────────────────

    def _store_has_model(self) -> bool:
        """True if /api/tags lists the expected model tag.

        GET /api/version 200 is a necessary but NOT sufficient health signal:
        Ollama serves /api/version even when the model store is empty (the
        v0.36.47 silent-failure shape). This method checks /api/tags and
        confirms the expected tag (default halcyon-v1) is present.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = data.get("models", [])
            if not models:
                return False
            tag = self.expected_model_tag
            return any(m.get("name", "") == tag for m in models)
        except Exception:
            return False

    def _is_healthy(self) -> tuple[bool, str]:
        """Full health check: /api/version AND non-empty store with expected tag.

        Returns (ok, detail) where detail is one of:
          'ok', 'version_failed', 'empty_model_store', 'missing_model_tag'
        """
        if not self._is_version_ok():
            return False, "version_failed"
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False, "tags_request_failed"
            data = resp.json()
            models = data.get("models", [])
            if not models:
                return False, "empty_model_store"
            tag = self.expected_model_tag
            if not any(m.get("name", "") == tag for m in models):
                return False, "missing_model_tag"
        except Exception as exc:
            logger.warning("[OLLAMA-WD] /api/tags check failed: %s", exc)
            return False, "tags_check_error"
        return True, "ok"

    # ── process discovery ─────────────────────────────────────────────────────

    def _ollama_pids(self) -> list[int]:
        """PIDs of running ollama processes (Windows tasklist / POSIX pgrep).

        Returns a deduped list. Used to PID-terminate residual owners — never
        used to drive a name-kill.
        """
        pids: list[int] = []
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/fo", "csv", "/nh", "/fi", "imagename eq ollama.exe"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.strip().splitlines():
                    parts = [p.strip().strip('"') for p in line.split(",")]
                    if len(parts) >= 2:
                        try:
                            pids.append(int(parts[1]))
                        except ValueError:
                            continue
            else:
                result = subprocess.run(
                    ["pgrep", "-x", "ollama"],
                    capture_output=True, text=True, timeout=10,
                )
                for line in result.stdout.strip().splitlines():
                    try:
                        pids.append(int(line.strip()))
                    except ValueError:
                        continue
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("[OLLAMA-WD] process discovery failed: %s", exc)
        seen: set[int] = set()
        unique: list[int] = []
        for pid in pids:
            if pid not in seen:
                seen.add(pid)
                unique.append(pid)
        return unique

    def _graceful_stop(self) -> None:
        """Attempt `ollama stop` to release the model gracefully before kill."""
        if not self._exe:
            return
        try:
            subprocess.run(
                [self._exe, "stop"],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.info("[OLLAMA-WD] 'ollama stop' unavailable (%s)", exc)

    def _kill_pid(self, pid: int) -> None:
        """Terminate a SPECIFIC pid. PID-scoped only — never /im, never by name.

        Windows escalation: taskkill /f /t /pid -> PowerShell Stop-Process.
        POSIX: kill -9.
        """
        pid = int(pid)
        if pid <= 0:
            return
        if platform.system() != "Windows":
            try:
                subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
            return
        try:
            result = subprocess.run(
                ["taskkill", "/f", "/t", "/pid", str(pid)],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("[OLLAMA-WD] killed Ollama PID %d via taskkill", pid)
                return
        except subprocess.TimeoutExpired:
            logger.warning("[OLLAMA-WD] taskkill /pid %d timed out, escalating", pid)
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Id {pid} -Force -ErrorAction Stop"],
                capture_output=True, timeout=10,
            )
            logger.info("[OLLAMA-WD] killed Ollama PID %d via Stop-Process", pid)
        except subprocess.TimeoutExpired:
            logger.warning("[OLLAMA-WD] Stop-Process %d timed out — kill exhausted", pid)
        except OSError as exc:
            logger.warning("[OLLAMA-WD] Stop-Process %d OSError — kill exhausted: %s", pid, exc)

    # ── single-owner pre-flight ───────────────────────────────────────────────

    def preflight(self) -> None:
        """Ensure no foreign Ollama owner survives before we launch.

        If an instance is already healthy, callers ADOPT it (see ensure_owner)
        and never reach here. When reached, any residual Ollama is gracefully
        stopped then PID-terminated so exactly one owner results.
        """
        self._graceful_stop()
        residual = self._ollama_pids()
        for pid in residual:
            logger.info("[OLLAMA-WD] terminating residual Ollama PID %d", pid)
            self._kill_pid(pid)

    # ── launch ────────────────────────────────────────────────────────────────

    def _launch(self) -> None:
        """Launch `ollama serve` pinned to GPU1.

        Env includes CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID,
        OLLAMA_NUM_PARALLEL=2, and OLLAMA_MODELS (defense-in-depth against
        LocalSystem resolving ~/.ollama to the systemprofile path).
        """
        exe = self._exe or "ollama"
        env = dict(os.environ)
        env["CUDA_VISIBLE_DEVICES"] = "1"
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        env["OLLAMA_NUM_PARALLEL"] = "2"
        env["OLLAMA_MODELS"] = _OLLAMA_MODELS_PATH
        kwargs: dict = {"env": env}
        if platform.system() == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        proc = subprocess.Popen([exe, "serve"], **kwargs)
        self._launched_pid = proc.pid
        logger.info("[OLLAMA-WD] launched 'ollama serve' on GPU1 (pid=%s)", proc.pid)

    # ── ensure single owner ───────────────────────────────────────────────────

    def _emit_unhealthy(self, detail: str) -> None:
        """Emit unhealthy metric and loud Telegram alert."""
        payload = json.dumps({"gpu": "1", "detail": detail})
        try:
            upsert_daily_metric("gpu_health_ollama_ok", 0.0, payload)
        except Exception as exc:
            logger.debug("[OLLAMA-WD] metric emit failed: %s", exc)
        logger.warning("[OLLAMA-WD] Ollama unhealthy: %s", detail)
        try:
            # v0.36.52: notify_system_event(event, detail) — was passing
            # message= (rejected as unexpected kwarg). severity is consumed by
            # safe_send itself (popped at telegram.py:1609), not forwarded.
            safe_send(
                "system_event",
                event="GPU1-OLLAMA unhealthy",
                detail=detail,
                severity="critical",
                force=True,
            )
        except Exception as exc:
            logger.warning("[OLLAMA-WD] safe_send failed: %s", exc)

    def _emit_healthy(self) -> None:
        """Emit healthy metric."""
        payload = json.dumps({"gpu": "1", "detail": "ok"})
        try:
            upsert_daily_metric("gpu_health_ollama_ok", 1.0, payload)
        except Exception as exc:
            logger.debug("[OLLAMA-WD] metric emit failed: %s", exc)

    def ensure_owner(self) -> bool:
        """Guarantee exactly one Ollama owner, GPU1-pinned.

        Adopt branch: /api/version 200 AND /api/tags has expected tag => adopt.
        Launch branch: any check fails => preflight + launch.

        MAJOR-4: /api/version alone is insufficient — must also check /api/tags.

        Returns True if a healthy existing instance was ADOPTED (no relaunch),
        False if a fresh instance was launched after pre-flight cleanup.
        """
        ok, detail = self._is_healthy()
        if ok:
            logger.info("[OLLAMA-WD] healthy Ollama with model store — adopting")
            self._emit_healthy()
            return True

        # Pre-launch: only log for version/tags failures (Ollama isn't up yet, loud emit
        # would be noise); always _emit_unhealthy after launch since Ollama SHOULD be up.
        if detail in ("empty_model_store", "missing_model_tag"):
            self._emit_unhealthy(detail)
        elif detail != "ok":
            logger.info("[OLLAMA-WD] Ollama not healthy (%s) — will (re)launch", detail)

        self.preflight()
        self._launch()
        time.sleep(_STARTUP_GRACE_SEC)

        ok2, detail2 = self._is_healthy()
        if not ok2:
            self._emit_unhealthy(detail2)
        else:
            self._emit_healthy()
        return False

    # ── shutdown ──────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """On service stop, terminate the Ollama PID we launched (if any)."""
        if self._launched_pid is not None:
            logger.info(
                "[OLLAMA-WD] service stop — terminating launched PID %d",
                self._launched_pid,
            )
            self._kill_pid(self._launched_pid)
            self._launched_pid = None

    # ── health loop ───────────────────────────────────────────────────────────

    def run(self) -> None:
        """Run the watchdog: ensure owner, then poll health every 30s.

        Each loop iteration performs the full MAJOR-4 invariant check
        (/api/version AND /api/tags with expected model tag).
        """
        self.ensure_owner()
        try:
            while True:
                time.sleep(_HEALTH_POLL_SEC)
                ok, detail = self._is_healthy()
                if ok:
                    self._emit_healthy()
                else:
                    self._emit_unhealthy(detail)
                    logger.warning("[OLLAMA-WD] Ollama unhealthy (%s) — restarting", detail)
                    self.ensure_owner()
        except KeyboardInterrupt:
            self.shutdown()


def main() -> None:
    """Entrypoint for `python -m src.scheduler.ollama_watchdog`."""
    logging.basicConfig(level=logging.INFO)
    OllamaWatchdog().run()


if __name__ == "__main__":
    main()
