"""VRAM transition management between Ollama inference and PyTorch training.

Called by: scheduler.watch
Calls: config, llm.client, training.versioning
Owns tables: none
Config keys: llm
Tests: tests/test_vram_manager.py

The RTX 3060 has 12GB VRAM. Ollama inference uses ~5-6GB. PyTorch training
uses ~10-11GB. They CANNOT coexist. This manager handles clean transitions:

Evening (6:50 PM): Ollama -> unload -> verify VRAM clear -> launch training subprocess
Morning (5:15 AM): kill training -> verify VRAM clear -> reload Ollama -> warm up

Training runs as a SUBPROCESS so that process termination guarantees complete
VRAM release -- the OS reclaims all CUDA memory when the process exits.
"""

import logging
import os
import signal
import subprocess
import sys
import time

import requests

from src.config import load_config

logger = logging.getLogger(__name__)

# Common nvidia-smi locations on Windows
_NVIDIA_SMI_PATHS = [
    "nvidia-smi",  # On PATH
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
]


def _find_nvidia_smi() -> str | None:
    """Find nvidia-smi binary, searching common Windows locations."""
    for path in _NVIDIA_SMI_PATHS:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


class VRAMManager:
    """Manages GPU VRAM transitions between Ollama inference and PyTorch training."""

    def __init__(self):
        self._training_process: subprocess.Popen | None = None
        self._nvidia_smi = _find_nvidia_smi()
        if not self._nvidia_smi:
            logger.warning("[VRAM] nvidia-smi not found — VRAM monitoring unavailable")

    def get_active_model(self) -> str:
        """Get the active Ollama model name from versioning or config."""
        try:
            from src.training.versioning import get_active_model_name
            name = get_active_model_name()
            if name and name != "base":
                return name
        except Exception:
            pass
        config = load_config()
        return config.get("llm", {}).get("model", "qwen3:8b")

    def _get_ollama_base_url(self) -> str:
        """Get Ollama base URL from config."""
        config = load_config()
        return config.get("llm", {}).get("base_url", "http://localhost:11434")

    def get_vram_used_mb(self) -> int:
        """Get current GPU VRAM usage in MB via nvidia-smi."""
        if not self._nvidia_smi:
            return -1
        try:
            result = subprocess.run(
                [self._nvidia_smi, "--query-gpu=memory.used",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                # May have multiple GPUs; take first line
                return int(result.stdout.strip().split("\n")[0].strip())
        except (subprocess.TimeoutExpired, ValueError, OSError) as e:
            logger.warning("[VRAM] nvidia-smi failed: %s", e)
        return -1

    def _unload_ollama(self) -> bool:
        """Unload the active Ollama model from VRAM."""
        model = self.get_active_model()
        base_url = self._get_ollama_base_url()
        try:
            resp = requests.post(
                f"{base_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info("[VRAM] Unloaded model %s", model)
                return True
            logger.warning("[VRAM] Unload returned status %d", resp.status_code)
        except Exception as e:
            logger.warning("[VRAM] Unload request failed: %s", e)
        return False

    def _reload_ollama(self) -> bool:
        """Reload the Ollama model into VRAM with warm-up."""
        model = self.get_active_model()
        base_url = self._get_ollama_base_url()
        try:
            resp = requests.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "keep_alive": "18h",
                    "prompt": "System health check. Respond with OK.",
                    "stream": False,
                },
                timeout=120,
            )
            if resp.status_code == 200:
                logger.info("[VRAM] Reloaded model %s", model)
                return True
            logger.warning("[VRAM] Reload returned status %d", resp.status_code)
        except Exception as e:
            logger.warning("[VRAM] Reload request failed: %s", e)
        return False

    def _wait_for_vram_clear(self, threshold_mb: int = 1500,
                             timeout_seconds: int = 30) -> bool:
        """Wait until VRAM usage drops below threshold."""
        if not self._nvidia_smi:
            # No nvidia-smi — assume success after a short wait
            time.sleep(3)
            return True

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            used = self.get_vram_used_mb()
            if 0 <= used < threshold_mb:
                logger.info("[VRAM] VRAM clear: %dMB used", used)
                return True
            time.sleep(2)

        used = self.get_vram_used_mb()
        logger.warning("[VRAM] VRAM not clear after %ds: %dMB used",
                       timeout_seconds, used)
        return False

    def handoff_to_training(self) -> bool:
        """Unload Ollama model, verify VRAM clear, prepare for training.

        Returns True if VRAM is ready for training subprocess.
        """
        logger.info("[VRAM] Beginning handoff to training...")
        used_before = self.get_vram_used_mb()

        # Step 1: Unload Ollama
        if not self._unload_ollama():
            logger.warning("[VRAM] Initial unload failed, retrying...")
            time.sleep(3)
            if not self._unload_ollama():
                logger.error("[VRAM] Unload failed after retry — aborting handoff")
                return False

        time.sleep(3)

        # Step 2: Verify VRAM clear
        if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=30):
            # Retry unload
            logger.warning("[VRAM] VRAM not clear, retrying unload...")
            self._unload_ollama()
            time.sleep(3)
            if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=30):
                # Kill Ollama process entirely to free VRAM
                logger.warning("[VRAM] Killing Ollama process to reclaim VRAM...")
                try:
                    import platform
                    if platform.system() == "Windows":
                        subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                                       capture_output=True, timeout=10)
                    else:
                        subprocess.run(["pkill", "-f", "ollama"],
                                       capture_output=True, timeout=10)
                    time.sleep(5)
                except Exception as kill_err:
                    logger.warning("[VRAM] Failed to kill Ollama: %s", kill_err)
                if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=15):
                    logger.error("[VRAM] Handoff to training FAILED — VRAM not clear even after killing Ollama")
                    return False

        used_after = self.get_vram_used_mb()
        logger.info("[VRAM] Handoff to training: Ollama unloaded, VRAM at %dMB "
                    "(was %dMB)", used_after, used_before)
        return True

    def handoff_to_inference(self) -> bool:
        """Kill training subprocess, verify VRAM clear, reload Ollama.

        Returns True if Ollama is loaded and warm.
        """
        logger.info("[VRAM] Beginning handoff to inference...")

        # Step 1: Kill training subprocess if running
        if self._training_process and self._training_process.poll() is None:
            logger.info("[VRAM] Terminating training subprocess (pid=%d)...",
                        self._training_process.pid)
            self._training_process.terminate()
            try:
                self._training_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning("[VRAM] Training subprocess did not terminate, killing...")
                self._training_process.kill()
                self._training_process.wait(timeout=10)

        time.sleep(3)

        # Step 2: Verify VRAM clear
        if not self._wait_for_vram_clear(threshold_mb=1500, timeout_seconds=30):
            logger.warning("[VRAM] VRAM not clear after killing training process")
            # Continue anyway — Ollama may still be able to load

        # Step 3: Ensure Ollama process is running, then reload model
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
        except Exception:
            pass  # May already be running

        if not self._reload_ollama():
            logger.error("[VRAM] Handoff to inference FAILED — Ollama reload failed")
            return False

        # Step 4: Warm-up verification
        try:
            from src.llm.client import is_llm_available
            if not is_llm_available():
                logger.warning("[VRAM] Ollama loaded but health check failed")
                return False
        except Exception:
            pass

        used = self.get_vram_used_mb()
        logger.info("[VRAM] Handoff to inference: Ollama loaded, warm-up complete, "
                    "VRAM at %dMB", used)
        return True

    def launch_training_subprocess(self, task_name: str,
                                   script_args: list[str]) -> subprocess.Popen:
        """Launch a training task as a subprocess for clean VRAM isolation.

        When the subprocess exits, ALL CUDA memory is freed by the OS.
        """
        logger.info("[VRAM] Launching training subprocess: %s", task_name)
        proc = subprocess.Popen(
            [sys.executable] + script_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._training_process = proc
        return proc

    @property
    def training_running(self) -> bool:
        """Check if the training subprocess is currently running."""
        if self._training_process is None:
            return False
        return self._training_process.poll() is None
