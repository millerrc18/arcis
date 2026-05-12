# Dual-GPU Utilization — Design Brief (task #91)

**Triggered by:** RTX 3060 hardware install completed 2026-05-12 ~03:50 ET, alongside existing RTX 3090.

**Sprint context:** Sprint 5 (final sprint). Wave E of the glidepath. Walk-forward implementation is OUT OF SCOPE for Sprint 5 (post-sprint track).

## Current GPU state (verified via `nvidia-smi` + `torch.cuda` 2026-05-12 03:50)

| GPU | Card | VRAM | Compute | SMs | PCIe Bus | Idle Temp | Idle Pwr |
|---|---|---|---|---|---|---|---|
| 0 | RTX 3090 | 25.8 GB | 8.6 (Ampere) | 82 | 01:00.0 | 55°C | 29W |
| 1 | RTX 3060 | 12.9 GB | 8.6 (Ampere) | 28 | 08:00.0 | 42°C | 6W |

- Driver: 596.36 (max CUDA 13.2)
- PyTorch: 2.6.0+cu124 (CUDA 12.4 runtime — forward-compat with driver)
- cuDNN: 90100
- Same compute capability on both — no PTX/kernel divergence

## Current GPU consumers (pre-design state)

1. **Ollama** (PID 12604) — squatting on GPU 0 (3090). Serves the `halcyon-v1` model (Qwen3-8B fine-tuned). ~1.1 GB VRAM idle. This is currently the only persistent GPU consumer outside of training runs.
2. **Training pipeline** — `train.py` (rewritten 2026-05-10 per memory `project_gpu_upgrade`): Transformers + PEFT + TRL stack, no Unsloth dependency. `NUM_PARALLEL=4` recently became viable on the 24 GB 3090 alone. Used for fine-tuning Qwen3-8B with LoRA adapters on the Stage-1 corpus.
3. **Council inference** — uses Ollama under the hood, so shares GPU 0 with the persistent Ollama process.
4. **Watch loop / dashboard** — CPU-only (no GPU dependency).
5. **Backtesting / simulation** — CPU-only.

## What changed with the 3060 install

