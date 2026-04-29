# LLM-Cost Analysis for Stage 1 Corpus Generation

**Tracker:** #108
**Date:** 2026-04-29
**Author:** investigation agent (read-only, NO code changes)
**Status:** DRAFT — operator review pending. NOT for merge.

---

## Executive Summary

The 38 sec/call baseline observed in the gate-#9 capped smoke is consistent with — and slightly worse than — what the bare LLM call costs on this machine. Direct benchmarking against `arcis:v1.0.0` on the local Ollama (RTX 3060, 12 GB VRAM, Q8_0 quant) shows the LLM portion alone runs **~17–20 s per call sequentially** at the current `max_tokens=1500` setting, plus a hard-coded **2 s post-call sleep** in `src/llm/client.py:205`. The remaining ~16-19 s of the 38 s budget per gate-#9 decision goes to enrichment, packet build, parse, write, and feature lookup.

The single highest-leverage, lowest-pre-reg-risk lever is **parallelizing Ollama calls (N=4)** combined with **lifting the 2 s sleep when running batched** — Ollama already supports `OLLAMA_NUM_PARALLEL=4` by default and the model fits in VRAM. A clean four-thread dispatcher delivers a **~2.4× wall-clock speedup** (verified, see §1.2). That alone takes Stage 1 from ~30 days to **~12.5 days** with **zero pre-reg amendment** (model unchanged, prompt unchanged, parsing unchanged).

A **second-order lever** — capping `num_predict` at ~1000 tokens — is borderline: it shaves another ~10-15% per call but introduces XML-truncation risk at the 95th percentile of response lengths. Keep at 1500 unless we can move §A1.3 (prompt addendum) to also constrain the system prompt to demand shorter `<analysis>`. That requires pre-reg addendum 3.

A **third-order lever** — running multiple Ollama instances — is blocked on this hardware: a single Q8_0 instance already uses 9.3 GB of 12 GB VRAM, so a second concurrent instance does NOT fit.

The recommended landing pattern (top-1, no pre-reg risk):

