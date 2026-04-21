# Cleanup Sprint 3 — Pass 2 Research

**Branch:** `docs/cleanup-sprint-3-strategic-specs`
**Base:** `main` @ `f01d8b4b`
**Prereq:** `cleanup_sprint_3_evaluation.md` (Pass 1, commit `ff3157d`)

Targeted reads against project-knowledge docs to validate the contents
that Pass 3 will draft into each of the 4 strategic specs. Not an
exhaustive search — per prompt anti-goal, each spec targets specific
named docs.

---

## Spec 1 — Evaluation harness — validation of proposed contents

### Rubric weights (from `docs/research/ARCIS_RESEARCH_FRAMEWORK.md`)

Confirmed 6-dimension gold-standard rubric, summing to 100%:

| Dimension | Weight | What it measures |
|---|---|---|
| Thesis clarity | 25% | Clear, falsifiable directional thesis |
| Evidence grounding | 20% | Claims supported by specific data points |
| Risk identification | 20% | Identifies what could go wrong |
| Catalyst awareness | 15% | Upcoming events that could affect thesis |
| Quantitative precision | 10% | Specific numbers, not vague qualitative claims |
| Internal consistency | 10% | No contradictions within the analysis |

### Rubric calibration guidance (same doc)

- **Outcome-blinding required.** König-Kersting: evaluators rate identical reasoning higher when outcome is favorable. Use Annie Duke's 2×2 matrix (process × outcome) with deliberate upweighting of "good process / bad outcome."
- **Judge-model discipline.** Temperature = 0; **different model family as judge** (e.g., Claude judging Halcyon outputs); calibrate against 50 expert-labeled examples to Cohen's κ ≥ 0.6.
- **CheckEval binary decomposition** — +0.45 agreement improvement over Likert scales per FinReasoning benchmark (83.7% human-LLM agreement).
- **Pre-filters**: Loughran-McDonald sentiment dictionary (uncertainty-word density, strong-to-weak modal ratio).
- **Rubric evolution post-200 trades.** Regression of rubric dimensions against trade outcomes; adjust weights by predictive power. The rubric itself learns ("meta-flywheel" in the research framework).

### Existing infrastructure vs. spec gap

| Component | File | State vs. needed |
|---|---|---|
| Per-output rubric scoring | — | **Not built**; spec creates a rubric judge module |
| Canary set | `data/reference/canary_set.jsonl` | 5 examples; design is 25; spec targets 300 |
| Canary runner | `src/training/canary.py` | Exists; designed for 25 examples; distinct-n / self-BLEU / perplexity / edge-case accuracy signals defined |
| Canary status in EOD report | `src/scheduler/reports.py:136,696` | **Hardcoded `"STABLE"`** — stub, not computed |
| A/B evaluation | `src/training/ab_evaluation.py` | `run_shadow_evaluation`, `check_promotion_ready` — CLI-only, not wired into overnight pipeline |
| Quality drift | `src/training/quality_drift.py` | stdlib-only distinct-n + self-BLEU; writes to `quality_drift_metrics` |
| Leakage detector | `src/training/leakage_detector.py` | TF-IDF balanced accuracy; **wired nightly** at `src/scheduler/overnight.py:117` — runs but not gate-blocking |
| Storage tables | `canary_evaluations`, `model_evaluations`, `quality_drift_metrics` | Exist; zero rows ever (2026-04-20 audit finding) |
| Gate evaluator | `src/evaluation/gate_evaluator.py` | Exists; not wired to promotion |

**Key insight for Pass 3:** Spec 1 is *not* a greenfield build. It's a **wiring + canary-set-expansion + composite-gate** spec. Rubric judge is new.

### Cost model sanity check (from prompt: "300 × 2-3 models × ~17s")

- Ollama local inference on RTX 3060 per MASTER.md.
- Overnight window: VRAM handoff at ~18:50 ET; reload ~05:15 ET next morning. ~10 hours.
- 300 prompts × 3 models × 17s = 15,300s ≈ **4.25 hours** — fits inside the overnight window with headroom for fine-tuning and other overnight tasks.
- At 2 models (production + 1 challenger): ~2.8 hours.
- Caveat: Ollama sequential inference; if training subprocess is also running, they contend for VRAM via the existing `src/scheduler/vram_manager.py` handoff mechanism.

---

