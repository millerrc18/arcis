# Containerization — Future-Sprint Spec

**Status:** draft spec (Cleanup Sprint 3 — not yet implemented)
**Author context:** 2026-04-20 audit strategic item #4
**Source docs:** `docs/sprints/cleanup_sprint_3_evaluation.md` §Spec-4, `docs/sprints/cleanup_sprint_3_research.md` §Spec-4, `MASTER.md` (NSSM / Windows integrations), `docs/sprints/cleanup_sprint_1_research.md` (cp1252 incidents H6 + H3.b)

## 0. TL;DR

Move the **training subsystem** into a Linux environment (WSL2 or
Docker-in-WSL2) to eliminate the cp1252 encoding issues that have
already cost three subsystems. Keep the **watch loop** Windows-native
because of the NSSM service integration + PowerShell installer + 24/7
production reliability. Start with **WSL2 alone** (simplest migration);
layer Docker on later for reproducibility if warranted.

Estimated implementation: **1–2 sprints**. Does not block any other
work; can fire at any time.

## 1. Why this spec exists

Windows cp1252 encoding has already caused three production failures
on the training subsystem:

| Symptom | Fix (Cleanup Sprint 1) |
|---|---|
| `UnicodeEncodeError: 'charmap' codec can't encode character '❌'` — logger crash on `❌` emoji | H6: replace emoji + 22 em dashes in `src/scheduler/overnight.py` with ASCII markers |
| `UnicodeDecodeError: 'charmap' codec can't decode byte 0x90` in `trl/chat_templates/gptoss.jinja` — SFTTrainer import fails | H3.b: pin `trl>=0.12,<0.25` |
| Logger `StreamHandler` cp1252 choking on documented test output | H6 regression tests + PYTHONUTF8=1 env follow-up (operator-manual) |

Every Windows-hostile issue hit the training subsystem — the part
that's fundamentally Linux-native (PyTorch / HuggingFace / trl built
and primarily tested on Linux). The watch loop, in contrast, has
never had a cp1252 incident because it runs ASCII-clean domain code
and writes structured logs.

**Goal:** training runs in UTF-8 default glibc Linux, eliminating the
next cp1252 surprise before it fires. Watch loop stays on Windows
because its reliability posture (NSSM auto-restart, PowerShell
installer, Windows service account isolation) is worth preserving.

## 2. Scope decision — what gets containerized, what stays Windows

| Subsystem | Container? | Rationale |
|---|---|---|
| **Training subsystem** (`training_data/train.py`, `src/training/trainer.py`, fine-tune subprocess, trl / transformers / peft / bitsandbytes / unsloth imports) | **Yes** | cp1252-hostile; PyTorch / HuggingFace primary support is Linux; eliminates the bug class. |
| **Watch loop** (`src/scheduler/watch.py`, WatchLoop class, 24/7 operation) | **No — stays Windows** | NSSM service wrapper, auto-restart, Windows service account, `scripts/install_service.ps1` PowerShell installer, `AppEnvironmentExtra` ARCIS_DB_PATH — all Windows-native per `MASTER.md:112,389,407-424`. |
| **Scan services** (`src/services/universe_scanner.py`, `mr_scan_service.py`, `scan_service.py`) | **No — runs in watch-loop process** | Same process tree as watch loop. Imports cross-platform. |
| **Ollama inference daemon** | **No — stays native** | Already cross-platform on Windows; CUDA works directly. Containerizing adds a layer without removing pain. |
| **Render sync, Alpaca adapter, Finnhub / yfinance collectors** | **No — stays native** | Network-bound, OS-agnostic, no cp1252 issues observed. |
| **Reconciliation, risk governor, journal store** | **No — Windows-native** | Runs in watch-loop process. Windows writes to SQLite fine via `connect_db()` (Sprint 2 H7 closed the bare-connect gaps). |
| **Backtests + one-off scripts** (walk-forward, stress tests, training-data scripts) | **Optional — container** | Nice-to-have for reproducibility; not a current pain point. Defer unless operator wants it. |

**Container surface = training subsystem only.** That's the pain
point. The watch loop running as a Windows service is a feature, not
a bug.