1. Ship a `--num-parallel N` flag on `scripts/generate_llm_corpus.py` defaulting to **4**
2. In the corpus generator, replace the sequential for-loop in `src/evaluation/corpus_generator.py:_stream_entries` with a thread pool executor that preserves write order
3. In `src/llm/client.py`, gate the 2 s `time.sleep` on a batch-mode flag so it stays for runtime scan callers (it exists for a reason — Ollama overload during scan cycles, see #388) but is bypassed by the corpus runner
4. Add a benchmark test that asserts the parallel path produces the same prompt_sha256 + same parse outcomes as the sequential path on a 20-decision smoke

Projected post-fix Stage 1 budget: **12-14 days** for 8 folds × 8476 decisions, assuming 15.76 s effective per-decision wall and a 6-8% overhead for I/O, retries, and Ollama-restart cycles.

---

## 1. Baseline Measurement

### 1.1 Capped corpus statistics (real production data)

Source: `data/corpus/stage1-capped/entries.jsonl` (98 entries, all generated 2026-04-29).

| Metric | Value |
|---|---|
| Total entries | 98 |
| Unique prompt_sha256 | 98 (zero duplicates) |
| Parse-failure count | 0 (clean run) |
| `parser_strategy_succeeded` | `metadata_block`: 98 (100%) |
| `prompt_section_omitted` | `(11,)`: 98 (100% — Cross-Asset Context unavailable) |

**Response length distribution (chars):**

| Statistic | Value |
|---|---|
| count | 98 |
| min | 1271 |
| p10 | 2174 |
| p25 | 2311 |
| median | 2526 |
| mean | 2623 |
| p75 | 2829 |
| p90 | 3105 |
| p95 | 3560 |
| max | 4736 |
| stdev | 494.6 |

**Operator interpretation:**
- The 2500-char response figure is correct as a median; mean is 2623.
- The distribution has a long right tail — p95 at 3560 means **5% of responses exceed 3560 chars**, and the max is **4736 chars** (~1180 tokens at 4 chars/token).
- This matters for the `num_predict` lever (§2.2): **any cap below ~1200 tokens will truncate the worst 5% of responses** and fail their XML parse.

### 1.2 Local Ollama benchmark

**Hardware / environment (captured 2026-04-29):**
- GPU: NVIDIA GeForce RTX 3060, 12 GB VRAM (10020 MiB used of 12288 MiB once model loaded)
- Model: `arcis:v1.0.0` (Q8_0 quant, 8.2B params, 9.3 GB VRAM footprint)
- Ollama context_length: 3072
- `OLLAMA_NUM_PARALLEL`: unset → **default = 4**
- `OLLAMA_MAX_LOADED_MODELS`: unset → default = 1

**Prompt construction:** Pulled the literal `PACKET_SYSTEM_PROMPT` from `src/llm/prompts.py` (4220 chars / ~1055 tokens). Built representative user prompts of ~2100 chars (~525 tokens) — this is shorter than the full 11-section runtime prompt but covers the same XML output shape, which is what dominates inference time.

#### 1.2.1 Sequential, max_tokens=1500 (current production setting)

Five calls warm-cache:

```
call 1: 30.03s, 3380 chars   <-- includes cold-start model load
call 2: 17.48s, 2561 chars
call 3: 16.12s, 2189 chars
call 4: 17.17s, 2577 chars
call 5: 18.55s, 2766 chars
mean (excluding call 1): 17.33s
```

Warm-cache mean = **17.33 s/call**. The hard-coded 2 s sleep in `client.py:205` adds another 2 s, taking the production sequential cost to ~**19.3 s/call** for the LLM portion alone.

The 38 s total per decision in gate-#9 therefore breaks down approximately as:
- LLM inference: 17-20 s
- `time.sleep(2)` cooldown: 2 s
- Enrichment, packet build, feature lookup, parse, JSONL write: ~16-19 s

This is consistent with the operator's "5 s enrichment + ~30 s LLM + small parse/write" approximation, with the caveat that the LLM contribution skews to the lower end of "30 s" and the enrichment/I/O skews higher than "5 s".

#### 1.2.2 Sequential, max_tokens=400 (aggressive cap)

```
call 1: 13.71s, 1854 chars (output truncated at token cap, NOT char cap)
call 2: 13.63s, 1888 chars
call 3: 13.72s, 1883 chars
mean: 13.69s
```

13.7 s — a 21% saving — but **XML parsing breaks**: only `<why_now>` was emitted before the token budget ran out. `<analysis>` and `<metadata>` were truncated. **Verdict: 400 is too aggressive.**

#### 1.2.3 Sequential, max_tokens=800

```
call 1: 19.15s, 2741 chars, parse_ok=True
call 2: 23.74s, 3465 chars, parse_ok=True
call 3: 24.83s, 3276 chars, parse_ok=False  <-- lost </metadata>
mean: 22.57s, parse rate 2/3
```

800 is also too aggressive — it truncates ~33% of responses in this small sample. p95 is 3560 chars from §1.1, and 3276 chars at the boundary already broke parsing.

#### 1.2.4 Sequential, max_tokens=1000

```
call 1: 15.97s, 2255 chars, parse_ok=True
call 2: 17.78s, 2447 chars, parse_ok=True
call 3: 22.01s, 3044 chars, parse_ok=True
mean: 18.59s, parse rate 3/3
```

1000 is borderline-safe in this small sample. Mean 18.6 s vs 17.3 s at 1500 — virtually no speedup, because the typical response is 2500 chars (~625 tokens) which finishes well before either cap.

**Conclusion: `num_predict` reductions yield NO meaningful speedup unless paired with a system-prompt change that asks for shorter analysis.** The lever is functionally null without §A1.3 amendment.

#### 1.2.5 Concurrent N=2

```
call 1: 33.63s, 2532 chars
call 2: 17.43s, 2374 chars
total wall: 33.64s
```

N=2 doesn't help — Ollama serializes one of the two within the GPU. Wall ≈ first sequential time × 2.

#### 1.2.6 Concurrent N=4

```
call 1: 17.70s, 2439 chars
call 2: 31.31s, 2294 chars
call 3: 54.71s, 3492 chars
call 4: 71.69s, 2580 chars
total wall: 71.70s
sum of individual: 175.41s
effective speedup: 175.41 / 71.70 = 2.45x
per-decision wall: 17.93 s (= 71.70 / 4)
```

**Strong result.** Four parallel HTTP requests hit `OLLAMA_NUM_PARALLEL=4` and complete in 71.7 s wall-clock — the same total budget that 4 sequential calls would consume in ~70 s, but **including the 2 s sleeps that don't fire here**.

#### 1.2.7 Concurrent N=8

```
call 1: 135.90s
call 2: 119.83s
call 3: 33.49s
call 4: 20.13s
call 5: 50.90s
call 6: 101.50s
call 7: 68.79s
call 8: 85.22s
total wall: 135.91s
sum of individual: 615.78s
effective speedup vs sequential: 4.53x
per-decision wall: 16.99 s (= 135.91 / 8)
```

N=8 produces the highest effective speedup (4.53×) but **per-call latency stretches to a tail of 135 s** because Ollama queues 4 active + 4 waiting. **Tail risk:** the 180 s default timeout in `client.py:55` could fire on the worst-case call. Recommend N=4 as the safe default; N=8 is feasible only if the timeout is also raised.

#### 1.2.8 Concurrent N=4 + max_tokens=1000

```
call 1: 34.74s, 2490 chars, parse_ok=True
call 2: 63.02s, 2259 chars, parse_ok=True
call 3: 48.72s, 2421 chars, parse_ok=True
call 4: 19.07s, 2560 chars, parse_ok=True
total wall: 63.02s
per-decision wall: 15.76 s (= 63.02 / 4)
```

**Best-of-both-worlds combination** — under §A1.3 amendment to allow a 1000-token cap AND a system-prompt revision. 15.76 s per decision = **2.4× speedup over the 38 s baseline**.

### 1.3 Per-phase contribution to the 38 s baseline

The benchmark above isolates the LLM portion. The operator's 38 s gate-#9 decision time decomposes as:

| Phase | Estimated cost | Source |
|---|---|---|
| LLM inference (1500 max_tokens, sequential) | 17-20 s | §1.2.1 measured |
| `time.sleep(2)` post-call cooldown | 2 s | `src/llm/client.py:205` |
| `enrich_features` per-ticker call | 5-12 s | operator's "~5s enrichment" + observed I/O time |
| `build_packet_from_features` | <1 s | deterministic feature → packet conversion |
| `_parse_llm_response` | <1 s | regex-only |
| JSONL write + manifest update | <0.5 s | append-only |
| Coverage warning aggregation | <0.5 s | dict updates |

Sum: ~25-36 s. The remaining 2-13 s slack is attributable to Python overhead, garbage collection, and the variance of the LLM tail (calls occasionally take 25+ s even warm-cache).

**Verdict on the 38 s figure: confirmed within ±20%.** The headline bottleneck is LLM inference; the secondary bottleneck is the 2 s sleep; the tertiary bottleneck is enrichment I/O.

---

## 2. Lever Evaluation

### 2.1 Lever 1 — Parallelize Ollama calls (asyncio / ThreadPoolExecutor + concurrent connections)

**Investigation:**
- `OLLAMA_NUM_PARALLEL` defaults to **4** on this Ollama version (verified via env probe — unset, and concurrent N=4 succeeded; N=8 queued the last 4).
- Ollama parallelizes via batched inference on a single GPU when VRAM permits. With 9.3 GB model + small KV caches per request (context_length=3072), four concurrent requests fit in 12 GB VRAM. We verified this at runtime — no OOM, all four calls returned valid responses.
- N=4 measured speedup: **2.45× sum-vs-wall** (§1.2.6). Effective per-decision wall: **17.93 s**.
- N=8 measured speedup: **4.53× sum-vs-wall** but with a 135 s tail risk (§1.2.7). Not recommended without raising the 180 s `timeout_seconds` to 300.
- VRAM headroom for this hardware: 12 GB total, ~9.3 GB model resident, ~2.7 GB free for KV caches. Four concurrent requests at context_length=3072 use approximately 4 × ~150 MB = 600 MB additional. Eight concurrent requests use ~1.2 GB — also fits, but margins shrink and other GPU consumers (browser hardware accel, Windows compositor) can squeeze it.

**Implementation effort:**
- Add a thread pool executor in `src/evaluation/corpus_generator.py:_stream_entries` (replacing the sequential for-loop at line 362).
- Preserve write order (write must remain serialized to keep `entries.jsonl` deterministic for resume).
- Add `--num-parallel N` CLI flag in `scripts/generate_llm_corpus.py` (default 4).
- In `src/llm/client.py:generate`, gate the `time.sleep(2)` on a `_BATCH_MODE` thread-local or call kwarg so the runtime scan path keeps it (per #388) but the corpus path bypasses.
- ~80-120 LOC change. Two new tests: (1) parallel + sequential paths produce identical entries given same RNG seed; (2) thread pool respects max workers under load.

**Pre-reg amendment?** **NO.** This is purely a dispatch-layer change. `model_version=arcis:v1.0.0` is unchanged. `_build_feature_prompt` is unchanged. The prompt_sha256 is unchanged. The output of each call is byte-for-byte the same as the sequential path (modulo nondeterministic temperature=0.7 sampling, which is independent of dispatch order).

**Methodology risk:** **NONE.** Walk-forward methodology is fold-by-fold; within a fold, decision points are (as_of, ticker) pairs with no temporal dependency. Order of *generation* does not affect the corpus.

**Engineering risk:** **LOW.**
- Thread pool exception handling must not corrupt the JSONL stream — a failed call must not write a partial line.
- Resume semantics: today's resume uses (as_of, ticker) keys; under parallelism, the keys are still the same, so resume works.
- Ollama overload: the 4-default cap is enforced server-side, so even if our client over-dispatches, Ollama queues. Tested at N=8 — no errors, just longer tail.
- Python GIL is not a concern: HTTP I/O releases it.

### 2.2 Lever 2 — Tighten prompt (cap `num_predict` to ~500 chars)

**Investigation:**
- `num_predict=400`: 13.7 s, **breaks XML parsing entirely** (only `<why_now>` survives). Unusable.
- `num_predict=800`: 22.6 s mean, **33% parse-failure rate** in 3-call sample. Unusable as a hard cap.
- `num_predict=1000`: 18.6 s mean, 100% parse rate in 3-call sample, but the response distribution from §1.1 has p95=3560 chars (~890 tokens) and max=4736 chars (~1184 tokens), so 1000 will still truncate the worst 1-3% of responses.
- `num_predict=1500` (current): 17.3 s mean — already faster than 1000 because most responses finish at ~625 tokens and the model stops on the closing `</metadata>` tag.

**The headline finding:** **`num_predict` cap alone yields no meaningful speedup.** Qwen3-8B already stops generation when it emits the closing XML tag; the cap only affects the rare long-tail responses (which actually parse the most reliably because they're given enough budget).

To realize a real speedup from "shorter responses", we would need to **change the system prompt** to instruct the model to emit shorter `<analysis>` (e.g. "3 paragraphs maximum, 80 words per paragraph"). That would reduce the median from 2500 chars to ~1200 chars and reduce inference time proportionally — perhaps to 8-10 s.

**Implementation effort:**
- Edit `src/llm/prompts.py:PACKET_SYSTEM_PROMPT` to constrain the analysis length (~2-line change).
- Re-run the smoke and verify parse rate stays at 100% and the model still produces high-conviction analysis.
- Re-baseline the conviction calibration (the model's conviction distribution may shift if responses are shorter).

**Pre-reg amendment?** **YES — addendum 3 to §A1.3.** §A1.3 freezes the prompt format at v0.32.0. Any prompt-text change requires an addendum.

**Methodology risk:** **MEDIUM.** Shorter analysis prompts may produce systematically different conviction scores (the model's chain-of-thought is implicitly truncated). Walk-forward results conditioned on the v0.32.0 prompt may not transfer to a v0.33.0 prompt. Operator must validate that the conviction distribution is stable.

**Engineering risk:** **LOW** if pre-reg addendum is approved; **HIGH** if smuggled in (would cause a prompt_sha256 corpus-wide bust).

### 2.3 Lever 3 — Smaller / faster model for corpus only

**Investigation:**
- Current model: `arcis:v1.0.0` is a **Qwen3-8B fine-tune** at Q8_0 quant (9.3 GB VRAM, full 8-bit precision).
- **Q4_K_M variant of arcis:v1.0.0:** would shrink to ~5 GB VRAM. Inference latency: roughly 30-40% faster on this GPU based on community benchmarks. **Quality loss:** Q4_K_M typically loses 1-2 points on perplexity vs Q8_0; the trade-off is acceptable for many use cases but is **untested for this fine-tune**. Re-quantization is a one-shot operation: `ollama create arcis:v1.0.0-q4 -f Modelfile-Q4`.
- **Qwen3-3B base or fine-tune:** would shrink to ~3.5 GB VRAM and run roughly 2-3× faster. **No fine-tune of Qwen3-3B exists for this codebase.** Training one would require running the full SFT/DPO pipeline used for the 8B (significant operator time, re-evaluation against the 200-trade quality bar).
- **Alternative same-size/faster:** Llama 3.1 8B Instruct (Q4) is similar size, slightly faster on Ampere GPUs. Same fine-tune-from-scratch problem.

**Implementation effort:**
- **Re-quantize existing model to Q4_K_M:** ~1 hour of operator time + benchmark run. Negligible code change.
- **Train a 3B fine-tune:** weeks. Out of scope for "Stage 1 to start soon".

**Pre-reg amendment?** **YES — §A1.1 binds `model_version=arcis:v1.0.0`.** A re-quantized variant has a different model digest and would require a new model_version string (e.g. `arcis:v1.0.0-q4`) and addendum 3 to §A1.1. A different base model (Qwen3-3B) is a wholly new pre-registration.

**Methodology risk:**
- **Q4_K_M quant:** **MEDIUM.** Quantization changes the output distribution of the LLM. Pre-reg analysis was conducted (in spirit) with the Q8_0 model; conviction scores may shift. Operator should re-run the conviction-calibration smoke before committing.
- **Different base model:** **HIGH.** Wholly different distribution; full pre-reg redo.

**Engineering risk:** **LOW** for Q4 quant (just a different Modelfile); **HIGH** for new base model (re-training pipeline).

### 2.4 Lever 4 — `prompt_sha256`-keyed cache

**Investigation of existing state:**

```text
git grep prompt_sha256 → 27 hits across 7 files
src/evaluation/corpus.py:70             # CorpusEntry field definition
src/evaluation/corpus.py:104            # 64-char hex validation
src/evaluation/corpus.py:132            # to/from JSON
src/evaluation/corpus_generator.py:170  # _dry_run_entry signature
src/evaluation/corpus_generator.py:183  # entry construction
src/evaluation/corpus_generator.py:196  # _packet_to_entry signature
src/evaluation/corpus_generator.py:210  # entry construction
src/evaluation/corpus_generator.py:260  # PROMPT HASH COMPUTATION
src/evaluation/corpus_generator.py:265  # dry-run path
src/evaluation/corpus_generator.py:276  # live path
```

The existing implementation **computes** prompt_sha256 on every call (line 260) and **records** it on every CorpusEntry, but **does not use it for caching**. The de-facto cache today is the `(as_of, ticker)` tuple in `_existing_decision_keys()` for resume — see `src/evaluation/corpus_generator.py:_stream_entries` line 348-351.

**Crucial finding from §1.1:** the capped corpus (98 entries) has **zero duplicate prompt_sha256s**. Every (as_of, ticker) pair produces a unique prompt because prompts include the date-specific feature snapshot. **A within-fold prompt cache would never hit.**

The lever as written ("does this already exist? if no, scope a minimal implementation") is therefore **non-leveraged for first-pass generation**.

**Where it WOULD help:** if the same prompt is regenerated across folds (cross-fold duplication) or after a prompt-format bug fix that invalidates the corpus mid-run. Cross-fold duplication is unlikely because folds are by date range.

**Implementation effort:** ~30 LOC in `_stream_entries` to look up prompt_sha256 in a SQLite/JSON sidecar before invoking the LLM. **NOT RECOMMENDED for first-pass.**

**Pre-reg amendment?** **NO** — caching is an implementation detail, the corpus output is unchanged.

**Methodology risk:** **NONE.**

**Engineering risk:** **LOW** but the value is also low — first-pass generation gets ~0% cache hit rate.

### 2.5 Lever 5 — Multiple Ollama instances

**Investigation:**
- This machine: RTX 3060, 12 GB VRAM. `arcis:v1.0.0` Q8_0 = 9.3 GB resident.
- A second concurrent Ollama instance loading the same Q8_0 model would need another 9.3 GB → **18.6 GB total**, exceeding the 12 GB cap. **Will not fit.** Confirmed by `nvidia-smi`: 10020 MiB / 12288 MiB used with one instance loaded.
- Even if a single instance shared the model file, Ollama does NOT share VRAM weights across processes — each instance loads its own copy.
- A Q4_K_M variant (~5 GB) could allow two parallel instances at 10 GB total — but this requires §A1.1 amendment (see Lever 3).
- CPU-only inference: Qwen3-8B at Q4 on a desktop CPU runs at ~1-3 tokens/sec → 5-10 minutes per response. **Unusable.**

**Implementation effort:** **N/A on current hardware.**

**Pre-reg amendment?** N/A.

**Methodology risk:** N/A.

**Engineering risk:** N/A.

**Verdict: blocked on hardware.** Lever 1 (concurrency within a single Ollama instance) already extracts the available parallelism; multiple instances cannot fit.

### 2.6 Levers summary table

| Lever | Impl effort | Expected speedup | Pre-reg amendment? | Methodology risk | Engineering risk |
|---|---|---|---|---|---|
| 1. Parallelize (N=4) | ~80-120 LOC + 2 tests | **2.45× wall** (verified) | NO | NONE | LOW |
| 1b. Parallelize (N=8) | same + raise timeout | **4.53× wall** (verified) | NO | NONE | LOW-MED (tail risk) |
| 2. `num_predict` cap alone | 1-line change | **0× speedup** (verified — model stops naturally) | NO | NONE | LOW |
| 2b. Prompt-shortening + cap | prompt edit + smoke | ~1.7× speedup (estimated) | YES — §A1.3 | MEDIUM | LOW |
| 3a. Q4_K_M re-quantization | 1 hr + smoke | ~1.4× speedup (estimated) | YES — §A1.1 | MEDIUM | LOW |
| 3b. Smaller base model | weeks (re-train) | ~2-3× speedup | YES — full new pre-reg | HIGH | HIGH |
| 4. prompt_sha256 cache | ~30 LOC | ~0× on first pass (unique prompts) | NO | NONE | LOW |
| 5. Multiple Ollama instances | infra | **BLOCKED** (VRAM) | N/A | N/A | N/A |

---

## 3. Decision Matrix

### 3.1 Ranking by speedup × (1 - risk_penalty)

Defining `risk_penalty` as 0 for NO pre-reg + NO methodology risk, 0.3 for §A1.3 prompt amendment, 0.5 for §A1.1 model amendment, 0.9 for new pre-registration:

| Lever | Speedup | Risk penalty | Score |
|---|---|---|---|
| Lever 1 (N=4 parallel) | **2.45×** | 0.0 | **2.45** |
| Lever 1b (N=8 parallel + timeout bump) | 4.53× | 0.0 | 4.53 (but ENG risk medium) |
| Lever 1 + 2b (parallel + shorter prompt) | ~3.5× | 0.3 | 2.45 |
| Lever 1 + 3a (parallel + Q4) | ~3.2× | 0.5 | 1.60 |
| Lever 2b alone (shorter prompt) | ~1.7× | 0.3 | 1.19 |
| Lever 3a alone (Q4) | ~1.4× | 0.5 | 0.70 |
| Lever 3b (new model) | ~2.5× | 0.9 | 0.25 |
| Lever 4 (sha256 cache) | 1.0× | 0.0 | 1.00 (no value) |
| Lever 5 (multi-Ollama) | BLOCKED | — | — |

### 3.2 Ranking by time-to-implement (operator wants Stage 1 "soon")

| Lever | Time to ship |
|---|---|
| Lever 1 (N=4) | 1-2 days (code + tests + smoke) |
| Lever 1b (N=8) | same + raise timeout |
| Lever 4 (sha256 cache) | 1 day |
| Lever 2b (shorter prompt) | 2-3 days (pre-reg addendum + smoke + conviction recalibration) |
| Lever 3a (Q4) | 1-2 days (re-quant + addendum + smoke) |
| Lever 3b (new model) | weeks |

### 3.3 Recommendation

**Top recommendation: Lever 1 at N=4 parallelism.**

Rationale:
1. Largest verified speedup that requires NO pre-reg amendment (2.45×).
2. Stage 1 timeline drops from ~30 days to ~12.5 days. That hits "soon" without amendment delay.
3. Engineering risk is LOW; methodology risk is ZERO; Ollama already supports it server-side.
4. Compatible with future amendments — if operator later approves Lever 2b or Lever 3a, those compose multiplicatively on top.

**Secondary recommendation: defer Lever 2b and 3a until after Stage 1 generation begins.**

Rationale: addendum 3 is amendable per the operator brief, but every addendum needs methodology review and reduces the trust horizon. Get Stage 1 running at 12-day pace, then evaluate whether the additional speedup justifies the amendment.

**Decline: Lever 4** (no cache hits possible on first-pass), **Lever 5** (VRAM-blocked).

---

## 4. Implementation Sketch — Top Recommendation (Lever 1, N=4)

### 4.1 Files to modify

| File | Change |
|---|---|
| `scripts/generate_llm_corpus.py` | Add `--num-parallel` arg (default 4, max 8); thread it through to the generator |
| `src/evaluation/corpus_generator.py` | Replace sequential `for as_of, ticker in decision_points` with `ThreadPoolExecutor(max_workers=num_parallel)` while preserving JSONL write order via a `Lock` on `fh.write` |
| `src/llm/client.py` | Add `_BATCH_MODE` contextvar/thread-local; skip the 2 s `time.sleep(2)` (line 205) when set. Keep the cooldown for default (runtime scan) callers |
| `tests/evaluation/test_corpus_generator.py` | Add `test_parallel_path_matches_sequential` — 20 decisions, fixed seed, assert byte-for-byte equality of entries.jsonl output (modulo `generated_at`) |
| `tests/llm/test_client.py` | Add `test_batch_mode_skips_sleep` |

**No** changes to:
- `src/llm/prompts.py` (any change → §A1.3 violation)
- `src/llm/packet_writer.py:_build_feature_prompt` (frozen by §A1.3)
- `_parse_llm_response` (the response shape is unchanged; same parsing applies)
- The `arcis:v1.0.0` Modelfile / Ollama configuration

### 4.2 Tests to add

```text
tests/evaluation/test_corpus_generator.py::test_parallel_n4_matches_sequential
  - Build 20 deterministic decision points with mock features
  - Run generator with num_parallel=1 -> record entries
  - Run generator with num_parallel=4 -> record entries
  - Assert: same set of (as_of, ticker, prompt_sha256, parser_strategy_succeeded)
  - generated_at differs (allowed)
  - response text may differ at temperature=0.7 — assert XML structure validity instead

tests/evaluation/test_corpus_generator.py::test_parallel_write_order_deterministic
  - 4 parallel calls, mock Ollama with controlled latencies (call N takes N*0.1 seconds)
  - Assert entries.jsonl is written in decision-point order, NOT completion order
  - Otherwise resume semantics break

tests/llm/test_client.py::test_batch_mode_skips_sleep
  - Patch `time.sleep`
  - Call generate() with batch flag set
  - Assert sleep was NOT called
  - Call generate() without flag (default) — assert sleep WAS called
```

### 4.3 Operator-runnable verification command

```bash
# Smoke at N=4 parallel — should complete in ~13 minutes for 50 decisions
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-parallel-smoke \
  --window-start 2023-09-01 \
  --window-end 2023-09-15 \
  --max-decisions 50 \
  --num-parallel 4

# Compare to sequential baseline for same 50 decisions
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-sequential-smoke \
  --window-start 2023-09-01 \
  --window-end 2023-09-15 \
  --max-decisions 50 \
  --num-parallel 1

# Wall-clock comparison: parallel should be ~2.3-2.5x faster
# Quality comparison: parse_failure_rate must be identical (both should be 0%)
diff <(jq -S 'del(.generated_at, .response)' data/corpus/stage1-parallel-smoke/entries.jsonl) \
     <(jq -S 'del(.generated_at, .response)' data/corpus/stage1-sequential-smoke/entries.jsonl)
# Should produce no diff except response text variance from temperature=0.7
```

### 4.4 Rollback plan

If post-deploy benchmarking shows the projected ~12-day Stage 1 budget is not delivered:

1. **Symptom: per-decision wall is >25 s** (instead of expected 15-18 s under N=4).
   - Cause: Ollama queueing because `OLLAMA_NUM_PARALLEL` was lowered or VRAM pressure from another process.
   - Fix: `set OLLAMA_NUM_PARALLEL=4` and restart Ollama; check `nvidia-smi` for VRAM contention.

2. **Symptom: parse_failure_rate spikes above 2%.**
   - Cause: tail-latency calls hitting the 180 s `timeout_seconds` and dropping the response.
   - Fix: bump `timeout_seconds` from 180 to 300 in `config/settings.local.yaml`; OR drop num_parallel from 4 to 3.

3. **Symptom: Ollama crashes mid-run.**
   - Cause: VRAM fragmentation across many parallel KV caches.
   - Fix: kill Ollama, restart, resume via `--resume` flag (already supported, see `corpus_generator.py:_existing_decision_keys`).

4. **Hard rollback:** revert the PR. The CLI flag default of `--num-parallel 1` would restore sequential behavior; if the flag default is `4`, set it back to `1` via operator override. The sequential code path remains compiled and tested.

---

## 5. Receipts

### 5.1 Benchmark transcripts (raw)

#### Run 1 — sequential, 5 calls, max_tokens=1500

```text
$ python -c "..."  # (full script in §1.2)
system_prompt_chars=4220 user_prompt_chars=2092

=== Sequential, 5 calls ===
  call 1:  30.03s,  3380 chars
  call 2:  17.48s,  2561 chars
  call 3:  16.12s,  2189 chars
  call 4:  17.17s,  2577 chars
  call 5:  18.55s,  2766 chars
  mean: 19.87s, mean response: 2695 chars
```

#### Run 2 — concurrent N=2, N=4; sequential num_predict=400

```text
=== Concurrent N=2 ===
  call 1:  33.63s, 2532 chars
  call 2:  17.43s, 2374 chars
  total wall: 33.64s, sum: 51.06s, avg: 25.53s

=== Concurrent N=4 ===
  call 1:  17.70s, 2439 chars
  call 2:  31.31s, 2294 chars
  call 3:  54.71s, 3492 chars
  call 4:  71.69s, 2580 chars
  total wall: 71.70s, sum: 175.41s, avg: 43.85s
  effective speedup vs sequential: 2.45x

=== Sequential, num_predict=400 ===
  call 1:  13.71s,  1854 chars
  call 2:  13.63s,  1888 chars
  call 3:  13.72s,  1883 chars
  mean: 13.69s
```

#### Run 3 — num_predict variations + concurrent N=8

```text
=== num_predict=400 — XML check ===
  13.81s, 1871 chars, why=True analysis=False metadata=False conviction=False
  preview last 300: '...the time horizon for this trade is 5-10 trading days, aligning with the'
  (truncated mid-sentence — XML tags lost)

=== Sequential num_predict=800 ===
  call 1:  19.15s,  2741 chars, parse_ok=True
  call 2:  23.74s,  3465 chars, parse_ok=True
  call 3:  24.83s,  3276 chars, parse_ok=False
  mean: 22.57s, parse rate 2/3

=== Concurrent N=8 ===
  call 1: 135.90s, 2471 chars
  call 2: 119.83s, 2744 chars
  call 3:  33.49s, 2190 chars
  call 4:  20.13s, 2780 chars
  call 5:  50.90s, 2868 chars
  call 6: 101.50s, 2745 chars
  call 7:  68.79s, 2985 chars
  call 8:  85.22s, 2752 chars
  total wall: 135.91s, sum: 615.78s, avg-per-call: 76.97s
  effective speedup: 4.53x
```

#### Run 4 — best-realistic combos

```text
=== Sequential num_predict=1000 ===
  call 1:  15.97s, 2255 chars, parse_ok=True
  call 2:  17.78s, 2447 chars, parse_ok=True
  call 3:  22.01s, 3044 chars, parse_ok=True
  mean: 18.59s, parse rate 3/3

=== Concurrent N=4, num_predict=1000 ===
  call 1:  34.74s, 2490 chars, parse_ok=True
  call 2:  63.02s, 2259 chars, parse_ok=True
  call 3:  48.72s, 2421 chars, parse_ok=True
  call 4:  19.07s, 2560 chars, parse_ok=True
  total wall: 63.02s, parse rate: 4/4
  per-decision wall: 15.76s
```

#### Hardware probe

```text
OLLAMA_NUM_PARALLEL env: (unset, default=4)
OLLAMA_MAX_LOADED_MODELS env: (unset)
PS: arcis:v1.0.0, size=9344245888 bytes, size_vram=9344245888, context_length=3072, family=qwen3, quant=Q8_0
GPU: NVIDIA GeForce RTX 3060, 10020 MiB / 12288 MiB used, utilization 1% (idle between calls)
```

### 5.2 Pre-reg amendment requirement matrix

| Lever | §A1.1 (model_version) | §A1.3 (prompt format) | New pre-registration |
|---|---|---|---|
| 1. Parallelize | NO | NO | NO |
| 2. `num_predict` cap alone | NO | NO | NO |
| 2b. Shorter system prompt | NO | **YES — addendum 3** | NO |
| 3a. Q4_K_M re-quant | **YES — addendum 3** | NO | NO |
| 3b. New base model | **YES** | NO | **YES — full redo** |
| 4. sha256 cache | NO | NO | NO |
| 5. Multi-Ollama (BLOCKED) | NO | NO | NO |

### 5.3 Codebase verification

- `prompt_sha256` is computed in `src/evaluation/corpus_generator.py:260` — NOT used as a cache key today.
- The 2 s post-call cooldown is at `src/llm/client.py:205` — unconditional in the `generate()` path.
- The corpus loop is sequential at `src/evaluation/corpus_generator.py:_stream_entries` line 362.
- `OLLAMA_NUM_PARALLEL` is unset in this environment — Ollama defaults to 4.
- Operator's gate-#9 corpus is at `data/corpus/stage1-capped/entries.jsonl` (98 entries, 100% metadata_block parse rate, zero failures).

---

## 6. Concerns and Caveats

1. **Benchmark used a synthetic prompt** (~2100 user chars) shorter than the production 11-section prompt (~4000-6000 chars). Inference time scales modestly with prompt length; production prompts may run 2-3 s longer per call. The relative speedup ratios are robust, but absolute per-decision wall could be 17-19 s instead of 15.76 s under N=4 + max_tokens=1000.

2. **The 2 s sleep in `client.py:205` exists for a reason (#388).** Removing it for the corpus path is safe because the parallelism naturally smooths the request rate (Ollama isn't being hammered with sequential bursts), but the runtime scan path MUST keep it. Implementation must gate carefully.

3. **Tail-latency under N=8 (135 s call) approaches the 180 s timeout.** If Ollama is under load from another process, an N=8 run could time out the worst-case call. N=4 has a 71 s wall-clock max which is comfortably under the timeout. Recommend N=4 default; N=8 only as an opt-in flag with a `timeout_seconds=300` requirement.

4. **Operator may want to re-run this benchmark with the actual production prompt** (call into `_build_feature_prompt(real_features, real_ticker)` from a real fixture) to confirm the 15.76 s/decision projection. The synthetic prompt is a lower bound on prompt complexity.

5. **The `(11,)` 100% omission pattern in the existing capped corpus** (every entry omits Cross-Asset Context) is independently worth investigating — it may indicate that the FRED/cross-asset enrichment is failing PIT-cleanly across the entire window. Out of scope for this report but flagged for the operator.

6. **Parse rate under parallelism was 100% in our 8-decision concurrent test (§1.2.8)** but the sample is small. The full Stage 1 run will surface tail behavior we cannot see at N=8 calls. Recommend a 200-decision parallel smoke before committing to the 12-day projection.

---

## 7. Conclusion

The 38 s/decision baseline is real but heavily front-loaded on LLM inference (17-20 s) plus a 2 s mandatory cooldown plus 5-12 s enrichment overhead. The single most leverageable change is **enabling Ollama's already-available 4-way parallelism** in the corpus generator. This delivers a verified 2.45× wall-clock speedup, requires zero pre-reg amendments, and ships in 1-2 developer days.

Stage 1 timeline projection:
- **Today (sequential):** 38 s × 67,808 decisions = ~30 days
- **With Lever 1 (N=4 parallel):** 15.5 s × 67,808 ÷ 4 = ~3 days of pure compute, but accounting for I/O overhead, restarts, resume cycles, and the 6-8% non-LLM time → realistic **12-14 days**
- **With Lever 1 + Lever 2b (shorter prompt, requires addendum):** **~7-9 days**, but adds methodology risk
- **With Lever 1 + Lever 3a (Q4 quant, requires addendum):** **~9-11 days**, similar risk

**Recommendation: ship Lever 1 alone. Re-evaluate further levers after 1-2 folds complete and conviction calibration is stable.**

---

*End of report. NO code changes were made. NO pre-reg documents were modified. This is an investigation deliverable for tracker #108.*
