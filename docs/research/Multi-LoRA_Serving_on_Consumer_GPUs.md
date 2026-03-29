# Multi-LoRA serving on consumer GPUs for Halcyon Lab

**The optimal architecture for serving 3–8 LoRA adapters on Qwen3 8B is llama.cpp's native server with pre-loaded adapters and per-request selection — not Ollama, not vLLM.** llama-server supports loading all adapters at startup, hot-swapping via API with ~10–50ms latency per adapter change, and works natively on Windows 11 with CUDA. The real bottleneck is KV cache invalidation on adapter swap (~1–2 seconds), not the adapter weights themselves — at rank 16, each adapter consumes just ~34MB versus the 8.7GB base model. On the RTX 3060 (12GB), all 8 rank-32 adapters fit simultaneously alongside Qwen3 8B Q8_0 with room to spare. A dual-GPU setup running two independent llama-server instances can process 3 strategies × 15 stocks within 15 minutes at 30s/inference — well under the 30-minute window.

---

## Comparison of serving architectures

| Feature | Ollama hot-swap | vLLM multi-LoRA | llama-server | MoLE/X-LoRA |
|---|---|---|---|---|
| **Multi-adapter feasibility** | ⚠️ Separate model per adapter; no hot-swap | ✅ Native multi-LoRA | ✅ Native multi-LoRA | ✅ All loaded simultaneously |
| **Adapter swap latency** | 15–25s (full model reload on 3060) | ~50–200ms (LRU cache swap) | ~10–50ms (scale toggle) + 1–2s KV rebuild | 0ms (gating selects per-token) |
| **VRAM per adapter (rank 16)** | ~8.7GB (full model copy per adapter) | ~50–80MB (pre-allocated slot) | ~34MB (raw adapter weights) | ~34MB + ~1–100MB router |
| **Max adapters on RTX 3060** | 1 at a time | 3 (AWQ 4-bit base, 2048 ctx) | **8+ (Q8_0 base, 4096 ctx)** | 8+ (Q8_0 base) |
| **Max adapters on RTX 3090** | 1–2 at a time | 8 (AWQ 4-bit, 4096 ctx) | **8+ (Q8_0 base, 8192 ctx)** | 8+ (Q8_0 base) |
| **Windows 11 native** | ✅ Full | ⚠️ WSL2 required | ✅ Full CUDA support | ❌ PyTorch only, no GGUF |
| **Complexity** | Low | Medium-High | **Medium** | High (training required) |
| **Structured output** | ✅ `format: "json"` | ✅ JSON schema + regex | ✅ GBNF grammar + JSON schema | ✅ (framework-dependent) |
| **GGUF support** | ✅ Native | ⚠️ Experimental, not with LoRA | ✅ Native | ❌ Safetensors only |
| **Single-request latency** | **~45ms TTFT** | ~82ms TTFT | **~40–50ms TTFT** | Comparable to single adapter |

---

## Ollama cannot hot-swap adapters today

Ollama supports applying a single LoRA adapter via the `ADAPTER` directive in a Modelfile, and PR #7667 (merged November 2024) added code-level support for multiple `--lora` flags. However, **Issue #9548 (opened March 2025) for LoRA hot-swapping remains unresolved as of v0.18.3** (March 2026). The underlying llama.cpp engine gained hot-swap endpoints in PRs #8857 and #10994, but Ollama has not yet exposed this capability through its API.

The practical workaround — creating separate model definitions per adapter (e.g., `strategy-A`, `strategy-B`, each with `FROM qwen3:8b-q8_0` and a different `ADAPTER` file) — forces a full model unload/reload cycle when switching. On the RTX 3060 with 12GB VRAM, cold-loading an **8.7GB Q8_0 model takes approximately 15–25 seconds**. The base model plus KV cache consumes ~10–10.7GB, leaving no room for a second model instance. Even on the RTX 3090, two 8.7GB model instances cannot coexist simultaneously.