## 3. Options tradeoff

### 3.1 WSL2 alone (no Docker) — **recommended first step**

- **Mechanics:** Install Ubuntu 22.04 or 24.04 inside WSL2, install Python 3.12 + CUDA toolkit + training deps (`pip install -r requirements-training.txt`), run `training_data/train.py` from inside WSL2.
- **Pros:**
  - Zero container-orchestration complexity.
  - Native Linux glibc + UTF-8 default — solves cp1252 by construction.
  - GPU passthrough via CUDA-in-WSL2 is first-class on Windows 11 (operator's platform per `MASTER.md:70`).
  - Strong Windows ↔ Linux interop: WSL2 can read Windows paths and vice versa.
  - Free, no licensing considerations.
  - Can bind-mount the repo from Windows (slow for small-file ops, fine for training).
- **Cons:**
  - Not a reproducible artifact. Someone else setting up the same environment has to follow README steps.
  - Two Python installations (Windows for watch loop, Linux for training) — drift risk.
  - Operator has to remember "run training under `wsl`."
- **Best for:** fast cp1252 fix, ship tonight, iterate later.

### 3.2 WSL2 + Docker Engine — **mid-term upgrade**

- **Mechanics:** Same as above, but install Docker Engine inside WSL2 (not Docker Desktop; avoids licensing). Build a `Dockerfile.training` that pins Python + CUDA + deps. `docker build` + `docker run --gpus all -v $(pwd):/repo` for training runs.
- **Pros:**
  - Reproducible: `docker build` produces identical env.
  - Layer cache makes iteration fast.
  - Good for a future second machine / teammate.
  - Still no Docker Desktop licensing dependency.
- **Cons:**
  - Docker-in-WSL2 has slightly worse GPU-passthrough reliability than bare WSL2 (NVIDIA Container Toolkit adds an extra layer).
  - Small-file operations on bind-mounted NTFS are **slow** (10–100× native).
  - Setup takes 1–3 hours first time.
- **Best for:** operator wants a reproducible build artifact, or planning to scale beyond one machine.

### 3.3 Docker Desktop — **not recommended**

- **Mechanics:** Install Docker Desktop on Windows. Same Dockerfile as 3.2.
- **Cons:**
  - Docker Desktop licensing is free for individuals / nonprofits / small business (<$10M revenue, <250 employees), but the framing changes if the operator commercializes the system.
  - Adds a GUI + background service the operator already has one of (NSSM).
  - No meaningful advantage over WSL2 + Docker Engine for a single-user workflow.

### Recommendation

Start with **3.1 (WSL2 alone)** — ships the cp1252 fix tonight. If
after 2 weeks the operator wants reproducibility, upgrade to **3.2
(WSL2 + Docker Engine)** in a follow-up sprint.

## 4. GPU passthrough reality check

- **CUDA in WSL2 (Windows 11):** supported since mid-2022. Windows-side NVIDIA driver + CUDA toolkit inside the WSL2 distro + PyTorch CUDA wheels. Confirmed working with Ollama inference, PyTorch fine-tuning, and trl's SFTTrainer in the community.
- **VRAM contention:** the existing `src/scheduler/vram_manager.py` handoff mechanism is still required. Container does **not** remove contention — the GPU is the same physical device whether Ollama on Windows or PyTorch in WSL2 is using it.
  - Today: Ollama runs on Windows; training runs on Windows; VRAM manager unloads Ollama → starts training → on training completion, reloads Ollama.
  - Post-migration: Ollama on Windows; training runs inside WSL2; **same handoff still needed**. Trainer subprocess is now spawned via `wsl -- python training_data/train.py` instead of direct Python. VRAM manager's unload-ollama logic stays Windows-side.
- **Ollama vs PyTorch VRAM**: both frameworks allocate GPU memory explicitly. `ollama stop` (Windows) releases VRAM before training starts inside WSL2. On training completion, VRAM manager reloads Ollama.

Risk: if WSL2's CUDA driver version diverges from the Windows-side NVIDIA driver, `torch.cuda.is_available()` can go False. Mitigation: pin both sides, update in lockstep, add a pre-flight GPU sanity check in the training entry point.

## 5. Filesystem performance caveats

- **NTFS ↔ ext4 cross-mount** in WSL2 is slow (10–100× native) for small-file operations: `pip install`, pytest discovery, git operations, `find`, tokenizer loading, many-small-file I/O.
- **Large-file operations** (parquet writes, GGUF reads, single big tensors) are fast enough.
- Training workload is **dominated by large-file operations** — model weights load once, batches are in memory. Pip install happens rarely (once per dep change). Tokenizer load is a one-off per training run.

**Mitigation options:**

- **Option A:** Keep repo under `\\wsl$\Ubuntu\home\user\halcyon-lab` (Linux-native, slow from Windows side). Watch loop accesses nothing inside it anyway; Windows IDE / git client can still reach it via UNC path.
- **Option B:** Keep repo on `C:\arcis\halcyon-lab` (Windows-native), bind-mount into WSL2 under `/mnt/c/...`. Watch loop + Windows tools remain fast; training is slower on small-file ops but training doesn't care.
- **Option C (later):** for Docker-in-WSL2, use a named volume for the Python cache (pip / HuggingFace cache / datasets cache). Keeps large-file workloads on native Linux FS.

**Recommended:** Option B for step 1 (WSL2 alone) — requires no repo relocation. Switch to Option A only if pip installs become painful.

## 6. Path handling

- Windows paths in `config/settings.local.yaml` (`C:/arcis/data/ai_research_desk.sqlite3`) do NOT work as-is inside WSL2 (paths become `/mnt/c/arcis/data/ai_research_desk.sqlite3`).
- Training subsystem does **not** talk to the SQLite DB during a training run — it reads training examples from the DB once at job start (or from a JSONL export that `[TRAINING] Exported 1393 training + 0 holdout examples` produces per 2026-04-20 log evidence).
- Mitigation: either
  - (a) Export training examples to JSONL in a shared location (e.g., `/mnt/c/arcis/halcyon-lab/training_data/exports/` ← Windows writes, WSL2 reads), OR
  - (b) Windows-side script calls `wsl -- python train.py --examples-path /mnt/c/arcis/halcyon-lab/training_data/export.jsonl` with a pre-export step.

Entry-point adjustment: `vram_manager.launch_training_subprocess()` needs to spawn `wsl python ...` instead of `python ...`. One-line change.

## 7. NSSM service stays Windows

The existing NSSM setup in `MASTER.md:112,389,407-424`:

- Service name `ArcisWatchLoop`.
- Auto-restart, log rotation, Windows service-account isolation.
- `AppEnvironmentExtra=ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3`.
- Installer script `scripts/install_service.ps1`.

**No change to any of the above.** The watch loop continues running
as a Windows service. Only the training subprocess it spawns gets
rewritten to invoke WSL2.

## 8. Implementation path — Sprint A (WSL2 alone)

### Pass 1 (eval doc, ~1 commit)
- Document the exact Windows → WSL2 migration boundary: training subsystem + its direct deps.
- Inventory of current Windows-specific code in the training path (paths, file I/O, env vars).

### Pass 2 (research, ~1 commit)
- Decide Option A vs B for filesystem layout.
- Decide Option (a) vs (b) for path handling (JSONL export vs bind-mount read).
- Confirm `requirements-training.txt` installs cleanly under Ubuntu 22.04 + Python 3.12.

### Pass 3 (implementation, ~3–5 commits)
- Add `docs/operations/wsl2_setup.md` with step-by-step operator setup guide.
- Modify `src/scheduler/vram_manager.py` `launch_training_subprocess()` to invoke `wsl -- python training_data/train.py ...`.
- Add feature-flag `training.use_wsl2: true|false` in `config/settings.example.yaml` so the change is reversible.
- Regression tests: launch path with WSL2-invoked subprocess verified against the existing Windows-invoked subprocess. Since tests can't easily exercise WSL from Windows CI, the regression test is at the `vram_manager` command-construction level (assert correct `wsl` command assembled).
- Revert trl `<0.25` pin if the encoding issue no longer reproduces in WSL2 (optional; may want to keep the pin for other reasons).

### Sprint B (WSL2 + Docker Engine, optional, ~1 sprint)
- `Dockerfile.training` pinning Python + CUDA + deps.
- `docker-compose.training.yml` for local runs.
- Named volumes for pip / HuggingFace cache.
- `scripts/run_training_docker.ps1` — Windows-side wrapper.
- Documentation in `docs/operations/docker_training.md`.

## 9. Dependencies

- **None blocking.** Sprint-F/G/H chain (#530) does not depend on this.
- **Does not affect** the live watch loop, trading path, or Alpaca integration.
- **Does affect** Cleanup Sprint 1 H3.b's trl pin — post-migration, the pin may no longer be necessary.

## 10. Success criteria

**Sprint A (WSL2 alone):**
- `training_data/train.py` runs to completion without `UnicodeDecodeError` on gptoss.jinja (or any other cp1252-incompatible file).
- VRAM handoff: Ollama unloads on Windows, training subprocess starts in WSL2, GPU allocated.
- Output: new GGUF model file produced, recognizable by Ollama.
- Operator can revert to Windows-native training by flipping `training.use_wsl2: false`.

**Sprint B (Docker, optional):**
- `docker build -f Dockerfile.training .` produces image.
- `docker run --gpus all -v $(pwd):/repo training:latest` runs a training job.
- `pip install`-heavy operations use cached volume (fast re-runs).

## 11. Migration risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| WSL2 CUDA driver / Windows NVIDIA driver drift | Low | Training fails with `cuda not available` | Pin both; pre-flight `nvidia-smi` check in training entry point |
| Bind-mount pip install slowness | Medium | Setup takes hours not minutes | Option A (repo under `\\wsl$\`) or named pip cache volume (Docker path) |
| WSL2 subprocess spawn from Windows NSSM service fails | Low-medium | Training doesn't launch from the service user | Test under the NSSM service account specifically; Windows services have restricted WSL access in some configs |
| Operator forgets WSL2 is where training runs, inspects Windows-side `.venv` for "why is new version missing" | Medium | Debugging confusion | Operator-facing doc + config flag `training.use_wsl2: true` visible in YAML |
| trl upgrade still crashes on something Linux-specific | Very low | Training fails post-migration | The current pin `<0.25` stays as a safety net; only remove it after N days of green |

## 12. Out of scope — filed separately

- **Watch loop containerization.** Deliberately Windows-native. Revisit only if a specific cp1252 bug hits the watch loop (none observed to date).
- **Dashboard / API frontend containerization.** Already deployed to Render — already containerized by Render's build pipeline.
- **Multi-machine distributed training.** Sprint B Dockerfile enables it but orchestration (multiple GPU hosts) is its own sprint.

## 13. Decision points for operator at sprint-dispatch time

1. **WSL2 alone vs. WSL2 + Docker Engine first:** recommendation is WSL2 alone (Sprint A) first; Docker later. Operator can choose to go straight to Docker if reproducibility is a hard requirement.
2. **Keep the trl `<0.25` pin post-migration:** recommendation yes (belt + suspenders); remove only if pinning becomes blocking for a feature need.
3. **PYTHONUTF8=1 on Windows side** (Sprint 1 H6 follow-up — operator-manual to add to NSSM service env): **still worth doing** even after WSL2 migration, because the watch loop stays Windows and benefits from the UTF-8 default for its own logging.
4. **Include backtest / stress-test scripts in the container?** Recommendation: defer. Current scripts run fine on Windows. Containerize them only if they start failing for cp1252 reasons too.

## 14. Next CC sprint prompt (shape-only)

> "Build Sprint A: migrate the training subsystem to WSL2 alone.
> Modify `src/scheduler/vram_manager.py` `launch_training_subprocess()`
> to spawn `wsl python training_data/train.py ...` when
> `config.training.use_wsl2=true`. Add `docs/operations/wsl2_setup.md`
> with operator setup steps. Feature-flag the change. Regression
> tests at the command-construction level. Do NOT remove the trl
> version pin in this sprint."

Pass-3 spec file ends here.
