"""VRAM transition management between Ollama inference and PyTorch training.

Called by: scheduler.watch
Calls: config, llm.client, training.versioning
Owns tables: none
Owns files: logs/training_*.log (subprocess output)
Config keys: llm
Tests: tests/test_vram_manager.py

The RTX 3060 has 12GB VRAM. Ollama inference uses ~5-6GB. PyTorch training
uses ~10-11GB. They CANNOT coexist. This manager handles clean transitions:

Evening (6:50 PM): Ollama -> unload -> verify VRAM clear -> launch training subprocess
Morning (5:15 AM): kill training -> verify VRAM clear -> reload Ollama -> warm up

Training subprocess output is redirected to logs/training_{task}.log to avoid
pipe buffer deadlocks. Inference handoff escalates aggressively if VRAM
stays high: kill Ollama processes, clear CUDA cache, then fail if still stuck.

Training runs as a SUBPROCESS so that process termination guarantees complete
VRAM release -- the OS reclaims all CUDA memory when the process exits.
"""

import logging
import os
import platform
import shutil
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


def _find_ollama() -> str | None:
    """Find the ollama executable.

    v0.36.36: the NSSM service runs without the operator's user PATH, so
    `subprocess(["ollama", ...])` raised `[WinError 2] cannot find the file` on
    the failed-handoff Ollama restart (2026-05-19 18:54). Fall back to the
    default Windows install location under %LOCALAPPDATA%.
    """
    found = shutil.which("ollama")
    if found:
        return found
    candidates = []
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        candidates.append(
            os.path.join(localappdata, "Programs", "Ollama", "ollama.exe")
        )
    candidates.append(r"C:\Program Files\Ollama\ollama.exe")
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