## Spec 2 — Second strategy — validation of proposed contents

### Strategy 2: short-term mean reversion — full signal spec from `Strategy_2_Selection__Mean_Reversion_Wins.md`

Entry:
- **Layer 1** (required): RSI(2) < 5 (Connors validated, win rate >70% on S&P 500).
- **Layer 2** (required): at least one of Bollinger Band(20,2) lower band touch, Z-score of 5-day returns < −2.0, OR Connors RSI (3,2,100) < 10.
- **Layer 3** (quality filter, recommended): exclude recent negative earnings surprise (PEAD filter), 200-day SMA drawdown > 15% (genuine breakdown), pending binary events (FDA/M&A), sector in downtrend. Include: multi-quarter positive SUE trend (Kaczmarek-Zaremba filter), above-avg institutional ownership, capitulation-signature volume (≥1.5× 20-day avg).

Exit:
- **Primary:** RSI(2) > 65 **OR** close above 5-day SMA.
- **Regime:** If VIX < 15 during hold, tighten to RSI(2) > 50 or first profitable close.
- **No percentage stop-losses** — Connors shows they damage mean-reversion performance because deeper oversold = higher expected return.

Sizing:
- VIX > 25 → +25% MR allocation (funded by reduction in pullback).
- VIX < 15 → −25% MR allocation.
- Follows Nagel (2012): reversal returns scale linearly with volatility.

Data additions on top of existing pipeline:
- RSI(2), Connors RSI, Bollinger Bands, Z-score of 5-day returns — trivial technical-indicator additions.
- Earnings SUE (Financial Modeling Prep or Alpha Vantage) — ~$30–50/month API cost.

Go/no-go gates (from same doc):
1. Backtest Sharpe > **0.5 net** on 2022–2024 holdout (Harvey-Liu-Zhu threshold).
2. Paper-trading realized correlation with pullback < **+0.20**.
3. Paper-trading drawdown must not exceed **−15%**.

### Strategy 3: evolved PEAD — full architecture from `PEAD_for_SP100__The_Drift_Evolved.md`

The doc resolves a research tension cleanly: single-quarter SUE-based PEAD is **dead** for large-cap stocks post-2006 decimalization (Martineau 2022, Subrahmanyam 2025), but richer earnings-information signals survive.

Candidate sub-signals (doc ranks them):

| Signal | Works? | Expected effect | Evidence |
|---|---|---|---|
| Classic single-quarter SUE | **No (dead)** | ~0 | Martineau 2022, Subrahmanyam 2025 |
| 12-quarter elastic-net SUE | **Yes** | Sharpe 0.34 → 0.63 | Kaczmarek-Zaremba 2025 |
| Text-based SUE.txt (earnings-call NLP) | **Likely yes** | 8% drift / 63 days | Meursault-Liang-Routledge-Scanlon 2023 JFQA |
| CNN visual earnings patterns | **Partially** | 3.6% spread / 63 days | Garfinkel-Hribar-Hsiao 2024 |
| Multi-signal composite (recommended) | **Yes** | Sharpe 0.9–1.3 est. | Supported by multiple papers above |
| Revenue–EPS concordance | **Yes** | +0.25% quarterly / concordant hedge | Jegadeesh-Livnat 2006 |
| Analyst revision velocity | **Yes** | — | Days 1–5 post-earnings |

Implementation path (from same doc):
- Data: Finnhub `company_earnings()` endpoint provides actual vs. estimate with pre-computed surprise for S&P 100. Adequate given high analyst coverage convergence.
- Limitation: no historical consensus snapshots — **critical for backtesting**, not for live. Workaround: point-in-time SUE from alt provider (FMP snapshots).
- Elastic net model trains `[SUE_t-1, ..., SUE_t-12]` → next-quarter return. Older lags gain weight over time (Kaczmarek-Zaremba temporal shift).

### Prompt's 4 candidates vs. existing decision tree

Reiterating Pass-1 finding with the Pass-2 detail: the 4 candidates in the sprint prompt are **Strategy #4 options** (the operator has Strategy 1 = pullback, 2 = MR selected, 3 = PEAD selected). Of the 4 prompt candidates:

