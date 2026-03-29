# Building bulletproof data quality for small-scale financial ML

A solo-operated ML trading system with 1,000 training examples cannot afford a single bad data point — yet Halcyon Lab's 78% format contamination persisted for weeks because zero quality gates existed. **The complete prevention stack for this failure costs $0 and takes roughly two days to build**: a custom Python ingestion gate (~50 lines), Pandera schema validation, Deepchecks NLP batch audits, SQLite-native versioning with audit triggers, distribution monitoring via Evidently AI, and Telegram alerting. Every recommendation below is calibrated for a solo operator generating 5–30 examples daily into a SQLite database, fine-tuning Qwen3 8B on 1,000–10,000 training examples. Enterprise tooling like LakeFS, Weights & Biases, and Airflow is explicitly excluded — the goal is **90% of enterprise MLOps value at 10% of the complexity**.

Andrew Ng's data-centric AI framework provides the theoretical foundation: with small datasets, quality dominates quantity so completely that 50 excellent examples can outperform billions of poor ones. The LIMA paper from Meta demonstrated that **1,000 high-quality examples produce competitive instruction-following performance** for LLM fine-tuning. At Halcyon Lab's scale, the 78% format failure effectively reduced the useful training set from ~1,000 to ~220 examples — a catastrophic loss where every corrupted example represented 0.1% of the entire dataset. The fix is not more data; it is systematic data engineering with automated gates that make such failures impossible.

---

## Two-stage validation prevents format disasters from ever recurring

The 78% markdown-instead-of-XML failure would have been caught instantly by even the simplest ingestion-time check — a `try: etree.fromstring()` call. The architecture requires two distinct validation stages, each serving a different purpose.

**Ingestion-time checks** run synchronously on every single record at insert time. These must be fast (microseconds per record) and catch structural failures immediately: XML well-formedness via `lxml`, required field presence, content length bounds (min 50 / max 10,000 characters), and a critical format detection function that identifies markdown artifacts (regex for `#`, `**`, triple backticks) and rejects anything that isn't valid XML. A format detection gate like this would have caught the contamination on the very first malformed example:

```python
from lxml import etree
import re

def validate_on_ingest(content: str) -> tuple[bool, list[str]]:
    errors = []
    # The check that would have prevented the 78% failure
    markdown_patterns = [r'^#{1,6}\s', r'\*\*.*\*\*', r'^```', r'\[.*\]\(.*\)']
    for pattern in markdown_patterns:
        if re.search(pattern, content, re.MULTILINE):
            errors.append(f"Markdown detected: {pattern}")
    try:
        etree.fromstring(content.encode())
    except etree.XMLSyntaxError as e:
        errors.append(f"Invalid XML: {e}")
    return len(errors) == 0, errors
