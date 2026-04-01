# Deep Research: Hardware Deployment Strategy for a Multi-Desk AI Trading System

I'm the solo founder of Halcyon Lab — an autonomous AI-powered equity trading system scaling from a single RTX 3060 12GB to a multi-desk, multi-model architecture. I need a comprehensive hardware deployment strategy that starts with where I am today and maps every upgrade step to a specific capability unlock, all the way through to the "infinite money" ideal state.

## Current State
- **Hardware:** Single Windows 11 workstation, RTX 3060 12GB, 32GB RAM, NVMe SSD
- **Model:** Qwen3 8B (Q8_0 GGUF, 8.7GB) via Ollama — consumes ~9GB VRAM, leaving ~3GB headroom
- **Workloads on the single GPU:**
  - Inference: 13 scans/day × 5-15 stocks × ~30 seconds each = ~65-195 calls/day
  - Training: Weekly Saturday retrain (QLoRA via BitsAndBytes, ~2-3 hours)
  - Council: 5 AI agent sessions/day via Claude API (not local GPU)
  - Overnight: 12 data collectors (CPU-bound, not GPU)
- **Constraint:** GPU utilization target 75% (inference ≤30%, training ≤45%, slack ≥25%)
- **Monthly budget:** Currently ~$64 total operating cost
- **OS:** Windows 11 (defense contractor day job, familiar environment)

## Planned Architecture (from research library)
Halcyon Lab is scaling to a multi-desk, multi-strategy system:

### Desk Architecture
1. **Equity Swing Desk** (Phase 1 — ACTIVE): Pullback-in-uptrend, S&P 100
2. **Equity Swing Desk** (Phase 2): + Mean Reversion (RSI(2)), + universe expansion to ~325 stocks
3. **Equity Swing Desk** (Phase 3): + Evolved PEAD (ML-enhanced earnings composite with FinBERT NLP)
4. **Options Volatility Desk** (Phase 3-4): VRP harvesting, term structure, credit spreads
5. **Equity Momentum Desk** (Phase 5): Longer-horizon momentum strategies
6. **Intraday Desk** (Phase 6+): Sub-daily holding periods, requires different infrastructure

### Model Requirements Per Desk
- Each strategy MAY need its own LoRA adapter (per-strategy fine-tuning)
- Evolved PEAD needs FinBERT on CPU alongside the main model on GPU
- Options desk needs separate feature engine, risk governor, and potentially a different base model
- Research model (for generating training data, scoring, analysis) runs concurrently with production inference
- Council (5-agent deliberation) currently uses Claude API but could run locally with a larger model

### Other GPU Workloads
- **GRPO reinforcement learning** (planned at 100+ closed trades): requires significant VRAM, currently blocked on RTX 3060
- **Walk-forward backtesting**: computationally intensive, benefits from parallel execution
- **Training data generation**: Claude API currently, but could use local model for cost savings
- **FinBERT inference**: ONNX INT8 on CPU (~1 sec/document), but GPU would be faster for batch processing

## Questions — Explore ALL of These in Detail

### 1. The Upgrade Path: What Does Each GPU Unlock?
Map every realistic GPU upgrade to the specific capabilities it enables:

- **RTX 3060 12GB (current):** What's the maximum I can do? How many strategies, what model sizes, what training techniques?
- **RTX 3090 24GB (planned next step, ~$800 used):** What does doubling VRAM unlock? Qwen 14B? GRPO training? Concurrent inference + training?
- **RTX 4090 24GB (~$1,600):** Same VRAM as 3090 but faster. When does the speed difference matter vs just more VRAM?
- **RTX 5090 32GB (~$2,000+):** When does 32GB become necessary? What model sizes and training techniques require it?
- **Dual GPU setups:** NVLink vs non-NVLink. Can two 3090s serve different desks independently? Can they pool VRAM for larger models? What's the practical overhead?
- **Used server GPUs (A100 40/80GB, H100):** At what scale does datacenter hardware make sense for a solo operator? Power requirements, noise, cooling?

### 2. Multi-GPU Architecture for Multi-Desk Trading
In the ideal multi-desk architecture, how should GPUs be assigned?

- **Option A: Shared GPU, time-sliced** — All desks share one GPU, inference scheduled sequentially. When does this break down?
- **Option B: Dedicated GPU per desk** — Each desk gets its own GPU for guaranteed latency. Cost vs benefit analysis.
- **Option C: Functional split** — One GPU for inference (all desks), one for training/GRPO, one for research. When does this make sense?
- **Option D: Hybrid** — Primary GPU for production inference, secondary for training + research, overflow to cloud. Cost modeling.