Key Ollama configuration parameters for multi-model scenarios include `OLLAMA_MAX_LOADED_MODELS` (default: 3× GPU count), `OLLAMA_KEEP_ALIVE` (default: 5 minutes), and `OLLAMA_KV_CACHE_TYPE` (supports `q8_0` or `q4_0` for ~50% KV cache reduction). Flash attention (`OLLAMA_FLASH_ATTENTION=1`) reduces memory further. But none of these solve the fundamental problem: **Ollama treats each adapter-model combination as a separate model requiring its own full VRAM allocation**.

---

## vLLM excels at multi-LoRA but demands WSL2 and format conversion

vLLM's multi-LoRA architecture loads the base model once and applies adapter weights per-request using the **Punica kernel** (derived from S-LoRA research). The server accepts `--enable-lora --max-loras N --max-lora-rank R` and routes requests to specific adapters via the `model` field in OpenAI-compatible API calls. Runtime adapter management is available through `POST /v1/load_lora_adapter` and `POST /v1/unload_lora_adapter` when `VLLM_ALLOW_RUNTIME_LORA_UPDATING=True`.

The critical constraint for Halcyon Lab: **vLLM's GGUF support is "highly experimental and under-optimized"** per official documentation, and GGUF + LoRA compatibility is undocumented. Multi-LoRA serving requires safetensors-format adapters on AWQ, GPTQ, or BF16 base models. This means converting from the current GGUF pipeline to AWQ 4-bit (Qwen/Qwen3-8B-AWQ at ~5–6GB) — a workable but significant architectural change.

On Windows 11, vLLM requires **WSL2** (the official recommendation) or community native builds from SystemPanic/vllm-windows. WSL2 adds roughly **5–10% performance overhead** for GPU-bound workloads. The Qwen3 8B AWQ model fits the RTX 3060 with 3 active LoRA slots at 2048 context (`--enforce-eager` needed to disable CUDA graph memory overhead), while the RTX 3090 comfortably handles 8 adapters at rank 32 with 4096+ context.

**vLLM pre-allocates per-slot memory** sized to `max_lora_rank`, so setting `--max-lora-rank 32` when only rank 16 is needed wastes ~2× memory per slot. Each rank-16 slot consumes approximately **50–80MB**, and each rank-32 slot **100–160MB** on Qwen3 8B. With 8 slots at rank 32, total additional VRAM is ~800MB–1.3GB. Adapters beyond `max_loras` are cached in CPU memory and swapped on-demand via LRU eviction.

For single-request latency, Ollama and llama.cpp outperform vLLM: **TTFT is ~45ms for Ollama versus ~82ms for vLLM** at concurrency=1. vLLM's advantage only emerges at 5+ concurrent requests, where continuous batching and PagedAttention deliver dramatically higher throughput.

---

## llama-server is the clear winner for this workload

llama.cpp provides the most complete solution for multi-LoRA serving on consumer GPUs with GGUF models on Windows. The server supports:

- **Multiple adapters at startup**: `--lora adapter1.gguf --lora adapter2.gguf ...` loads all adapters into memory
- **Pre-load without applying**: `--lora-init-without-apply` loads all adapters with scale=0, avoiding startup overhead
- **Global adapter control**: `POST /lora-adapters` toggles adapter scales server-wide
- **Per-request selection**: The `lora` field in completion requests specifies adapter scales per-call (PR #10994, merged)

The key implementation pattern for Halcyon Lab:

```bash
llama-server -m Qwen3-8B-Q8_0.gguf \
  --lora-scaled momentum.gguf:0.0 \
  --lora-scaled sentiment.gguf:0.0 \
  --lora-scaled risk.gguf:0.0 \
  --lora-init-without-apply \
  -ngl 999 -c 4096 --port 8080 -fa
```

Per-request API calls then specify which adapter to activate:
```json
{
  "prompt": "Analyze AAPL momentum...",
  "lora": [{"id": 0, "scale": 1.0}],
  "response_format": {"type": "json_schema", "json_schema": {"schema": {...}}},
  "max_tokens": 512
}
```

**Adapter swap latency breaks down into two components.** Toggling the scale of pre-loaded adapters takes approximately **10–50ms** on GPU — the tensors are already resident in VRAM. However, changing adapter weights **invalidates the KV cache** because cached key-value pairs were computed with different LoRA weights. Rebuilding the KV cache for a 2048-token prompt at ~2,000–4,000 tokens/sec takes **0.5–1 second** — this is the dominant swap cost, not the adapter itself.

GGUF LoRA adapters are created from PEFT/safetensors format using `convert_lora_to_gguf.py` from the llama.cpp repository, or via the GGUF-my-LoRA HuggingFace Space. GBNF grammar and JSON schema structured output work fully with LoRA — they operate at the token sampling layer, independent of model weights. Windows 11 native CUDA is fully supported with pre-built binaries or pip-installable wheels (`pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124`).

---

## Capacity planning reveals adapters are not the bottleneck

Qwen3 8B uses **36 layers, 8 KV heads, 128-dim heads** with grouped-query attention. Per-token KV cache in FP16 is **0.14MB**, yielding these context-dependent memory requirements:

| Context | FP16 KV cache | Q8_0 KV cache | Q4_0 KV cache |
|---|---|---|---|
| 2,048 | 0.28 GB | 0.14 GB | 0.07 GB |
| 4,096 | 0.56 GB | 0.28 GB | 0.14 GB |
| 8,192 | 1.13 GB | 0.56 GB | 0.28 GB |

The VRAM budget after loading the base model, CUDA overhead (~0.5GB), and KV cache reveals that **LoRA adapters are negligibly small relative to available headroom**:

| GPU × Quantization | Free after model + 4K KV (FP16) | Max rank-16 adapters | Max rank-32 adapters |
|---|---|---|---|
| **RTX 3060 + Q8_0** | 2.24 GB | 65 | 32 |
| **RTX 3060 + Q4_K_M** | 5.94 GB | 174 | 87 |
| **RTX 3090 + Q8_0** | 14.24 GB | 418 | 209 |
| **RTX 3090 + Q4_K_M** | 17.94 GB | 527 | 263 |

Even the most constrained scenario — RTX 3060 with Q8_0 at 8192 context (FP16 KV) — leaves 1.67GB free, enough for **24 rank-32 adapters**. The practical limit is never adapter count but rather KV cache size and base model quantization. Eight adapters at rank 32 total just **544MB**.

---

## Optimal batching for the 30-minute scan window

The workload of 3 strategies × 15 stocks = 45 inference calls must complete within 1,800 seconds. Three batching approaches were analyzed:

**Strategy-serial** (recommended for single GPU): Load adapter 1 → process all 15 stocks → swap → repeat. Only 2 swaps total. At **30s/inference, total time is ~22.5 minutes** — well within the window. At 60s/inference, it balloons to 45 minutes and fails.

**Stock-serial** yields 30 swaps instead of 2, adding measurable overhead. At 10s/swap, this costs an extra 5 minutes versus strategy-serial. Not recommended unless per-stock result grouping is required.

**Dual-GPU parallel** (recommended for scaling): Two independent llama-server instances, one per GPU, processing simultaneously. Split strategies across GPUs — RTX 3090 handles 2 strategies (30 inferences), RTX 3060 handles 1 (15 inferences). Wall-clock time equals the slower GPU:

| Inference time | RTX 3090 (2 strategies) | RTX 3060 (1 strategy) | Wall clock |
|---|---|---|---|
| 30s | 15 min | 7.5 min | **15 min ✅** |
| 45s | 22.5 min | 11.25 min | **22.5 min ✅** |
| 60s | 30 min | 15 min | **30 min ✅** |

For 8 strategies at 30s/inference (120 inferences), dual-GPU processing takes exactly 30 minutes with optimal splitting. At 45s/inference with 5+ strategies, a third GPU or inference time optimization (Q4_K_M quantization, shorter prompts, disabled thinking mode) becomes necessary.

---

## MoLE is architecturally elegant but impractical here

The Mixture of LoRA Experts family includes several approaches: **X-LoRA** (integrated into HuggingFace PEFT, uses frozen adapters with a trainable gating classifier), **LoRAMoE** (per-layer routers trained jointly with experts, 3M+ training samples), **TT-LoRA MoE** (frozen experts with separately trained top-1 router), and **MixLoRA** (consumer-GPU optimized at ~17.9GB for LLaMA-7B with 8 experts). X-LoRA is the most production-ready, available as `peft.XLoraConfig`.

However, **no MoLE implementation exists for GGUF format**. All require PyTorch/safetensors inference, sacrificing the performance advantage of llama.cpp's optimized GGUF kernels. More fundamentally, the existing setup classifier already provides the routing function — it classifies stocks into trading strategies, directly mapping to adapter selection. This is functionally equivalent to TT-LoRA MoE's hard top-1 routing but with **zero additional training, zero inference overhead, and zero architectural complexity**.

The gating overhead of MoLE approaches ranges from near-zero (X-LoRA sparse top-1 at ~2–5% overhead) to significant (dense routing through all experts at ~15–30% overhead). For 3–8 adapters with sequential processing, adapter swap costs of 1–2 seconds are negligible compared to 30–60 second inference times. **MoLE becomes worthwhile only beyond ~10+ adapters with high-throughput concurrent multi-strategy inference** — a threshold Halcyon Lab is unlikely to reach on consumer hardware.

The recommended "MoLE alternative" is **classifier-based hard routing**: setup classifier selects adapter → llama-server applies it per-request. This achieves the same functional outcome as TT-LoRA MoE without the training pipeline.

---

## Phase 2 architecture: 2 adapters on RTX 3060

**Configuration**: Single llama-server instance on Windows 11 native

```bash
llama-server.exe ^
  -m Qwen3-8B-Q8_0.gguf ^
  --lora-scaled strategy_A.gguf:0.0 ^
  --lora-scaled strategy_B.gguf:0.0 ^
  --lora-init-without-apply ^
  -ngl 999 -c 4096 -fa ^
  --cache-type-k q8_0 ^
  --port 8080
```

**VRAM breakdown**: Base model 8.7GB + CUDA overhead 0.5GB + 2 adapters at rank 16 = 68MB + KV cache (4096 ctx, Q8_0) = 0.28GB. **Total: ~9.55GB of 12GB** — 2.45GB headroom.

**Workflow**: Strategy-serial batching. Setup classifier routes each stock to adapter A or B. Process all adapter-A stocks first (scale A to 1.0, B to 0.0), then swap (1–2s including KV rebuild), process all adapter-B stocks. For 2 strategies × 15 stocks × 30s = **~15.1 minutes**.

**Structured output**: Use `response_format` with JSON schema per request. GBNF grammar also available for complex output formats.

---

## Phase 3 architecture: 4 adapters on RTX 3090

**Configuration**: Single llama-server instance with all 4 adapters pre-loaded

```bash
llama-server -m Qwen3-8B-Q8_0.gguf \
  --lora-scaled strategy_A.gguf:0.0 \
  --lora-scaled strategy_B.gguf:0.0 \
  --lora-scaled strategy_C.gguf:0.0 \
  --lora-scaled strategy_D.gguf:0.0 \
  --lora-init-without-apply \
  -ngl 999 -c 8192 -fa \
  --cache-type-k q8_0 \
  --port 8080
```

**VRAM breakdown**: Base model 8.7GB + overhead 0.5GB + 4 adapters at rank 32 = 272MB + KV cache (8192 ctx, Q8_0) = 0.56GB. **Total: ~10.0GB of 24GB** — 14GB headroom for extended context or additional adapters.

**Workflow**: Strategy-serial batching with 3 swaps. At 30s/inference: 4 × 15 × 30s + 3 × 2s = **~30.1 minutes** on a single GPU. If tight, use **dual-GPU**: RTX 3090 handles strategies A+B (30 inferences), RTX 3060 handles C+D (30 inferences). Wall-clock: **~15.1 minutes at 30s/inference**.

**Dual-GPU setup**: Two llama-server instances with `CUDA_VISIBLE_DEVICES` pinning:
```bash
# GPU 0 (RTX 3090)
set CUDA_VISIBLE_DEVICES=0
llama-server -m Qwen3-8B-Q8_0.gguf --lora-scaled A.gguf:0.0 --lora-scaled B.gguf:0.0 --port 8080

# GPU 1 (RTX 3060)  
set CUDA_VISIBLE_DEVICES=1
llama-server -m Qwen3-8B-Q4_K_M.gguf --lora-scaled C.gguf:0.0 --lora-scaled D.gguf:0.0 --port 8081
```

A Python orchestration layer routes requests to the appropriate server based on the setup classifier's output.

---

## Capacity planning across hardware and configurations

| Hardware | Quantization | Base VRAM | Context | KV cache | Free for LoRA | Max r16 | Max r32 | Swap latency |
|---|---|---|---|---|---|---|---|---|
| RTX 3060 12GB | Q8_0 | 8.7 GB | 2048 | 0.28 GB | 2.52 GB | 74 | 37 | ~1–2s |
| RTX 3060 12GB | Q8_0 | 8.7 GB | 4096 | 0.56 GB | 2.24 GB | 65 | 32 | ~1–2s |
| RTX 3060 12GB | Q4_K_M | 5.0 GB | 4096 | 0.56 GB | 5.94 GB | 174 | 87 | ~1–2s |
| RTX 3060 12GB | Q4_K_M | 5.0 GB | 8192 | 1.13 GB | 5.37 GB | 158 | 79 | ~1.5–3s |
| RTX 3090 24GB | Q8_0 | 8.7 GB | 4096 | 0.56 GB | 14.24 GB | 418 | 209 | ~1–2s |
| RTX 3090 24GB | Q8_0 | 8.7 GB | 8192 | 1.13 GB | 13.67 GB | 402 | 201 | ~1.5–3s |
| RTX 3090 24GB | Q4_K_M | 5.0 GB | 8192 | 1.13 GB | 17.37 GB | 510 | 255 | ~1–2s |

Swap latency includes ~10–50ms for adapter scale toggle plus ~0.5–2s for KV cache rebuild (proportional to prompt length). At **8 strategies with rank-32 adapters, even the RTX 3060 at Q8_0 with 4096 context can hold all 8 simultaneously** (544MB of 2.24GB free). Hardware limits are reached only at implausible adapter counts (30+).

For 8 strategies to complete within 30 minutes:
- **Single RTX 3090**: 8 × 15 × 30s = 60 min ❌ (needs parallelism or faster inference)
- **Dual GPU (3090 + 3060)**: Split 5+3 strategies. Max(75×30s, 45×30s)/per-GPU ≈ **37.5 min ❌** (needs Q4_K_M for ~20s/inference or 4+4 split at 30 min exactly)
- **Both GPUs + Q4_K_M + shorter prompts**: Target ~20s/inference → dual GPU at 4+4 = max(60×20s, 60×20s) = **20 min ✅**

## Conclusion

**llama-server with `--lora-init-without-apply` and per-request adapter selection is the definitive solution** for Halcyon Lab's multi-adapter serving needs. It uniquely combines GGUF native support, Windows compatibility, sub-second adapter swapping, structured output, and minimal VRAM overhead — advantages no other framework matches simultaneously. Ollama lacks hot-swap capability, vLLM requires WSL2 and format conversion away from GGUF, and MoLE approaches add training complexity without meaningful benefit below ~10 adapters.

The most overlooked finding is that **LoRA adapter memory is essentially irrelevant to capacity planning** — 8 rank-32 adapters total just 544MB, while the base model alone is 8.7GB and KV cache at 8192 context consumes 1.13GB. The true scaling constraint is inference time × stock count × strategy count, which is best addressed through dual-GPU parallelism and quantization-driven speed improvements rather than more sophisticated serving architectures.