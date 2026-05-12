# Operator-Guide Insert — Dual-GPU Operation (Strategy A)

**Status:** Prose draft for `docs/operator-guide.md` insertion as part of SP6 implementation PR (same-PR rule, CLAUDE.md). Insertion anchor: immediately before the literal heading `### "Ollama crashes / corpus producing template fallbacks"` (currently line 618 — verify via `grep -n` at implementation time).

---

### Dual-GPU Operation (Strategy A)

The lab runs two NVIDIA GPUs in workload-separation mode:

| GPU | Card | VRAM | Workload | Pinned via |
|---|---|---|---|---|
| 0 | RTX 3090 | 24 GB | Training subprocess (overnight_train.py, trainer.py CURRICULUM/DPO scripts, verify_training_readiness.py) | `CUDA_VISIBLE_DEVICES=0` in NSSM ArcisWatchLoop env + operator interactive shell |
| 1 | RTX 3060 | 12 GB | Ollama daemon (halcyon-v1, council inference, grammar_client if enabled) | `CUDA_VISIBLE_DEVICES=1` in scripts/ollama_watchdog.ps1 |

**CUDA enumeration order is pinned to PCI bus order** (`CUDA_DEVICE_ORDER=PCI_BUS_ID`) at the same boundaries so driver upgrades, PCIe reseats, or GPU swaps cannot silently flip GPU 0 / GPU 1 identity.

#### Why workload separation

Before the 3060 reinstall (2026-05-12), training and Ollama competed for VRAM on the 3090, requiring an evening/morning handoff dance. Workload separation eliminates the contention — Ollama serves 24/7 on GPU 1 while training runs on GPU 0 without coordination.

#### Verifying the split

```powershell
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv
```

Expected steady state:
- GPU 0: RTX 3090, idle ~0–100 MiB when no training; ~14–18 GiB during training.
- GPU 1: RTX 3060, ~5–9 GiB resident (Ollama serving halcyon-v1).

For a deeper check, run `python scripts/verify_training_readiness.py`. It includes a dual-GPU layout check that fails loud if the split is wrong.

#### Per-card VRAM math (NUM_PARALLEL default = 2)

**GPU 0 (RTX 3090, 24 GB):**
- Training (4-bit Qwen3-8B + LoRA + optimizer state + activations): ~14–18 GB during fine-tune.
- Headroom: ~6–10 GB.
- Training per_device batch size: tuned by trainer.py CURRICULUM_TRAIN_SCRIPT; operator-tunable.

**GPU 1 (RTX 3060, 12 GB):**
- Ollama halcyon-v1 (Qwen3-8B q4_K_M): ~5–6 GB resident.
- KV cache (NUM_PARALLEL=2, typical 8K context): ~1.5–2 GB.
- Headroom: ~4–5 GB (NUM_PARALLEL=2 is the safe default).
- **NUM_PARALLEL=4 is opt-in only after load-testing.** The 4-way config leaves only ~0.4 GB cushion against CUDA transient workspace allocations (~512 MB), and 5-agent concurrent council bursts can push past the cap. To opt in: edit `scripts/ollama_watchdog.ps1` setting `OLLAMA_NUM_PARALLEL = '4'` AND run the §10 NUM_PARALLEL=4 load test before letting it ride. If `nvidia-smi -i 1 memory.used` ever exceeds 11.5 GB, revert to 2.

#### Daily ops cadence (post-Strategy-A)

The pre-Strategy-A 6:50 PM evening handoff and 5:15 AM morning handoff are **deprecated**. Strategy A makes them unnecessary:
- Ollama runs 24/7 on GPU 1. No evening unload.
- Training fires any time on GPU 0 without coordination. No morning reload.

The overnight training schedule (auto-triggered when `should_train()` returns True) still respects the operator's training window (default 6:50 PM ET start). The training subprocess inherits `CUDA_VISIBLE_DEVICES=0` and `CUDA_DEVICE_ORDER=PCI_BUS_ID` from the watch-loop NSSM service env.

#### Required env-var boundaries (read before troubleshooting)

Six process boundaries must have CUDA env set correctly. See `docs/audits/2026-05-12-dual-gpu-ideation/spec.md` §5 for the full inventory. Quick reference:

| Boundary | `CUDA_VISIBLE_DEVICES` | `CUDA_DEVICE_ORDER` | Set via |
|---|---|---|---|
| Watch loop (NSSM) | 0 | PCI_BUS_ID | NSSM AppEnvironmentExtra (preserve all existing vars — see §5.2 B1) |
| Ollama (ps1) | 1 | PCI_BUS_ID | `$env:` assignments at top of `scripts/ollama_watchdog.ps1` |
| Ollama watchdog (NSSM, new in SP6) | 1 | PCI_BUS_ID | NSSM AppEnvironmentExtra for `ArcisOllamaWatchdog` service |
| Operator shell (training) | 0 | PCI_BUS_ID | `[Environment]::SetEnvironmentVariable(...,'User')` (User-scope, requires fresh shell) |
| Training subprocess | 0 (inherited) | PCI_BUS_ID (inherited) | NSSM-inherited; no separate setting |
| Watch-loop llama-cpp (grammar) | 0 (inherited) | PCI_BUS_ID (inherited) | NSSM-inherited; only loaded if `llm.use_grammar_enforcement: true` |

#### Post-reboot recovery

After a Windows reboot:

1. NSSM auto-starts `ArcisWatchLoop` — watch loop comes up with `CUDA_VISIBLE_DEVICES=0`.
2. NSSM auto-starts `ArcisOllamaWatchdog` (SP6 addition — see §6) — Ollama comes up on GPU 1 with `CUDA_VISIBLE_DEVICES=1`.
3. Operator runs the pre-flight verification (spec §10.0) to confirm both services landed correctly.

If `ArcisOllamaWatchdog` is not yet installed (pre-SP6 deploy), the operator must run `scripts/start_ollama_watchdog.bat` from a shell that has the GPU 1 env set, otherwise Ollama lands on whichever device CUDA defaults to (typically GPU 0 = 3090, colliding with training).

#### Failure modes and recovery

The immediately-following `### "Ollama crashes / corpus producing template fallbacks"` section (and §7 watchdog section below) cover failure-mode details. For the full Strategy A failure matrix see `docs/audits/2026-05-12-dual-gpu-ideation/spec.md` §11.