For each option: max strategies supported, latency characteristics, failure modes, cost.

### 3. The Research GPU
I want a dedicated capability for:
- Running experimental models without affecting production inference
- Generating training data locally (replacing Claude API calls)
- A/B testing new LoRA adapters before deployment
- Walk-forward backtesting with LLM-in-the-loop
- Fine-tuning experiments (hyperparameter sweeps, curriculum learning)

What GPU does the research workload need? Can it be a cheaper/older card? Does it need to run the same model size as production, or can it run a smaller model for experimentation?

### 4. Multi-LoRA Serving Architecture
Research says llama-server (not Ollama) is optimal for multi-adapter serving:
- Pre-loaded adapters with per-request selection
- ~10-50ms swap latency, ~1-2s KV cache invalidation
- At rank 16, each adapter is ~34MB vs 8.7GB base model

Questions:
- How many concurrent LoRA adapters can realistically serve on each GPU tier?
- What's the maximum number of strategies (adapters) before you need a second GPU?
- Does adapter hot-swapping work across desks with different timing requirements?
- vLLM vs llama-server vs TGI for multi-LoRA in 2026 — which is most mature on consumer hardware?

### 5. CPU Workloads That Don't Need GPU
Identify everything that should run on CPU to free GPU headroom:
- FinBERT (ONNX INT8) — confirmed viable on CPU
- Data collection (12 overnight collectors)
- Feature engineering (pandas/numpy)
- Risk calculations
- What else? NLI verification? Embedding models? Sentiment analysis?

What CPU matters? Does hyperthreading help? Does more RAM help? Is there a case for a dedicated CPU-only server for data processing?

### 6. Network Architecture for Multi-Machine Setup
At what point does a single machine become insufficient? When you go multi-machine:
- Local network (two machines on same desk) vs cloud GPU instances
- How to share the SQLite database across machines? Or migrate to PostgreSQL?
- API-based model serving (one machine serves models, another runs the trading system)
- Latency requirements for trading decisions — what's acceptable?
- RunPod, Lambda Labs, Vast.ai for burst GPU compute (training, backtesting) — cost comparison with owned hardware

### 7. The "Infinite Money" Ideal Architecture
If cost were no object, what would the ideal hardware deployment look like for a 6-desk AI trading system operated by one person?
- How many GPUs, what models, what roles
- Which workloads are cloud vs local
- Redundancy and failover
- Power, cooling, noise considerations for a home office
- Total cost estimate (hardware + monthly operating)

### 8. The Practical Solo Operator Architecture
Now constrain to reality: one person, home office, $5K-$20K hardware budget over 2 years, residential power.
- What's the highest-leverage single upgrade from RTX 3060?
- What's the optimal 2-GPU setup for $2K-$4K?
- At what AUM does hardware investment pay for itself?
- Build vs buy (own hardware vs cloud GPU rental) crossover point
- Power consumption and electrical considerations (typical home circuit limitations)

### 9. Windows vs Linux for Multi-GPU Trading
I'm on Windows 11. The research says:
- Ollama has VRAM fragmentation issues on Windows requiring daily restarts
- CUDA/cuDNN sometimes has Windows-specific bugs
- Docker + GPU passthrough is simpler on Linux
- Some ML frameworks (DeepSpeed, Megatron) are Linux-only

At what complexity level should I switch to Linux? Can I run a Linux VM with GPU passthrough? WSL2 with CUDA? Or is a dedicated Linux machine for ML workloads the right answer?

### 10. Future-Proofing: What Changes in 2027-2028?
- Are consumer GPUs trending toward more VRAM? (3060 12GB → 5060 expected specs?)
- Will inference-optimized chips (Groq, Cerebras) become available for local deployment?
- Apple Silicon trajectory — does the unified memory architecture eventually become competitive for inference?
- NVIDIA's roadmap: Blackwell for consumers? When does 48GB become a consumer price point?
- Model efficiency trends: will 4B models match today's 8B quality? Will 1B models be sufficient for structured tasks?

## Output Format
For each section, provide:
1. Concrete hardware recommendations with exact model numbers and current prices
2. Performance benchmarks (tokens/sec, training time, VRAM usage) for relevant GPU + model combinations
3. Cost-benefit analysis with break-even calculations where applicable
4. Risk assessment (what breaks if this hardware fails?)
5. Migration path (how to get from current state to recommended state without downtime)

I want to build a 5-year hardware roadmap that maps each upgrade to a specific capability unlock, with clear decision criteria for when to pull the trigger on each investment.