class VRAMManager:
    """Manages GPU VRAM transitions between Ollama inference and PyTorch training."""

    def __init__(self):
        self._training_process: subprocess.Popen | None = None
        self._nvidia_smi = _find_nvidia_smi()
        if not self._nvidia_smi:
            logger.warning("[VRAM] nvidia-smi not found — VRAM monitoring unavailable")
        # Resolve ollama up front so service-context PATH gaps don't break the
        # restart path (v0.36.36). Fall back to the bare name (PATH lookup at
        # call time) when not found at a known location.
        self._ollama = _find_ollama() or "ollama"

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

        # Try graceful stop first (releases VRAM more reliably than keep_alive=0)
        try:
            import subprocess as _sp
            result = _sp.run(
                [self._ollama, "stop", model],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                logger.info("[VRAM] Graceful stop succeeded for %s", model)
                return True
            logger.info("[VRAM] 'ollama stop' returned %d, falling back to keep_alive=0", result.returncode)
        except Exception as e:
            logger.info("[VRAM] 'ollama stop' unavailable (%s), falling back to keep_alive=0", e)

        # Fallback: keep_alive=0 API call (existing code)
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

    def _model_pids_on_gpu(self, name_substr: str | None = None,
                           pid: int | None = None) -> list[int]:
        """PIDs of model processes still holding GPU compute memory.

        Matches a compute-app by process-name substring (case-insensitive,
        e.g. "ollama") and/or an exact PID.

        v0.36.35: judging "VRAM released" by total free memory is wrong on a
        desktop host where GPU[0] is the display GPU — the Windows compositor
        (dwm.exe) + browsers/IDEs hold an irreducible ~2.6GB baseline that
        exceeds any sane threshold. The model's release is provable only by the
        absence of its PROCESS from nvidia-smi --query-compute-apps.
        """
        matches: list[int] = []
        for proc in self._get_gpu_processes():
            if name_substr and name_substr.lower() in proc["name"].lower():
                matches.append(proc["pid"])
            elif pid is not None and proc["pid"] == pid:
                matches.append(proc["pid"])
        return matches

    def _wait_for_model_release(self, *, name_substr: str | None = None,
                                pid: int | None = None,
                                timeout_seconds: int = 30) -> bool:
        """Wait until the named/PID model process no longer holds GPU memory.

        Per-process replacement for the total-VRAM-threshold gate (v0.36.35);
        immune to desktop VRAM on a shared display GPU. Mirrors
        `_wait_for_vram_clear`'s no-nvidia-smi shortcut.
        """
        if not self._nvidia_smi:
            time.sleep(3)
            return True
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not self._model_pids_on_gpu(name_substr=name_substr, pid=pid):
                logger.info("[VRAM] model released GPU (name=%s pid=%s)",
                            name_substr, pid)
                return True
            time.sleep(2)
        # Final check after the deadline — the process may have exited between
        # the last poll and the timeout (and guarantees a check even if the
        # loop body never ran).
        holding = self._model_pids_on_gpu(name_substr=name_substr, pid=pid)
        if not holding:
            logger.info("[VRAM] model released GPU (name=%s pid=%s)", name_substr, pid)
            return True
        logger.warning("[VRAM] model still holding GPU after %ds: pids=%s",
                       timeout_seconds, holding)
        return False

    def _get_gpu_processes(self) -> list[dict]:
        """Return list of processes currently using GPU compute.

        Each entry: {"pid": int, "name": str, "used_mb": int | None}.
        `used_mb` is None when nvidia-smi reports the memory column as
        `[N/A]` — common on Windows for processes whose per-process VRAM
        accounting isn't surfaced via WDDM (Ollama's `ollama.exe` is a known
        case on RTX 30-series systems).

        Returns [] if nvidia-smi is unavailable, hangs, or finds nothing.

        v0.36.29 fix: pre-fix this method skipped rows where `int(used_memory)`
        raised ValueError, which dropped Ollama from results on the operator's
        RTX 3090+3060 system. The PID-based kill path then never fired and the
        2-night VRAM cascade returned. Lesson: identification doesn't require
        the memory column — only the PID and process name do.
        """
        if not self._nvidia_smi:
            return []
        try:
            result = subprocess.run(
                [self._nvidia_smi,
                 "--query-compute-apps=pid,process_name,used_memory",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
            procs: list[dict] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 3:
                    continue
                # PID must be a real int — drops header rows + truly malformed lines.
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                # Memory column may be "[N/A]" — treat as unknown rather than skip.
                try:
                    used_mb: int | None = int(parts[2])
                except ValueError:
                    used_mb = None
                procs.append({
                    "pid": pid,
                    "name": parts[1],
                    "used_mb": used_mb,
                })
            return procs
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("[VRAM] nvidia-smi --query-compute-apps failed: %s", e)
            return []

    def _kill_pid(self, pid: int) -> bool:
        """Aggressively kill a process by PID via escalating fallbacks.

        Windows escalation order:
          1. taskkill /f /t /pid <PID>  -- kills process tree
          2. PowerShell Stop-Process -Id <PID> -Force
          3. wmic process where ProcessId=<PID> delete

        Each step has a 10s timeout. Returns True on the first success.

        Linux fallback: kill -9 <PID>.

        Pre-v0.36.24 the code used `taskkill /f /im <name>` which hangs when
        an Ollama runner is wedged in a CUDA syscall. PID-based killing
        with escalation through multiple Windows tools survives that case.
        """
        if platform.system() != "Windows":
            try:
                subprocess.run(["kill", "-9", str(pid)],
                               capture_output=True, timeout=5)
                return True
            except (subprocess.TimeoutExpired, OSError):
                return False

        # Strategy 1: taskkill /f /t /pid
        try:
            result = subprocess.run(
                ["taskkill", "/f", "/t", "/pid", str(pid)],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("[VRAM] Killed PID %d via taskkill", pid)
                return True
            logger.info("[VRAM] taskkill /pid %d returned %d, escalating to PowerShell",
                        pid, result.returncode)
        except subprocess.TimeoutExpired:
            logger.warning("[VRAM] taskkill /pid %d timed out, escalating to PowerShell", pid)

        # Strategy 2: PowerShell Stop-Process -Force
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Id {pid} -Force -ErrorAction Stop"],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("[VRAM] Killed PID %d via Stop-Process", pid)
                return True
            logger.info("[VRAM] Stop-Process %d returned %d, escalating to wmic",
                        pid, result.returncode)
        except subprocess.TimeoutExpired:
            logger.warning("[VRAM] Stop-Process %d timed out, escalating to wmic", pid)

        # Strategy 3: wmic delete
        try:
            result = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={pid}", "delete"],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info("[VRAM] Killed PID %d via wmic", pid)
                return True
            logger.warning("[VRAM] All kill methods failed for PID %d", pid)
        except subprocess.TimeoutExpired:
            logger.warning("[VRAM] wmic kill PID %d timed out — all methods exhausted", pid)

        return False

    def _kill_ollama_processes(self) -> None:
        """Force-kill all Ollama processes to reclaim VRAM.

        v0.36.24: prefers PID-based discovery via nvidia-smi --query-compute-apps
        so we hit the actual VRAM-holding process. The legacy `/im`-based kill
        fails when an Ollama runner is wedged in a CUDA syscall (observed
        2026-05-18 evening + 2026-05-19 morning handoffs; both timed out the
        taskkill /im at 10s and left VRAM held).

        Falls back to the `/im`-based path when no Ollama-named process owns
        GPU memory (covers nvidia-smi missing / no GPU apps / Ollama crashed
        without freeing the runner).
        """
        try:
            if platform.system() != "Windows":
                subprocess.run(["pkill", "-f", "ollama"],
                               capture_output=True, timeout=10)
                time.sleep(5)
                return

            # Strategy A: PID-based kill of GPU-holding Ollama processes.
            # v0.36.29: dedupe by PID — multi-GPU systems (e.g. operator's
            # RTX 3090 + RTX 3060) list the same Ollama process once per GPU.
            gpu_procs = self._get_gpu_processes()
            ollama_procs = [p for p in gpu_procs if "ollama" in p["name"].lower()]
            seen_pids: set[int] = set()
            unique_ollama = []
            for p in ollama_procs:
                if p["pid"] not in seen_pids:
                    seen_pids.add(p["pid"])
                    unique_ollama.append(p)
            if unique_ollama:
                for proc in unique_ollama:
                    mem_str = (
                        f"{proc['used_mb']}MB" if proc["used_mb"] is not None
                        else "memory=[N/A]"
                    )
                    logger.info("[VRAM] Killing Ollama PID %d (%s, %s)",
                                proc["pid"], proc["name"], mem_str)
                    self._kill_pid(proc["pid"])
                time.sleep(3)

                # Verify: if no ollama-named PID still holds VRAM, we're done.
                # Dedupe again — same multi-GPU consideration.
                _still = self._get_gpu_processes()
                still_holding_pids = {
                    p["pid"] for p in _still if "ollama" in p["name"].lower()
                }
                if not still_holding_pids:
                    return
                # v0.36.44: the PID-based kill (taskkill /pid → Stop-Process → wmic)
                # ran but VRAM is STILL held — the Ollama runner is wedged in a CUDA
                # syscall (a process stuck in a kernel-mode GPU driver call can't be
                # terminated until the call returns). The legacy `/im` kill can't
                # terminate it either; it just blocks for its full timeout (observed
                # 2026-05-20 18:54: `/im` timed out at 10s, VRAM still held). Skip it
                # and return — the caller's retry + torch.cuda.empty_cache loop waits
                # for the driver to reclaim VRAM once the syscall unwinds.
                logger.warning(
                    "[VRAM] Ollama still holding VRAM after PID-based kill — likely "
                    "wedged in a CUDA syscall; skipping the /im fallback (it cannot "
                    "kill a wedged process and would just block). Caller will retry."
                )
                return

            # Strategy B (fallback): legacy /im kill — ONLY reached when nvidia-smi
            # found NO ollama-named GPU process (nvidia-smi missing, or Ollama crashed
            # without a tracked GPU app). The wedged-but-GPU-holding case returns above.
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                           capture_output=True, timeout=10)
            subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"],
                           capture_output=True, timeout=10)
            time.sleep(5)
        except Exception as kill_err:
            logger.warning("[VRAM] Failed to kill Ollama: %s", kill_err)

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

        # Step 2: Verify Ollama released the GPU (per-process; v0.36.35)
        if not self._wait_for_model_release(name_substr="ollama", timeout_seconds=30):
            # Retry unload
            logger.warning("[VRAM] Ollama still on GPU, retrying unload...")
            self._unload_ollama()
            time.sleep(3)
            if not self._wait_for_model_release(name_substr="ollama", timeout_seconds=30):
                # Kill Ollama process entirely to free VRAM
                logger.warning("[VRAM] Killing Ollama process to reclaim VRAM...")
                self._kill_ollama_processes()

                # Clear GPU memory fragments after killing processes
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        logger.info("[VRAM] torch.cuda.empty_cache() called")
                except ImportError:
                    pass

                # #304/#333: 3 retry attempts with 15s backoff before giving up
                _vram_ready = False
                for _retry in range(3):
                    if self._wait_for_model_release(name_substr="ollama", timeout_seconds=15):
                        _vram_ready = True
                        break
                    logger.warning("[VRAM] Retry %d/3: VRAM still not clear, waiting 15s...", _retry + 1)
                    time.sleep(15)
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass

                if not _vram_ready:
                    logger.error("[VRAM] Handoff to training FAILED — VRAM not clear after 3 retries")
                    # #304: Send Telegram alert on VRAM handoff failure
                    try:
                        from src.notifications.telegram import send_telegram, is_telegram_enabled
                        if is_telegram_enabled():
                            send_telegram(
                                "\U0001f6a8 VRAM HANDOFF FAILED: Could not clear VRAM "
                                "after killing Ollama + 3 retries. Training deferred to next cycle."
                            )
                    except Exception:
                        pass
                    # Ollama was killed but training can't start — restart Ollama so inference still works
                    logger.info("[VRAM] Restarting Ollama to restore inference capability...")
                    try:
                        import platform as _plat
                        if _plat.system() == "Windows":
                            subprocess.Popen([self._ollama, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            subprocess.Popen([self._ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(5)
                        self._reload_ollama()
                        logger.info("[VRAM] Ollama restarted after failed training handoff")
                    except Exception as restart_err:
                        logger.error("[VRAM] Failed to restart Ollama: %s", restart_err)
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

        # Step 1: Kill training subprocess if running. Capture the PID up front
        # so the per-process clear check (v0.36.35) can confirm the OS has
        # reclaimed its CUDA memory after exit. None when no training is tracked
        # (e.g. handle lost across a watch-loop restart) — then there is nothing
        # we launched holding VRAM and the check is a no-op.
        training_pid = self._training_process.pid if self._training_process else None
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

        # Close training log file if open
        log_file = getattr(self, '_training_log_file', None)
        if log_file and not log_file.closed:
            log_file.close()

        time.sleep(3)

        # Clear GPU memory fragments after killing training
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("[VRAM] torch.cuda.empty_cache() called after training kill")
        except ImportError:
            pass

        # Step 2: Verify training released the GPU (per-process; v0.36.35) —
        # escalate by force-killing the lingering TRAINING process, which is
        # what holds the VRAM here (the prior code killed Ollama, which we are
        # about to load — a no-op against the real holder).
        if not self._wait_for_model_release(pid=training_pid, timeout_seconds=30):
            logger.warning("[VRAM] Training PID %s still on GPU after 30s — force-killing",
                           training_pid)

            if training_pid is not None:
                self._kill_pid(training_pid)

            # Clear GPU cache again after the kill
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("[VRAM] torch.cuda.empty_cache() called after training force-kill")
            except ImportError:
                pass

            if not self._wait_for_model_release(pid=training_pid, timeout_seconds=45):
                logger.error("[VRAM] Handoff to inference FAILED — training still holding GPU after force-kill")
                return False

        # Step 3: Ensure Ollama process is running, then reload model
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.Popen([self._ollama, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([self._ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        Output is redirected to a log file to avoid pipe buffer deadlocks.
        """
        logger.info("[VRAM] Launching training subprocess: %s", task_name)
        log_path = os.path.join("logs", f"training_{task_name}.log")
        os.makedirs("logs", exist_ok=True)
        log_file = open(log_path, "a")
        proc = subprocess.Popen(
            [sys.executable] + script_args,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        self._training_process = proc
        self._training_log_file = log_file
        return proc

    @property
    def training_running(self) -> bool:
        """Check if the training subprocess is currently running."""
        if self._training_process is None:
            return False
        return self._training_process.poll() is None