- **Momentum-breakout** — closest analog in MR-selection doc is "sector rotation" (composite 22, ranked #3) flagged as correlation-killer (+0.30 to +0.50 with pullback). If the operator's new question is "pick Strategy #4," momentum-breakout is a *fresh* candidate not in the 2026-03 evaluation.
- **PEAD** — already selected as Strategy 3.
- **STMOM (Medhat-Schmeling)** — cited in `ARCIS_RESEARCH_FRAMEWORK.md` as reversal-dynamics support (Dai, Medhat et al. 2024), not as a separate strategy. Worth a fresh evaluation as Strategy #4.
- **Overnight/intraday tug-of-war** — in the 6-candidate MR-selection doc as "overnight returns," ranked #4 / composite 20, flagged as correlation-killer (+0.15 to +0.30 with pullback) per Lou-Polk-Skouras 2019.

Pass 3 writes the spec assuming the framing is **"Strategy 2 implementation audit + Strategy 3 (evolved PEAD) spec + acknowledgement of Strategy #4 candidates"** — operator decides at PR review whether to scope up.

---

## Spec 3 — Training curriculum gate — validation

### Outcome-mix targets (from `docs/research/Build_Score_Specification__Composite_KPI.md:88` and `deep-research/red-team-interview.md:60`)

Confirmed: **40% WIN / 25% LOSS / 5% TIMEOUT / 15% PASS**. Sums to 85%; remaining 15% is DPO pairs + anchors (per `red-team-interview.md:60`: "v2 dataset target 790 → 2,800 examples (40% WIN, 25% LOSS, 5% TIMEOUT, 15% PASS, 400 DPO pairs, 75 anchors)").

### Golden ratio (from `ARCIS_RESEARCH_FRAMEWORK.md:301` + `2026-04-05-15-algorithms-gap-analysis.md`)

- **62% curated / 38% model-generated** — lifted from AlpaGasus (Chen et al. 2023): 9K high-quality examples outperformed 52K unfiltered.
- Model-collapse citations: Shumailov et al. 2024 Nature (retaining just 10% original real data reduced degradation to "minor"); Dohmatob et al. 2025 ICLR Spotlight (even 1-in-1000 synthetic can cause asymptotic collapse; larger models amplify).
- He et al. 2025 citation is **unverifiable** per `2026-04-05-15-algorithms-gap-analysis.md:268` — flagged as low-confidence. Kang et al. (Meta/Virginia Tech) 2025 corroborates a ~30% synthetic / ~70% natural optimum, close to but slightly below 62/38's 38% synthetic.

### Leakage-detector threshold (from `src/training/leakage_detector.py` + sprint prompt memory)

- Balanced-accuracy baseline for random classifier on balanced binary data = 50%.
- Threshold: **< 55%** — only 5-percentage-point tolerance above random. TF-IDF model that detects outcome from commentary text at ≥55% balanced accuracy = evidence of leakage.
- `docs/research/15_Algorithm_Gap_Assessment.md` priority **#6 Self-Blinding Pipeline (Highest priority)** flags "embedding-based leakage detection" as a 2–3× sensitivity upgrade. Not in Sprint-3 scope; flagged as a Spec-3 follow-up inside the spec.

### Tool wiring status (from `src/scheduler/overnight.py:117` + repo-wide grep)

- `leakage_detector.run_leakage_check` — **wired** nightly at `overnight.py:117` but as a REPORT, not a gate.
- `quality_drift.compute_all_metrics` — called from `canary.py` module body only; canary itself doesn't run in overnight (per `overnight.py:213` hardcoded `canary_status="STABLE"`).
- No pre-training corpus gate exists — `src/training/trainer.py` or equivalent proceeds with whatever the training_examples table currently contains.

### Spec-3 gate composition (Pass-3 will draft)

Pre-training gate (blocks a training run if corpus fails):
1. Outcome mix within ±5 percentage points of 40/25/5/15.
2. Curated-to-generated ratio within ±5 pp of 62/38.
3. Leakage detector TF-IDF balanced accuracy < 55%.
4. Quality drift distinct-n not dropped >10% vs. prior corpus.
5. Minimum N per stage (40/25/5/15 targets × current total).

Post-training gate (interlocks with Spec 1 harness):
1. Spec-1 rubric composite ≥ threshold.
2. Canary perplexity increase < 5% vs. incumbent.
3. A/B head-to-head doesn't regress on rubric.

---

## Spec 4 — Containerization — validation

### Windows-native integrations that must stay (from `MASTER.md` + `CLAUDE.md`)

- `MASTER.md:17` — Release line includes "NSSM" as a pinned integration since v0.17.2.
- `MASTER.md:70` — hardware: RTX 3060 12GB, Windows 11, Z690, 24/7 operation.
- `MASTER.md:112` — NSSM service binding: `ArcisWatchLoop` service requires `ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3` in `AppEnvironmentExtra`. Standard Windows-service pattern.
- `MASTER.md:389` — "NSSM — Windows service wrapper for 24/7 watch loop (`scripts/install_service.ps1`)"
- `MASTER.md:407-424` — Windows service section: NSSM provides automatic restart, log rotation, and service-account isolation. Requires NSSM on PATH.
- `MASTER.md:689` — Grafana Loki MVP: async Python logging handler, `threading.Queue` (not multiprocessing) for Windows safety.

### Containerization scope decision matrix

| Subsystem | Container? | Rationale |
|---|---|---|
| Training subsystem (`training_data/train.py`, `src/training/*`, Ollama fine-tuning) | **Yes** | cp1252-hostile; trl pin was workaround; would benefit from glibc/UTF-8 default |
| Watch loop (`src/scheduler/watch.py`) | **No (keep Windows-native)** | NSSM integration, service lifecycle, Windows-specific log rotation |
| Scan services (`src/services/*_scan_service.py`) | **No (runs under watch loop)** | Same process tree as watch loop |
| Ollama inference daemon | **No (keep native)** | Already cross-platform on Windows; GPU passthrough in WSL2 container adds complexity without benefit |
| Render sync, Alpaca adapter | **No (keep native)** | Network-bound, OS-agnostic; no cp1252 issues observed |
| Reconciliation | **No (Windows-native)** | Runs in watch-loop process |
| Backtests (one-off scripts) | **Optional — container** | Nice-to-have; not a current pain point |

### WSL2 + Docker Engine vs. Docker Desktop

- **WSL2 + Docker Engine** — free, no Docker Desktop licensing concerns (Docker Desktop is free for individuals/nonprofits/small business but licensing shifts for larger operations). Requires manual installation of Docker Engine inside a WSL2 distribution. Strong Windows integration (WSL2 interop layer) — can bind-mount Windows paths into Linux container.
- **Docker Desktop** — easier install, richer GUI, but licensing cost uncertainty for potential future commercialization. Single-user workflow.
- **WSL2 alone, no Docker** — simplest: install a Ubuntu WSL2 distro, install Python + CUDA there, run training from bash. Loses portability (not a reproducible image) but eliminates container-orchestration complexity. Good first step.

Proposed default for Spec 4: **WSL2 alone for training subsystem first**, with Docker as a later upgrade when reproducibility matters. Operator can evaluate WSL2 within one week, defer Docker to a later sprint.

### GPU passthrough reality check

- **CUDA in WSL2**: supported since Windows 11 + WSL 2. Operator's machine is Windows 11 (per `MASTER.md:70`). NVIDIA driver Windows-side, CUDA toolkit inside WSL2 distro. Works with Ollama and PyTorch.
- **CUDA in Docker Desktop**: requires NVIDIA Container Toolkit (`nvidia-container-runtime`). Works but adds a container-runtime indirection.
- Risk: training subprocess under WSL2 cannot own the GPU while Ollama is using it on Windows — `vram_manager.py` handoff mechanism still required. Container does not remove the VRAM contention.

### Filesystem performance caveat

- NTFS ↔ ext4 cross-mount in WSL2 is **slow** (10–100× slower than native for small-file operations — pip installs, pytest discovery, git operations).
- Mitigation: keep the repo either fully under `\\wsl$\Ubuntu\home\...` (Linux-native, slow from Windows side) or on `C:\` with the container bind-mounting it (Windows-native, slow from Linux side). For training only (big parquet / GGUF files, few small-file operations), either works.
- Not a blocker; documented as operator knowledge.

---

## Pass-2 summary — no blockers

All four specs are draftable with existing research backing. No spec requires data that doesn't exist. Cross-spec coupling:
- Spec 1 provides the post-training gate; Spec 3 is the pre-training gate — they chain but neither circularly depends on the other.
- Spec 2 and Spec 4 are independent of the other two.

Pass 3 begins now with the 4 spec files, one commit per file.