```

**Batch-time checks** run nightly or before each training run, operating on aggregate statistics across the full dataset. These catch drift, duplicates, label distribution shifts, and cross-record consistency issues that no per-record check can detect. The critical insight from data engineering best practice is the **hybrid quarantine strategy**: quarantine bad records by default to allow continued operation, but halt the entire pipeline if the pass rate drops below 80% — preventing silent mass contamination.

For framework selection, **Pandera is the recommended primary validation layer** over Great Expectations. Pandera has only 12 package dependencies versus Great Expectations' 107, offers a Pythonic API with lambda-based custom checks, and achieves a learning curve measured in hours rather than days. Great Expectations' DataContext/Stores/Checkpoints architecture is enterprise-grade infrastructure that adds unnecessary cognitive load for a solo operator managing fewer than 10,000 records. For periodic deep validation, **Deepchecks NLP** provides nine pre-built data integrity checks specifically for text data — including conflicting labels detection, unknown token identification for specific tokenizers, text property outlier detection, and near-duplicate finding — that would require hundreds of lines of custom code to replicate.

Expected rejection rates for a healthy pipeline: **2–5% at ingestion** (format, schema, completeness), an additional 3–7% flagged during batch validation (duplicates, distribution anomalies), and 5–10% flagged by periodic LLM-as-judge scoring. A solo operator generating 5–30 examples daily should expect 1–5 quarantined items per day at steady state. The 78% failure rate was not merely high — it was catastrophically beyond any acceptable threshold and should have triggered an immediate pipeline halt at any ingestion rate above **15–20%**.

---

## Drift detection requires weekly windows and financial-aware thresholds

Statistical drift detection on daily batches of 5–30 examples is unreliable — sample sizes are simply too small for meaningful hypothesis testing. The practical minimum window for Halcyon Lab is **weekly accumulation (35–210 examples)** for basic tests, with full statistical power achieved at monthly windows (150–900 examples).

Three statistical methods form the recommended detection stack, each suited to different feature types. **Population Stability Index (PSI)** — calculated as Σ(Actual% − Expected%) × ln(Actual%/Expected%) across binned distributions — is the financial industry standard with well-established thresholds: PSI below **0.10** indicates no significant shift, **0.10–0.25** warrants monitoring, and above **0.25** demands investigation and likely retraining. For text features, apply PSI to token length distributions (continuous, 5–8 quantile bins) and vocabulary frequency distributions (categorical, treating top-K tokens as bins). A critical caveat: PSI is sensitive to binning strategy, and NannyML's research found the 0.25 threshold triggers on a mean shift of just 0.6 standard deviations between normal distributions.

The **Kolmogorov-Smirnov test** measures the maximum absolute difference between two empirical CDFs. For small samples, prefer the D statistic itself as a magnitude measure rather than relying on p-values — **D > 0.15–0.20 indicates meaningful drift** regardless of statistical significance. The KS test's key limitation is blindness to multiple distributed shifts; it detects only the single point of maximum CDF divergence.

**Wasserstein distance** (Earth Mover's Distance) is the strongest choice for Halcyon Lab's small datasets because it quantifies total distribution shift magnitude, remains stable with small samples, and produces interpretable results in the original data units (e.g., "the average token length shifted by 47 tokens"). Normalize by dividing by the reference standard deviation, then flag drift when the normalized value exceeds **0.2** (alert) or **0.5** (action). Evidently AI's experiments confirm Wasserstein is "a good compromise between way-too-sensitive KS and notice-only-big-changes PSI."

For text and embedding-based monitoring, the **model-based drift detection method** — training a classifier to distinguish reference from current embeddings and using ROC AUC as the drift score — outperforms all alternatives in Evidently AI's testing. An **AUC above 0.55** suggests drift; above **0.65** demands action. Generate embeddings using a sentence transformer like `all-MiniLM-L6-v2` or Qwen3's own embedding layer, then track weekly.

A challenge unique to financial ML is distinguishing data quality drift from legitimate market regime changes. The key diagnostic: **data quality issues typically affect specific features in isolation** (e.g., format compliance drops while everything else holds steady), while regime changes affect all market-derived features simultaneously. Maintain two reference windows — full historical training data and a recent 30-day window — and compare new data against both. Drift relative to the recent window but not the historical window suggests gradual evolution; drift relative to both signals a quality break. Track P&L as the ultimate concept drift indicator.

**Evidently AI** is the recommended monitoring framework. It uses SQLite natively as its storage backend, accepts pandas DataFrames directly, provides 100+ built-in metrics including PSI/KS/Wasserstein with configurable methods, offers text-specific descriptors (length, sentiment, regex), and runs from Jupyter notebooks with zero additional infrastructure. The free tier supports 10,000 rows per month — sufficient for Halcyon Lab's scale indefinitely.

For mode collapse detection in LLM-generated training data, track **Distinct-2** (ratio of unique bigrams to total bigrams) and average pairwise embedding cosine distance. A Distinct-2 drop exceeding **15% from baseline** signals collapsing diversity. The fundamental prevention rule: never let LLM-generated examples exceed **30–40% of total training data** without rigorous quality filtering. Research from Gerstgrasser et al. (2024) demonstrates that model collapse does not occur when synthetic data accumulates alongside real data rather than replacing it.

---

## SQLite-native versioning eliminates the need for external tools

LakeFS is enterprise infrastructure designed for petabyte-scale data lakes with multi-team governance — a hard no for a solo operator with a single SQLite file. DVC provides automated hash-based versioning tied to git commits but treats the entire SQLite file as an opaque blob, triggering a full copy on any single-row change. The recommended primary approach is **SQLite-native versioning using four interconnected tables** that provide complete data lineage without external dependencies.

The core schema uses a `training_examples` table with `content_hash` (SHA-256 of concatenated fields), `batch_id`, `source`, `validation_status`, and `row_version` columns; a `training_runs` table capturing `dataset_hash` (SHA-256 of all sorted content hashes), hyperparameters as JSON, git commit, library versions, and random seed; a `run_examples` junction table linking every training run to its exact constituent examples; and an `audit_log` table populated by SQLite triggers that record every INSERT, UPDATE, and DELETE with old and new values as JSON.

This architecture solves the "bad batch" problem directly. When contaminated examples are discovered, a single SQL query identifies every affected training run:

```sql
SELECT tr.run_id, tr.started_at,
       COUNT(re.example_id) as bad_count,
       ROUND(COUNT(re.example_id) * 100.0 / tr.dataset_size, 1) as contamination_pct