The 3060 adds 12 GB VRAM + 28 SMs of compute. It does NOT replace the 3090 — both stay installed. The 3060 is on a different PCIe slot (likely x4 or x8 vs the 3090's x16), but for workload-separation strategies (no peer-to-peer kernel ops) PCIe bandwidth is irrelevant.

## Design goals (from operator + task #91 description)

1. **Best utilization of both cards.** Identify the workload-separation, parallelism, or specialization strategy that maximizes throughput.
2. **Eliminate training-vs-inference VRAM contention.** Currently NUM_PARALLEL=4 + Ollama serving consume most of the 3090's VRAM during overnight training windows. Adding the 3060 should remove that bottleneck.
3. **No regressions.** Existing Ollama-serving-halcyon-v1 path must keep working.
4. **Deliverable: design spec, not implementation.** Implementation may slip to Wave F or post-sprint per operator's open question in the glidepath.

## Candidate strategies to evaluate

The design team should evaluate these and recommend ONE with rationale (or propose a better alternative):

### Strategy A — Workload separation (most likely winner)

- **GPU 0 (3090, 24 GB):** Training + council inference
- **GPU 1 (3060, 12 GB):** Ollama serving (halcyon-v1) + any embedding/reranker workloads
- **Mechanism:** `CUDA_VISIBLE_DEVICES=1 ollama serve` (Ollama binds to whichever device is "0" in its view). Train.py defaults to `cuda:0` which becomes the 3090 absent CUDA_VISIBLE_DEVICES.
- **Pro:** Zero training-vs-inference contention; no code changes to train.py; small Ollama config change.
- **Con:** 3060's 12 GB may be tight for Qwen3-8B (8B params @ float16 = ~16 GB; @ 4-bit quant = ~4-5 GB so probably fine for the quantized halcyon-v1).
- **Verification needed:** Does halcyon-v1's quantization fit in 12 GB with KV cache headroom for typical context lengths?

### Strategy B — Asymmetric DDP / FSDP training

- **Both GPUs train together** via DistributedDataParallel or Fully Sharded Data Parallel, scaling effective batch size.
- **Pro:** Higher training throughput if it works.
- **Con:** Mixed-VRAM DDP is *notoriously* awkward — each GPU stores a full model replica; the 3060's 12 GB caps effective per-replica size to what fits there. FSDP can shard parameters across both, but inter-GPU bandwidth becomes the bottleneck on PCIe (vs NVLink).
- **Verification needed:** Does FSDP-with-CPU-offload give acceptable throughput on PCIe x8/x16 mixed link?

### Strategy C — Pipeline parallel (frozen base on 3060, LoRA on 3090)

- **3060:** Holds frozen Qwen3-8B base weights (read-only)
- **3090:** Holds LoRA adapters + activations + optimizer state
- **Pro:** Useful if base model grows beyond 24 GB
- **Con:** Adds activation-passing across PCIe per forward/backward — significant latency penalty unless the base model is much larger than 8B params. Currently 8B fits comfortably on 3090 alone.
- **Verdict:** Likely overkill for current model size; revisit if scaling to 70B+.

### Strategy D — Hot-spare / OOM rescue

- **3060:** Idle by default. Train.py + Ollama use 3090.
- On OOM: train.py catches, retries with `device_map="auto"` so PyTorch spills to 3060.
- **Pro:** Simplest; preserves status quo for normal operation.
- **Con:** 3060's compute sits idle 99% of the time. Wasteful.

### Strategy E — Specialized: 3060 for embeddings / rerankers

- **3060:** Dedicated to sentence-transformers (embedding generation for corpus generation, RAG, similarity search), cross-encoders (reranking), or any small-model auxiliary task.
- **3090:** Training + council + Ollama.
- **Pro:** Frees up 3090 from embedding workloads (if any exist currently).
- **Con:** Need to audit codebase for embedding/reranker workloads — may not have enough to justify dedicating an entire card.

## Specific questions for the design team

1. **Which strategy wins?** Recommend ONE with strict rigor (per operator memory `feedback_strict_rigor_no_handwave`).
2. **For the winning strategy: exact mechanism.** What env vars get set where? What code changes (if any)? What config changes?
3. **Failure modes.** What happens if 3060 fails / driver hiccup / VRAM exhaustion on either card? Recovery procedure?
4. **Verification plan.** How does the operator confirm the split is working after implementation? Specific commands.
5. **Performance expectations.** Quantitative estimates — training throughput delta, inference latency delta, total system effective capacity.
6. **Operator-guide additions.** What sections of `docs/operator-guide.md` need new runbook entries?

## Out of scope for this design

- Walk-forward framework GPU usage (post-Sprint-5 sprint)
- Multi-host scaling (single-machine only)
- AMD GPUs or other vendor support
- Cloud-burst patterns (no Render / no AWS in scope)

## Codebase entry points the design team should read

- `src/llm/` — Ollama integration points
- `src/training/train.py` — training loop, device assignment
- `src/training/` — any other training-related modules
- `src/council/` — inference path that uses Ollama
- `train.py` (root) — main training entry point (rewritten 2026-05-10 per memory)
- `requirements.txt` + `requirements-cloud.txt` — version-pinning state
- `config/settings.local.yaml` — runtime config
- `.env` — env-var-based device config (currently none)
- `nvidia-smi` output reference attached above

## Constraints + operator memory pointers

- **`feedback_strict_rigor_no_handwave`** — Sprint 0+ dispatches require worktree isolation, sibling-search, no-skip/weaken/bypass. Design team should match this rigor.
- **`feedback_fix_before_trade`** — defaults to fix-now; design should propose implementation that's deployable in Sprint 5 if approved.
- **`feedback_sprint_5_is_final`** — design must close cleanly within Sprint 5 OR explicitly scope out to post-sprint.
- **`user_preferences`** — Quality over speed. Operator prefers thoroughness.
- **`project_gpu_upgrade`** (2026-05-10) — historical context; explains why train.py is Transformers+PEFT+TRL and not Unsloth.

## Expected output

- **`docs/audits/2026-05-12-dual-gpu-ideation/spec.md`** — design spec with recommendation + rationale + mechanism + failure modes + verification + operator-guide changes
- **`docs/audits/2026-05-12-dual-gpu-ideation/plan.md`** — implementation plan (task graph), only if operator wants Wave E implementation in Sprint 5

Operator will decide implementation-in-S5 vs design-only after reviewing the spec.