FROM training_runs tr
JOIN run_examples re ON tr.run_id = re.run_id
WHERE re.example_id IN (SELECT id FROM training_examples WHERE validation_status = 'quarantined')
GROUP BY tr.run_id;
```

**Dataset fingerprinting** — computing a deterministic hash over all valid training examples before each run — enables instant comparison between any two training states. If a fingerprint matches, the datasets are identical; if not, the junction table reveals exactly which examples differ. For complete external backup, use SQLite's built-in backup API (`conn.backup(dest)`) to create atomic snapshots before each training run, and periodically commit SQL text dumps to git for diffable history.

For experiment tracking, **skip MLflow and Weights & Biases**. MLflow adds ~200MB of dependencies and runs a server consuming ~200MB of RAM — reasonable but unnecessary overhead for infrequent fine-tuning runs. Weights & Biases sends data to external servers, creating IP risk for a trading system. Instead, store all experiment metadata directly in the `training_runs` SQLite table with JSON columns for hyperparameters and metrics. A **TrainingTracker class of roughly 80 lines** handles run registration, git state capture, dataset fingerprinting, metric logging, and database snapshotting — all the essential reproducibility metadata with zero external dependencies.

The minimum metadata required for targeted rollback: `dataset_hash`, `git_commit` + `git_dirty`, hyperparameters JSON (learning rate, epochs, batch size, LoRA rank), `random_seed`, `base_model` identifier, and library versions (Python, PyTorch, Transformers). With these fields captured, any training run can be reproduced exactly. Influence functions for identifying which specific training examples most affected model behavior are computationally infeasible for an 8B parameter model on a solo operator's hardware. The practical alternative: at 1,000–10,000 examples, **leave-one-out or batch ablation retraining** is cheap enough to be the standard approach for tracing data influence.

---

## Multi-source mixing ratios and lookahead bias demand financial-specific gates

Training data from multiple sources (API-generated, manual, historical backfill, production outcomes) introduces source-specific failure modes that generic validation cannot catch. API version drift is particularly insidious — a provider adding a new nested JSON field may not crash parsers but causes critical fields to silently default to null. **Hash the API response schema on every call** and compare against a stored reference; any structural change quarantines new examples immediately.

For optimal source mixing, start with **≥50% manually curated/production-verified examples, ≤30% API-generated, ≤20% historical backfill** at the 1,000-example stage. As the dataset scales to 5,000–10,000, relax to ≥40%/≤40%/≤20%. The "Data Mixing Can Induce Phase Transitions" paper (2025) demonstrates that knowledge acquisition from mixed datasets exhibits sharp phase transitions — below a critical ratio, the model learns almost nothing from a source; above it, acquisition accelerates rapidly. Track source proportions as a pre-training validation gate: `assert api_generated_pct <= 0.40`.

Assign default quality weights by source for loss weighting: manual = 1.0, production-verified = 0.95, API-generated-reviewed = 0.8, API-generated-unreviewed = 0.6, historical backfill = 0.5. Implement curriculum learning by training on highest-quality examples first and progressively introducing lower-quality sources across epochs.

**Lookahead bias detection** is the most critical financial-specific quality gate. Lopez-Lira et al. (2025) demonstrated that GPT-4o can recall exact S&P 500 closing prices with <1% error for dates within its training window — meaning any LLM-generated training example may contain memorized future data. Beyond TF-IDF classification, use temporal holdout validation (split strictly by date; dramatic performance asymmetry before vs. after the cutoff signals contamination), the **Lookahead Propensity score** (MIN-K% PROB method, achieving 0.88 AUC on validation), and point-in-time verification ensuring every referenced datapoint was publicly available at the example's stated timestamp. For equity data specifically: use as-reported earnings figures (not restated), verify that adjusted close prices are computed as of the example date, confirm news articles predate decision timestamps, and use rolling-window statistics for normalization rather than full-sample statistics.

---

## Circuit breakers should auto-halt on format failures, advise on drift

Pipeline halt decisions follow a risk-based framework where **anything affecting live trading decisions triggers automatic halt**, while gradual quality degradation triggers advisory alerts. The critical auto-halt conditions: format compliance below 90% (the 78% failure would have been caught), schema validation failures exceeding 5% (indicating broken upstream API), distribution shift with PSI above 0.25, any detected lookahead bias, and zero new examples for 72+ hours (indicating pipeline failure). Advisory alerts trigger at PSI between 0.10–0.25, source mix ratio drift exceeding 10% from target, and response length outliers beyond 3σ.

Pre-training validation requires a mandatory eight-point checklist — all must pass before any training run begins:

- Data volume ≥500 examples with ≥10 new since last training
- 100% schema compliance across all selected examples
- No single source exceeding 60% of total examples
- Response and instruction length PSI below 0.25 versus previous training set
- Most recent example less than 48 hours old, no more than 20% of examples older than 90 days
- No exact duplicates, near-duplicate cosine similarity below 0.95
- All examples passing temporal integrity validation
- Evaluation set ≥100 examples, temporally separated from training set

Post-training validation uses the **champion-challenger pattern**: run both the current production model and the newly trained challenger on an identical held-out evaluation set, then apply McNemar's test to determine statistical significance. McNemar's test requires at least 25 discordant pairs (examples where models disagree) for the chi-squared approximation; for smaller sets, use the exact binomial test. For detecting a 10% accuracy difference with 80% power, **~100 evaluation examples suffice** — achievable by reserving 15–20% of the total dataset. Only promote the challenger if it shows statistically significant improvement (p < 0.10, relaxed for small samples), maintains ≥95% output format compliance, and shows no Sharpe ratio degradation exceeding 0.2 in backtesting.

Recovery after a data quality incident follows six steps: detect and halt (automated, minutes), assess blast radius via SQL queries against the `run_examples` junction table (manual, 1–2 hours), quarantine contaminated examples (30 minutes), root cause analysis (1–4 hours), remediate by fixing or deleting bad data and retraining (variable), then validate and resume by running the full validation suite on the cleaned dataset. Document every incident with detection timestamp, blast radius, trading impact, root cause, resolution, and prevention measure added.

---

## The $0 monitoring stack that catches everything

The minimum viable MLOps stack for Halcyon Lab consists entirely of free tools already in a Python developer's workflow: **Git + SQLite + pytest + cron + Telegram**. No Kubernetes, no Airflow, no Prometheus, no managed services.

**pytest serves as the data validation framework**, requiring zero new dependencies. A `conftest.py` provides database fixtures; a `test_data_quality.py` implements `TestFormatCompliance` (the check that would have caught the 78% failure), `TestDataDistribution` (duplicates, minimum dataset size, recency), and `TestFinancialSpecific` (lookahead bias, signal format) as test classes. Run this suite daily via cron at 6 AM and weekly via GitHub Actions on any push to the `data/` directory. Anti-patterns to avoid: don't make tests dependent on external APIs, don't create separate test functions for individual examples (use `pytest.mark.parametrize`), and don't skip failed tests — fix the data.

**Telegram alerting requires ~30 lines of Python**: create a bot via @BotFather, get a chat ID, and `requests.post()` messages with severity-coded emoji. Critical alerts (format failures, data count drops) push immediately; warnings batch into daily digests. Prevent alert fatigue with a 24-hour cooldown per alert key, a maximum of 5 alerts per hour, and suppressed INFO-level alerts during quiet hours.

**A Streamlit dashboard in ~50 lines** visualizes format compliance rate, total example count, new examples per day, and validation status over time. Run locally with `streamlit run dashboard.py` — no deployment needed. Store quality metrics in a dedicated `quality_metrics` SQLite table updated by each validation run.

The monitoring schedule: **every insert** gets format validation via the ingestion gate; **daily at 6 AM** runs the full pytest suite with Telegram alerts; **weekly on Sunday** runs deep quality checks including embedding similarity, distribution analysis via Evidently AI, and source proportion audit; **before every training run** executes the eight-point pre-training checklist; **monthly** performs LLM-as-judge scoring of all examples using Claude Haiku batch API at a cost of approximately **$1–2 for 10,000 examples**.

Custom Python validation wins over framework overhead for this scale. The format validation that would have prevented the entire 78% failure is 20 lines of Python. The equivalent in Great Expectations requires ~100+ lines including data context setup, datasource configuration, expectation suite creation, and checkpoint configuration — plus 50+ transitive dependencies. Use Pydantic for individual record schema validation, Pandera when DataFrame-level validation becomes useful, and Deepchecks NLP for the weekly deep audit. Save Great Expectations for the day the team grows beyond one person.

---

## Conclusion: two days of work to prevent weeks of silent failure

The implementation priority is clear. **Day one**: build the custom ingestion gate (XML validation + markdown detection + required fields), write the core pytest suite, set up the SQLite quarantine table and training runs schema, and configure Telegram alerting. **Day two**: implement the pre-training validation checklist, set up cron-based daily monitoring, build the Streamlit dashboard, and run Deepchecks NLP against the full existing dataset to establish baselines.

The deeper insight from Ng's data-centric AI movement is that this infrastructure is not overhead — it is the core product. With 1,000 training examples, **data quality IS model quality**. The Halcyon Lab format failure persisted for weeks not because detection was hard (a single regex would have caught it) but because no one built the 20-line check. The entire recommended stack — ingestion gates, batch validation, drift monitoring, versioning, circuit breakers, and alerting — runs on SQLite, costs nothing, and transforms a fragile manual process into a system that fails loudly rather than silently.

Three novel insights emerge from this research. First, weekly accumulation windows are the minimum viable unit for drift detection at 5–30 daily examples — daily statistical testing is unreliable and generates false alarms. Second, the LLM-as-judge approach using batch API pricing has become remarkably cheap ($1–2 per 10,000 examples), making monthly full-dataset quality scoring practical even for solo operators. Third, the SQLite-native versioning approach with four tables (examples, runs, junction, audit log) provides complete data lineage and rollback capability without any external tooling — matching the core functionality of DVC and MLflow for this specific use case with zero additional dependencies.