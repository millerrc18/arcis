"""Fine-tuning orchestrator with Unsloth and auto-rollback.

Called by: api.routes.actions, cli.commands, scheduler.watch, services.training_service, training.report
Calls: config, llm.client, training.canary, training.claude_client, training.curriculum, training.dpo_pipeline, training.versioning
Owns tables: none
Config keys: auto_rollback_expectancy_drop, auto_rollback_winrate_drop, auto_train_min_examples, auto_train_threshold, auto_train_time_days, enabled, training
Tests: tests/test_holdout.py, tests/test_leakage_detector.py, tests/test_trainer.py, tests/test_training_data.py

WHY this architecture:
    Fine-tuning runs as a subprocess (not in-process) because the training
    script needs exclusive VRAM access. The watch loop's Ollama instance must
    be unloaded first (#112: VRAM not freed). Running as a subprocess also
    provides process isolation -- if training OOMs or segfaults, the main
    process survives and can report the failure.

    The pipeline has a champion-challenger model with auto-rollback:
    1. Export data with temporal holdout split (#114)
    2. Train via 3-stage curriculum (structure -> evidence -> decision)
    3. Canary evaluation on fixed reference examples
    4. Holdout evaluation comparing new model vs. previous champion
    5. Auto-rollback if expectancy or win-rate drops below threshold
    6. Optional DPO refinement if 100+ preference pairs exist

    #112 — VRAM handoff is coordinated by the watch loop (scheduler.watch),
    not by this module. The watch loop unloads Ollama before calling
    run_fine_tune() and reloads it after. This module assumes VRAM is
    available when called.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.utils.db import connect_db
from src.methods.promotion_gate import promotion_gate
from src.notifications import safe_send
from src.training.versioning import (
    get_active_model_version,
    get_next_semver,
    update_config_model,
    get_model_history,
    get_new_examples_since,
    get_performance_by_version,
    get_training_example_counts,
    init_training_tables,
    register_model_version,
    rollback_model,
)

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# WHY inline script strings instead of separate .py files: the training scripts
# are written to disk at runtime because they execute in a subprocess with a
# potentially different Python environment (CUDA-enabled). Keeping them inline
# ensures the exact script version matches the orchestrator version, avoiding
# drift between the two. The subprocess pattern also means these scripts cannot
# import from src/ -- they must be self-contained.

TRAIN_SCRIPT = '''# training_data/train.py -- DEPRECATED: legacy single-stage trainer
# Uses old Unsloth API. The curriculum script (CURRICULUM_TRAIN_SCRIPT) is the
# primary training path and uses standard PEFT/TRL 0.24 API instead.
import json, sys, os
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["UNSLOTH_DISABLE_FUSED_CROSS_ENTROPY"] = "1"

def main():
    from unsloth import FastLanguageModel
    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Qwen3-8B", max_seq_length=1024, dtype=None, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(model,
        r=8, lora_alpha=16, lora_dropout=0,
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
        bias="none", use_gradient_checkpointing="unsloth")

    examples = []
    with open("training_data/dataset.jsonl", encoding="utf-8") as f:
        for line in f: examples.append(json.loads(line))

    def fmt(ex):
        return {"text": tokenizer.apply_chat_template(
            [{"role":"system","content":ex["instruction"]},
             {"role":"user","content":ex["input"]},
             {"role":"assistant","content":ex["output"]}], tokenize=False)}

    dataset = Dataset.from_list(examples).map(fmt)
    if len(dataset) < 5:
        print(f"[TRAIN] Dataset too small ({len(dataset)} examples) — skipping")
        sys.exit(0)
    effective_gas = min(16, max(1, len(dataset)))
    trainer = SFTTrainer(model=model, processing_class=tokenizer,
        train_dataset=dataset, max_seq_length=1024,
        args=TrainingArguments(per_device_train_batch_size=1, gradient_accumulation_steps=effective_gas,
            num_train_epochs=1, learning_rate=2e-4, bf16=True, logging_steps=10,
            output_dir="training_data/checkpoints", report_to="none"))
    trainer.train()

    model.save_pretrained("training_data/lora_adapter")
    tokenizer.save_pretrained("training_data/lora_adapter")
    model.save_pretrained_gguf("training_data/halcyon-latest", tokenizer, quantization_method="q5_k_m")
    print("TRAINING COMPLETE")

if __name__ == "__main__":
    main()
'''

# WHY 3-stage curriculum (structure -> evidence -> decision):
# Stage 1 (STRUCTURE, lr=3e-4): Simple, clean examples where thesis and
#   evidence align clearly. Teaches the model output format and basic
#   analytical reasoning. Highest learning rate because early examples
#   are furthest from the model's prior.
# Stage 2 (EVIDENCE, lr=2e-4): Multi-source examples with conflicting
#   signals (e.g., strong technicals but weak fundamentals). Teaches
#   evidence weighing and nuanced judgment. Lower LR to avoid
#   overwriting Stage 1's structural learning.
# Stage 3 (DECISION, lr=1e-4): Hard cases -- regime transitions, sector
#   rotations, earnings proximity. Teaches the model to make and justify
#   difficult calls. Lowest LR for fine-grained refinement.
# The decreasing LR schedule follows the "curriculum learning" principle:
# easy examples first with aggressive updates, hard examples last with
# conservative updates. This prevents catastrophic forgetting of basic
# structure when learning complex decision-making.
CURRICULUM_TRAIN_SCRIPT = '''
import json, sys, os, torch
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

def main():
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTTrainer, SFTConfig
    from datasets import Dataset

    print(f"[TRAIN] CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}")
    print(f"[TRAIN] Free VRAM: {torch.cuda.mem_get_info()[0]/1e9:.1f}GB")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen3-8B",
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = prepare_model_for_kbit_training(model)
    # WHY r=16, alpha=32 (alpha/r=2): higher rank than the legacy script's r=8
    # because curriculum training has more diverse examples across 3 stages.
    # alpha/r=2 keeps the effective learning rate reasonable.
    # WHY all 7 projection modules: Qwen3's architecture uses gated MLP
    # (gate_proj + up_proj + down_proj) alongside attention projections.
    # Training all 7 gives maximum expressiveness on our small dataset
    # while still being parameter-efficient (~2% of full model params).
    # WHY dropout=0: with <1000 training examples and strong quality
    # filtering, regularization via dropout hurts more than it helps.
    # The holdout evaluation provides the overfitting check instead.
    lora_config = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0,
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
        bias="none", task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    model.gradient_checkpointing_enable()

    def load_stage(fn):
        examples = []
        with open(fn, encoding="utf-8") as f:
            for line in f: examples.append(json.loads(line))
        def fmt(ex):
            return {"text": tokenizer.apply_chat_template(
                [{"role":"system","content":ex["instruction"]},
                 {"role":"user","content":ex["input"]},
                 {"role":"assistant","content":ex["output"]}], tokenize=False)}
        return Dataset.from_list(examples).map(fmt)

    stages = [
        ("STRUCTURE", "training_data/stage1_structure.jsonl", 3e-4),
        ("EVIDENCE",  "training_data/stage2_evidence.jsonl",  2e-4),
        ("DECISION",  "training_data/stage3_decision.jsonl",  1e-4),
    ]

    for name, path, lr in stages:
        print(f"=== STAGE: {name} ===")
        try:
            ds = load_stage(path)
        except FileNotFoundError:
            print(f"  No data for {name}, skipping")
            continue
        if len(ds) == 0:
            print(f"  Empty dataset for {name}, skipping")
            continue
        if len(ds) < 5:
            print(f"  Dataset too small for {name} ({len(ds)} examples) — skipping")
            continue
        # #115 -- Dynamic gradient accumulation to prevent crash on small datasets.
        # WHY: with batch_size=1, gradient_accumulation_steps must not exceed
        # dataset size or the trainer throws a division-by-zero. Cap at 16 to
        # keep effective batch size manageable on 12GB VRAM (RTX 3060).
        effective_gas = min(16, max(1, len(ds)))
        sft_config = SFTConfig(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=effective_gas,
            num_train_epochs=1,
            learning_rate=lr,
            bf16=True,
            logging_steps=10,
            max_length=512,
            output_dir=f"training_data/checkpoints/{name.lower()}",
            optim="paged_adamw_8bit",
            report_to="none",
            dataset_text_field="text",
        )
        trainer = SFTTrainer(
            model=model,
            train_dataset=ds,
            args=sft_config,
        )
        trainer.train()
        print(f"  {name} complete: {len(ds)} examples")

    # Save LoRA adapter
    model.save_pretrained("training_data/lora_adapter")
    tokenizer.save_pretrained("training_data/lora_adapter")

    # Merge and export GGUF
    # #387: Try Unsloth GPU export first, then fall back to llama.cpp CPU conversion.
    # RTX 3060 12GB may not have enough VRAM for q5_k_m quantization of 8B models.
    print("[TRAIN] Merging LoRA and exporting GGUF...")
    gguf_exported = False
    try:
        from unsloth import FastLanguageModel
        merged_model, merged_tok = FastLanguageModel.from_pretrained(
            model_name="training_data/lora_adapter", max_seq_length=512, dtype=None, load_in_4bit=True)
        merged_model.save_pretrained_gguf("training_data/halcyon-latest", merged_tok, quantization_method="q5_k_m")
        gguf_exported = True
    except Exception as e:
        print(f"[TRAIN] GGUF export via Unsloth failed: {e}")
        # Fallback: use llama.cpp convert if available (CPU-based, no VRAM needed)
        try:
            import subprocess
            print("[TRAIN] Attempting CPU-based GGUF conversion via llama.cpp...")
            result = subprocess.run(
                ["python", "-m", "llama_cpp.convert",
                 "training_data/lora_adapter",
                 "--outfile", "training_data/halcyon-latest.gguf",
                 "--outtype", "q5_k_m"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=600,
            )
            if result.returncode == 0:
                print("[TRAIN] CPU-based GGUF conversion succeeded")
                gguf_exported = True
            else:
                print(f"[TRAIN] llama.cpp conversion failed: {result.stderr[:200]}")
        except Exception as fallback_err:
            print(f"[TRAIN] CPU fallback also failed: {fallback_err}")
    if not gguf_exported:
        print("[TRAIN] WARNING: No GGUF produced. LoRA adapter saved at training_data/lora_adapter.")

    print("TRAINING COMPLETE")

if __name__ == "__main__":
    main()
'''

# WHY DPO after SFT, not standalone: DPO (Direct Preference Optimization)
# refines an already-capable model by teaching it to prefer better analyses
# over worse ones. Without SFT first, the model would not know the output
# format or analytical framework. DPO is gated on 100+ preference pairs
# because smaller datasets cause the model to overfit to specific phrasings
# rather than learning genuine quality preferences.
# WHY beta=0.1: controls how much the model can diverge from the SFT
# reference policy. 0.1 is conservative -- we want subtle quality
# improvements, not dramatic behavioral changes.
DPO_TRAIN_SCRIPT = '''
import json, sys, os
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ["UNSLOTH_DISABLE_FUSED_CROSS_ENTROPY"] = "1"

def main():
    from unsloth import FastLanguageModel
    from trl import DPOTrainer, DPOConfig
    from datasets import Dataset

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="training_data/lora_adapter", max_seq_length=1024, dtype=None, load_in_4bit=True)

    model = FastLanguageModel.get_peft_model(model,
        r=8, lora_alpha=16, lora_dropout=0.0,
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
        bias="none", use_gradient_checkpointing="unsloth")

    pairs = []
    with open("training_data/preference_pairs.jsonl", encoding="utf-8") as f:
        for line in f: pairs.append(json.loads(line))

    dataset = Dataset.from_list(pairs)

    trainer = DPOTrainer(model=model, processing_class=tokenizer, train_dataset=dataset,
        args=DPOConfig(
            per_device_train_batch_size=1, gradient_accumulation_steps=8,
            num_train_epochs=3, learning_rate=5e-5, beta=0.1, bf16=True,
            logging_steps=10, output_dir="training_data/checkpoints/dpo", report_to="none"))
    trainer.train()

    model.save_pretrained("training_data/lora_adapter_dpo")
    tokenizer.save_pretrained("training_data/lora_adapter_dpo")
    model.save_pretrained_gguf("training_data/halcyon-latest", tokenizer, quantization_method="q5_k_m")
    print("DPO TRAINING COMPLETE")

if __name__ == "__main__":
    main()
'''


def should_train(db_path: str = DB_PATH) -> tuple[bool, str]:
    """Check if fine-tuning should be triggered.

    WHY two trigger conditions (threshold OR time+minimum):
    - Threshold (default 50 examples): when enough new data accumulates,
      train immediately to capture recent market regime shifts.
    - Time-based (default 7 days + 20 examples): even if example flow is
      slow, periodic retraining prevents the model from going stale. The
      minimum of 20 examples prevents wasteful training on tiny batches.

    Returns (should_train, reason_string).
    """
    config = load_config()
    training_cfg = config.get("training", {})
    if not training_cfg.get("enabled", False):
        return False, "Training disabled in config"

    # #330: Cast config values — YAML can store them as strings
    # Default raised to 500 to prevent bulk imports (backfill) from
    # falsely triggering auto-retrain during normal watch loop cycles.
    threshold = int(training_cfg.get("auto_train_threshold", 500))
    time_days = int(training_cfg.get("auto_train_time_days", 7))
    min_examples = int(training_cfg.get("auto_train_min_examples", 20))

    init_training_tables(db_path)
    active = get_active_model_version(db_path)

    if active:
        since_date = active["created_at"]
        new_count = get_new_examples_since(since_date, db_path)
        created = datetime.fromisoformat(active["created_at"])
        days_since = (datetime.now(ET) - created.replace(tzinfo=ET if created.tzinfo is None else created.tzinfo)).days
    else:
        # No model yet — count all examples
        counts = get_training_example_counts(db_path)
        new_count = counts["total"]
        days_since = 999  # Arbitrary large number

    if new_count >= threshold:
        viable, viability_reason, _ = get_training_split_viability(db_path=db_path)
        if not viable:
            return False, viability_reason
        return True, f"{new_count} new examples since last train (threshold: {threshold}); {viability_reason}"

    if days_since >= time_days and new_count >= min_examples:
        viable, viability_reason, _ = get_training_split_viability(db_path=db_path)
        if not viable:
            return False, viability_reason
        return True, f"{days_since} days since last train, {new_count} new examples; {viability_reason}"

    return False, f"{new_count} new examples, {days_since} days since last train (need {threshold} examples or {time_days} days with {min_examples}+ examples)"


def get_training_split_viability(db_path: str = DB_PATH) -> tuple[bool, str, dict]:
    """Return whether a training run can pass the temporal holdout gate.

    Uses a temporary export directory so the watch loop can decide whether to
    schedule the GPU training handoff without touching tracked training_data
    artifacts.
    """
    with tempfile.TemporaryDirectory(prefix="arcis-training-viability-") as tmpdir:
        split_counts, total = export_training_data(
            output_dir=tmpdir,
            db_path=db_path,
            alert_on_empty_holdout=False,
        )
    train_count = split_counts.get("training", 0)
    holdout_count = split_counts.get("holdout", 0)
    counts = {
        "total": total,
        "training": train_count,
        "holdout": holdout_count,
    }
    if total == 0 or train_count == 0:
        return False, "Training split not viable: no exportable training examples", counts
    if holdout_count == 0:
        return (
            False,
            "Training split not viable: HOLDOUT EMPTY after 5-day temporal gap",
            counts,
        )
    return True, f"holdout viable ({train_count} training / {holdout_count} holdout)", counts


def export_training_data(
    output_dir: str = "training_data",
    holdout_pct: float = 0.15,
    db_path: str = DB_PATH,
    alert_on_empty_holdout: bool = True,
) -> tuple[dict, int]:
    """Export training data with curriculum split and chronological holdout.

    Creates:
        training_data/dataset.jsonl            (combined training -- backward compat)
        training_data/stage1_structure.jsonl    (easy/clean examples)
        training_data/stage2_evidence.jsonl     (multi-source examples)
        training_data/stage3_decision.jsonl     (hard/conflicting examples)
        training_data/holdout.jsonl             (validation split -- never trained on)
        training_data/split_info.json           (metadata about the split)

    #114 — WHY chronological (temporal) holdout instead of random split:
    Financial data is time-series with regime changes. A random 85/15 split
    would leak future information into training (e.g., training on a March
    example, validating on a February example from the same regime). The
    temporal split ensures ALL holdout examples are chronologically AFTER
    all training examples, with a 5-day gap to prevent information bleeding
    across the boundary (e.g., a trade opened in training period but closed
    in holdout period).

    #111 — Canary examples are excluded from both training and holdout to
    maintain their integrity as a fixed reference set for model evaluation.

    #116 — Partial-close examples are excluded from training (ambiguous P&L
    labeling) but remain in the database for future analysis.

    Returns:
        ({"training": N, "holdout": N}, total_count)
    """
    init_training_tables(db_path)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Classify untagged examples first
    try:
        from src.training.curriculum import classify_all_examples
        classify_all_examples(db_path)
    except Exception as e:
        logger.warning("[TRAINING] Failed to classify examples: %s", e)

    with connect_db(db_path) as conn:
        rows = conn.execute(
            "SELECT example_id, instruction, input_text, output_text, created_at, "
            "quality_score, curriculum_stage, quality_score_auto, source "
            "FROM training_examples "
            "WHERE COALESCE(quarantined, 0) = 0 "
            "ORDER BY created_at ASC"
        ).fetchall()

    if not rows:
        for fname in ("dataset.jsonl", "holdout.jsonl", "stage1_structure.jsonl",
                       "stage2_evidence.jsonl", "stage3_decision.jsonl"):
            open(str(Path(output_dir) / fname), "w").close()
        split_info = {"total_examples": 0, "training_examples": 0, "holdout_examples": 0}
        with open(str(Path(output_dir) / "split_info.json"), "w") as f:
            json.dump(split_info, f, indent=2)
        return {"training": 0, "holdout": 0}, 0

    examples = [dict(row) for row in rows]
    total = len(examples)

    # #111 — Exclude canary examples from training data
    try:
        from src.training.canary import CanaryMonitor, DEFAULT_CANARY_PATH
        if DEFAULT_CANARY_PATH.exists():
            monitor = CanaryMonitor(db_path=db_path)
            canary_list = monitor.load_canaries()
            canary_ids = {e.get("example_id") for e in canary_list if e.get("example_id")}
            if canary_ids:
                before = len(examples)
                examples = [e for e in examples if e.get("example_id") not in canary_ids]
                filtered = before - len(examples)
                if filtered:
                    logger.warning("[TRAINING] Filtered %d canary examples from training data", filtered)
    except Exception as e:
        logger.debug("[TRAINING] Canary exclusion skipped: %s", e)

    # #116 — Exclude partial-close examples from training (stored for review only)
    examples = [e for e in examples if "partial" not in (e.get("source") or "")]

    # Fix for #273: Exclude examples with empty output_text.
    # Outcome-conditioned templates are stored with output_text="" as placeholders
    # for deferred batch generation. If batch generation hasn't run, these empty
    # examples would teach the model to produce empty responses, severely
    # corrupting the fine-tuning signal.
    before_empty_filter = len(examples)
    examples = [e for e in examples if (e.get("output_text") or "").strip()]
    empty_filtered = before_empty_filter - len(examples)
    if empty_filtered:
        logger.warning("[TRAINING] Filtered %d examples with empty output_text", empty_filtered)

    if not examples:
        for fname in ("dataset.jsonl", "holdout.jsonl", "stage1_structure.jsonl",
                       "stage2_evidence.jsonl", "stage3_decision.jsonl"):
            open(str(Path(output_dir) / fname), "w").close()
        split_info = {"total_examples": total, "training_examples": 0, "holdout_examples": 0,
                      "filtered_empty": empty_filtered}
        with open(str(Path(output_dir) / "split_info.json"), "w") as f:
            json.dump(split_info, f, indent=2)
        return {"training": 0, "holdout": 0}, 0

    # #114 -- Apply temporal split FIRST, then quality filter within each split.
    # WHY this order matters: if we quality-filter first, we might remove recent
    # examples that would have been in the holdout set, causing the temporal
    # boundary to shift backward and leak more-recent training data. By splitting
    # first and then filtering independently within each split, the temporal
    # boundary remains fixed regardless of which examples pass quality checks.
    from datetime import datetime as _dt, timedelta as _td

    split_idx = int(len(examples) * (1 - holdout_pct))
    if split_idx >= len(examples):
        split_idx = len(examples) - 1

    split_date = examples[split_idx]["created_at"][:10] if split_idx < len(examples) else ""

    # WHY 5-day gap between training and holdout: trades that span the split
    # boundary (opened during training window, closed during holdout window)
    # would leak information in both directions. A 5-day gap exceeds the
    # median holding period (~3 days for pullback setups), ensuring clean
    # separation. Examples falling within the gap are discarded -- they belong
    # to neither split.
    holdout_start_idx = split_idx
    if split_date:
        try:
            split_dt = _dt.fromisoformat(split_date)
            gap_dt = split_dt + _td(days=5)
            gap_date = gap_dt.strftime("%Y-%m-%d")
            for i in range(split_idx, len(examples)):
                if examples[i]["created_at"][:10] >= gap_date:
                    holdout_start_idx = i
                    break
            else:
                holdout_start_idx = len(examples)
        except (ValueError, TypeError):
            holdout_start_idx = split_idx

    train_examples_raw = examples[:split_idx]
    holdout_examples_raw = examples[holdout_start_idx:]

    # Quality filter applied AFTER temporal split -- independently per split.
    # WHY >= 3.0 threshold: the quality scorer rates 1-5, where 3 is "adequate
    # analytical structure with minor issues." Below 3 indicates missing thesis,
    # factual errors, or format non-compliance. None means unscored (new examples
    # awaiting the between-scan scoring window in scheduler/scorer.py).
    def _quality_ok(e):
        # #330: safe_numeric guards against SQLite returning str instead of float
        from src.utils.type_safety import safe_numeric
        score = e.get("quality_score_auto")
        return score is None or safe_numeric(score, 0.0) >= 3.0

    train_examples = [e for e in train_examples_raw if _quality_ok(e)]
    holdout_examples = [e for e in holdout_examples_raw if _quality_ok(e)]

    # #617 — surface the corpus-stall failure mode that pre-fix produced
    # silent zero-holdout. If train_examples is populated but holdout is
    # empty, the 5-day gap pushed holdout past the end of corpus. Model
    # evaluation is blocked until new examples land.
    if train_examples and not holdout_examples:
        most_recent = examples[-1]["created_at"][:10] if examples else "unknown"
        try:
            from datetime import datetime as _dt2
            days_stale = (_dt2.now() - _dt2.fromisoformat(most_recent)).days
        except (ValueError, TypeError):
            days_stale = -1
        logger.error(
            "[TRAINER] HOLDOUT EMPTY: corpus most recent %s (%dd stale) — "
            "5-day gap pushed holdout past end of corpus. Model evaluation BLOCKED.",
            most_recent, days_stale,
        )
        if alert_on_empty_holdout:
            safe_send(
                "trainer_holdout_empty",
                train_count=len(train_examples),
                most_recent_date=most_recent,
                days_stale=days_stale,
            )

    def _write_jsonl(path, exs):
        with open(path, "w") as f:
            for ex in exs:
                f.write(json.dumps({
                    "instruction": ex["instruction"],
                    "input": ex["input_text"],
                    "output": ex["output_text"],
                }) + "\n")

    # Write combined dataset (backward compat)
    _write_jsonl(str(Path(output_dir) / "dataset.jsonl"), train_examples)

    # Write stage-split files
    stage_map = {"structure": [], "evidence": [], "decision": []}
    for ex in train_examples:
        stage = ex.get("curriculum_stage") or "structure"
        stage_map.setdefault(stage, []).append(ex)

    _write_jsonl(str(Path(output_dir) / "stage1_structure.jsonl"), stage_map.get("structure", []))
    _write_jsonl(str(Path(output_dir) / "stage2_evidence.jsonl"), stage_map.get("evidence", []))
    _write_jsonl(str(Path(output_dir) / "stage3_decision.jsonl"), stage_map.get("decision", []))

    # Write holdout
    holdout_path = str(Path(output_dir) / "holdout.jsonl")
    with open(holdout_path, "w") as f:
        for ex in holdout_examples:
            f.write(json.dumps({
                "instruction": ex["instruction"],
                "input": ex["input_text"],
                "output": ex["output_text"],
                "created_at": ex["created_at"],
            }) + "\n")

    train_dates = [e["created_at"][:10] for e in train_examples] if train_examples else []
    holdout_dates = [e["created_at"][:10] for e in holdout_examples] if holdout_examples else []

    gap_days = 0
    if train_dates and holdout_dates:
        try:
            gap_days = (_dt.fromisoformat(holdout_dates[0]) - _dt.fromisoformat(train_dates[-1])).days
        except (ValueError, TypeError):
            pass

    split_info = {
        "total_examples": total,
        "quality_filtered": total - len(examples) + len(holdout_examples) + len(train_examples),
        "training_examples": len(train_examples),
        "holdout_examples": len(holdout_examples),
        "stage_counts": {k: len(v) for k, v in stage_map.items()},
        "training_date_range": {
            "start": train_dates[0] if train_dates else None,
            "end": train_dates[-1] if train_dates else None,
        },
        "holdout_date_range": {
            "start": holdout_dates[0] if holdout_dates else None,
            "end": holdout_dates[-1] if holdout_dates else None,
        },
        "temporal_gap_days": gap_days,
    }
    with open(str(Path(output_dir) / "split_info.json"), "w") as f:
        json.dump(split_info, f, indent=2)

    return {"training": len(train_examples), "holdout": len(holdout_examples)}, total


def evaluate_on_holdout(model_name: str = "halcyon-latest",
                        db_path: str = DB_PATH) -> dict:
    """Run the trained model on holdout examples and measure quality.

    WHY LLM-as-judge (Claude) instead of automated metrics: BLEU/ROUGE are
    useless for trade analysis because there are many valid ways to express
    the same thesis. Claude evaluates semantic quality -- thesis clarity,
    evidence quality, risk assessment, technical accuracy, actionability --
    which are the actual dimensions that matter for training data quality.

    WHY compare against gold standard: the quality_gap metric (gold - model)
    reveals whether the model is approaching human-quality analysis. A
    persistent gap > 0.5 suggests the training data or curriculum needs
    adjustment; a gap < 0.3 suggests the model is ready for more weight
    in the champion-challenger framework.

    For each holdout example:
    1. Feed the input to the trained model (via Ollama)
    2. Score the model's output with the LLM-as-judge (Claude)
    3. Compare model output quality against the gold-standard output

    Returns a dict with holdout evaluation metrics.
    """
    holdout_path = Path("training_data") / "holdout.jsonl"
    if not holdout_path.exists():
        return {"holdout_count": 0, "avg_quality_score": 0, "error": "No holdout file found"}

    examples = []
    with open(holdout_path) as f:
        for line in f:
            if line.strip():
                examples.append(json.loads(line))

    if not examples:
        return {"holdout_count": 0, "avg_quality_score": 0}

    from src.llm.client import generate
    from src.training.claude_client import generate_training_example

    scores = []
    gold_scores = []
    format_passes = 0

    JUDGE_PROMPT = """Rate this trade analysis on a 1-5 scale for overall quality.
Consider: thesis clarity, evidence quality, risk assessment, technical accuracy, and actionability.
Return ONLY a JSON object: {"score": N, "thesis_clarity": N, "evidence_quality": N, "risk_assessment": N, "technical_accuracy": N, "actionability": N}
where each N is 1-5."""

    for ex in examples:
        # Generate from the trained model
        model_output = generate(ex["input"], ex["instruction"])
        if not model_output:
            continue

        # Check format compliance (XML or plain text)
        if "<why_now>" in model_output and "<analysis>" in model_output:
            format_passes += 1
        elif "WHY NOW" in model_output.upper() and "DEEPER ANALYSIS" in model_output.upper():
            format_passes += 1

        # Score model output
        judge_input = f"ANALYSIS TO RATE:\n{model_output}"
        score_text = generate_training_example(JUDGE_PROMPT, judge_input, purpose="scoring")
        if score_text:
            try:
                # Try to parse JSON from response
                import re
                json_match = re.search(r'\{[^}]+\}', score_text)
                if json_match:
                    score_data = json.loads(json_match.group())
                    scores.append(score_data.get("score", 3))
            except (json.JSONDecodeError, AttributeError):
                pass

        # Score gold standard output
        gold_input = f"ANALYSIS TO RATE:\n{ex['output']}"
        gold_text = generate_training_example(JUDGE_PROMPT, gold_input, purpose="scoring")
        if gold_text:
            try:
                json_match = re.search(r'\{[^}]+\}', gold_text)
                if json_match:
                    gold_data = json.loads(json_match.group())
                    gold_scores.append(gold_data.get("score", 3))
            except (json.JSONDecodeError, AttributeError):
                pass

    avg_score = sum(scores) / len(scores) if scores else 0
    avg_gold = sum(gold_scores) / len(gold_scores) if gold_scores else 0

    result = {
        "holdout_count": len(examples),
        "evaluated_count": len(scores),
        "avg_quality_score": round(avg_score, 2),
        "avg_gold_standard_score": round(avg_gold, 2),
        "quality_gap": round(avg_gold - avg_score, 2),
        "format_compliance": round(format_passes / len(examples), 2) if examples else 0,
    }

    logger.info("[TRAINING] Holdout evaluation: avg_score=%.2f gold=%.2f gap=%.2f",
                avg_score, avg_gold, avg_gold - avg_score)
    return result


def run_fine_tune(db_path: str = DB_PATH) -> dict | None:
    """Run the full fine-tuning pipeline.

    Returns the new model version record on success, or None on failure.
    """
    # Step 1: Export training data with holdout split
    split_counts, example_count = export_training_data(db_path=db_path)
    if example_count == 0:
        print("[TRAINING] No training examples to fine-tune on.")
        return None

    train_count = split_counts.get("training", example_count)
    holdout_count = split_counts.get("holdout", 0)
    print(f"[TRAINING] Exported {train_count} training + {holdout_count} holdout examples")
    if train_count > 0 and holdout_count == 0:
        msg = (
            "[TRAINING] Skipping fine-tune: HOLDOUT EMPTY after 5-day "
            "temporal gap. Model training and promotion are blocked until "
            "eligible holdout examples exist."
        )
        logger.error(msg)
        print(msg)
        return None

    # Step 2: Write training script (curriculum if stage files exist, legacy otherwise)
    script_path = Path("training_data") / "train.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    stage1 = Path("training_data") / "stage1_structure.jsonl"
    if stage1.exists() and stage1.stat().st_size > 0:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(CURRICULUM_TRAIN_SCRIPT)
        print("[TRAINING] Using three-stage curriculum training")
    else:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(TRAIN_SCRIPT)
        print("[TRAINING] Using single-stage training (no curriculum data)")

    print("[TRAINING] Running fine-tuning script...")

    # Step 3: Run as subprocess
    train_env = _training_subprocess_env()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=train_env,
            timeout=7200,  # 2 hour timeout
        )
    except subprocess.TimeoutExpired:
        print("[TRAINING] ERROR: Fine-tuning timed out after 2 hours")
        return None
    except Exception as e:
        print(f"[TRAINING] ERROR: Failed to run training script: {e}")
        return None

    if result.returncode != 0:
        print(f"[TRAINING] ERROR: Training script failed:")
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
        return None

    print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)

    # Step 4: Find GGUF and register in Ollama
    gguf_path = _find_gguf("training_data")
    if not gguf_path:
        print("[TRAINING] ERROR: Could not find GGUF file after training")
        return None

    # Write Ollama Modelfile
    modelfile_path = Path("training_data") / "Modelfile"
    with open(modelfile_path, "w") as f:
        f.write(f"FROM ./{gguf_path.as_posix()}\n")

    # Create model in Ollama with versioned name
    version_name = get_next_semver(db_path)
    try:
        subprocess.run(
            ["ollama", "create", version_name, "-f", str(modelfile_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=True,
        )
        # Also keep halcyonlatest as alias for backward compatibility
        subprocess.run(
            ["ollama", "cp", version_name, "halcyonlatest"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[TRAINING] ERROR: Failed to register model in Ollama: {e}")
        return None

    # Step 4b: Run canary evaluation before model promotion.
    # WHY canary before holdout: canary examples are a fixed, curated reference
    # set that never changes between training runs. If the model degrades on
    # these, it has a fundamental capability regression (not just data-dependent
    # quality variation). This is a fast, cheap gate before the expensive
    # holdout evaluation that requires Claude API calls for LLM-as-judge scoring.
    try:
        from src.training.canary import CanaryMonitor
        canary = CanaryMonitor(db_path=db_path)
        canary_result = canary.evaluate(model_version=version_name)
        if canary_result.get("degradation_detected"):
            logger.warning("[CANARY] Model failed canary evaluation: %s", canary_result.get("details"))
            print(f"[TRAINING] WARNING: Canary degradation detected — {canary_result.get('details')}")
            print("[TRAINING] Model will NOT be promoted to active.")
            return {
                "version_name": version_name,
                "examples_count": example_count,
                "canary_failed": True,
                "canary_details": canary_result.get("details"),
            }
        else:
            logger.info("[CANARY] Model passed canary evaluation (score=%.4f)", canary_result.get("avg_score", 0))
            print(f"[TRAINING] Canary evaluation passed (score={canary_result.get('avg_score', 0):.4f})")
    except Exception as e:
        logger.warning("[CANARY] Canary evaluation failed: %s — blocking promotion", e)
        print(f"[TRAINING] Canary evaluation failed: {e} — model will NOT be promoted.")
        return {
            "version_name": version_name,
            "examples_count": example_count,
            "canary_failed": True,
            "canary_details": str(e),
        }

    # Step 5: Run holdout evaluation (if holdout exists)
    holdout_eval = None
    holdout_score = None
    holdout_json = None
    holdout_path = Path("training_data") / "holdout.jsonl"
    if holdout_path.exists() and holdout_path.stat().st_size > 0:
        try:
            print("[TRAINING] Running holdout evaluation...")
            holdout_eval = evaluate_on_holdout(model_name=version_name, db_path=db_path)
            holdout_score = holdout_eval.get("avg_quality_score")
            holdout_json = json.dumps(holdout_eval)

            # Check for regression against previous version
            active = get_active_model_version(db_path)
            # WHY 0.3 regression threshold: on the 1-5 quality scale, 0.3 is
            # ~1 standard deviation of typical run-to-run variation from the
            # LLM-as-judge. A drop larger than 0.3 indicates genuine regression
            # rather than noise. The model is registered as "evaluation" (not
            # "active") so it can be inspected without affecting production.
            if active and active.get("holdout_score"):
                prev_score = active["holdout_score"]
                if holdout_score and holdout_score < prev_score - 0.3:
                    print(f"[TRAINING] WARNING: Holdout score {holdout_score:.2f} < previous {prev_score:.2f} - 0.3. "
                          f"Possible overfitting. Registering as evaluation (not active).")
                    # Register as evaluation instead of active
                    version_id = register_model_version(
                        version_name=version_name,
                        examples_count=example_count,
                        synthetic_count=get_training_example_counts(db_path).get("synthetic_claude", 0),
                        outcome_count=get_training_example_counts(db_path).get("outcome_win", 0) + get_training_example_counts(db_path).get("outcome_loss", 0),
                        model_file_path=str(gguf_path),
                        db_path=db_path,
                        holdout_score=holdout_score,
                        holdout_details=holdout_json,
                        status="evaluation",
                    )
                    return {"version_id": version_id, "version_name": version_name,
                            "examples_count": example_count, "holdout_regression": True}

                print(f"[TRAINING] Holdout evaluation: {holdout_score:.2f} (previous: {prev_score:.2f})")
            elif holdout_score:
                print(f"[TRAINING] Holdout evaluation: {holdout_score:.2f}")
        except Exception as e:
            logger.warning("[TRAINING] Holdout evaluation failed: %s", e)
            print(f"[TRAINING] Holdout evaluation failed: {e} — model will NOT be promoted.")
            return {
                "version_name": version_name,
                "examples_count": example_count,
                "holdout_failed": True,
                "holdout_error": str(e),
            }
    else:
        logger.error("[TRAINING] Holdout file missing or empty after export — blocking promotion")
        print("[TRAINING] Holdout file missing or empty — model will NOT be promoted.")
        return {
            "version_name": version_name,
            "examples_count": example_count,
            "holdout_failed": True,
            "holdout_error": "missing_or_empty_holdout",
        }

    # Step 6: Register version and update config
    counts = get_training_example_counts(db_path)

    version_id = register_model_version(
        version_name=version_name,
        examples_count=example_count,
        synthetic_count=counts.get("synthetic_claude", 0),
        outcome_count=counts.get("outcome_win", 0) + counts.get("outcome_loss", 0),
        model_file_path=str(gguf_path),
        db_path=db_path,
        holdout_score=holdout_score,
        holdout_details=holdout_json,
        status="evaluation",
    )

    # Step 6b: Promotion gate is the final activation gate. The trained model
    # remains in evaluation until this returns decision='promote'.
    try:
        gate_result = run_promotion_gate_for_version(
            version_id=version_id,
            version_name=version_name,
            db_path=db_path,
        )
    except Exception as exc:
        logger.warning("[TRAINING] Promotion gate failed: %s", exc)
        print(f"[TRAINING] Promotion gate failed: {exc} — model remains evaluation-only.")
        return {
            "version_id": version_id,
            "version_name": version_name,
            "examples_count": example_count,
            "holdout_score": holdout_score,
            "promotion_gate_failed": True,
            "promotion_gate_error": str(exc),
        }

    if gate_result.get("decision") != "promote":
        logger.warning(
            "[TRAINING] Promotion gate blocked activation for %s: %s",
            version_name, gate_result.get("decision"),
        )
        print(
            f"[TRAINING] Promotion gate decision={gate_result.get('decision')} — "
            "model remains evaluation-only."
        )
        return {
            "version_id": version_id,
            "version_name": version_name,
            "examples_count": example_count,
            "holdout_score": holdout_score,
            "promotion_gate": gate_result,
        }

    _activate_model_version(version_id, db_path)
    update_config_model(version_name)

    # Step 7: DPO refinement (if enough preference pairs exist).
    # WHY gated on 100+ pairs: DPO with fewer examples causes the model to
    # memorize specific phrasing preferences rather than learning general
    # quality signals. 100 was determined empirically -- below this threshold,
    # DPO-trained models showed worse holdout scores than SFT-only models.
    # The DPO step is non-critical: if it fails, the SFT model is already
    # registered and active. DPO is an incremental refinement, not a gate.
    try:
        from src.training.dpo_pipeline import export_preference_pairs
        dpo_count = export_preference_pairs(output_dir="training_data", db_path=db_path)
        if dpo_count >= 100:
            print(f"[TRAINING] Running DPO refinement with {dpo_count} preference pairs...")
            dpo_script_path = Path("training_data") / "train_dpo.py"
            with open(dpo_script_path, "w", encoding="utf-8") as f:
                f.write(DPO_TRAIN_SCRIPT)
            try:
                dpo_result = subprocess.run(
                    [sys.executable, str(dpo_script_path)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", env=train_env, timeout=3600,
                )
                if dpo_result.returncode == 0:
                    print("[TRAINING] DPO refinement complete")
                else:
                    print(f"[TRAINING] DPO failed (non-critical): {dpo_result.stderr[-500:]}")
            except Exception as e:
                print(f"[TRAINING] DPO failed (non-critical): {e}")
        elif dpo_count > 0:
            print(f"[TRAINING] {dpo_count} preference pairs (need >= 100 for DPO, skipping)")
    except Exception as e:
        logger.debug("[TRAINING] DPO step skipped: %s", e)

    print(f"[TRAINING] Fine-tune complete. Registered {version_name} ({example_count} examples)")

    return {
        "version_id": version_id,
        "version_name": version_name,
        "examples_count": example_count,
        "holdout_score": holdout_score,
        "promotion_gate": gate_result,
    }


def _training_subprocess_env() -> dict[str, str]:
    """Environment for Windows-safe UTF-8 training subprocesses."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _resolve_returns_for_gate(
    db_path: str = DB_PATH,
) -> tuple[list[float], list, list[int]]:
    """Fetch closed shadow trade returns for the promotion gate.

    Returns a 3-tuple (returns, dates, directions) where:
      - returns: list[float] — pnl_pct / 100.0 (raw, no rf pre-subtraction)
      - dates: list[date] — date.fromisoformat(actual_entry_time[:10])
      - directions: list[int] — +1 per trade (long-only per registry.py:202)

    Rows with NULL actual_entry_time are filtered by SQL.
    Returns ([], [], []) when no qualifying rows are found.
    """
    from datetime import date as _date
    try:
        from src.journal.store import initialize_database
        initialize_database(db_path)
        with connect_db(db_path) as conn:
            rows = conn.execute(
                """SELECT pnl_pct, actual_entry_time FROM shadow_trades
                   WHERE status IN ('closed','stopped_out','target_hit','manually_closed')
                     AND pnl_pct IS NOT NULL
                     AND actual_entry_time IS NOT NULL
                     AND COALESCE(quarantined, 0) = 0
                   ORDER BY actual_exit_time ASC"""
            ).fetchall()
        if not rows:
            return ([], [], [])
        returns = [float(r[0]) / 100.0 for r in rows]
        dates = [_date.fromisoformat(r[1][:10]) for r in rows]
        directions = [1] * len(rows)
        return (returns, dates, directions)
    except Exception as exc:
        logger.warning("[PROMOTION_GATE] _resolve_returns_for_gate failed: %s", exc)
        return ([], [], [])


def _apply_gate_decision(decision: str, version_id: str, db_path: str = DB_PATH) -> None:
    """Write the gate decision back to model_versions.status."""
    status_map = {
        "promote": "promoted",
        "reject": "rejected_by_gate",
        "defer": "pending_review",
    }
    new_status = status_map.get(decision)
    if new_status is None:
        logger.warning("[PROMOTION_GATE] Unknown decision %r — status not updated", decision)
        return
    with connect_db(db_path) as conn:
        conn.execute(
            "UPDATE model_versions SET status = ? WHERE version_id = ?",
            (new_status, version_id),
        )
        conn.commit()
    logger.info(
        "[PROMOTION_GATE] version_id=%s decision=%s → status=%s",
        version_id, decision, new_status,
    )


def _activate_model_version(version_id: str, db_path: str = DB_PATH) -> None:
    """Promote an evaluation model to active after all gates pass."""
    with connect_db(db_path) as conn:
        conn.execute("UPDATE model_versions SET status = 'retired' WHERE status = 'active'")
        conn.execute("UPDATE model_versions SET status = 'active' WHERE version_id = ?", (version_id,))
        conn.commit()
    logger.info("[PROMOTION_GATE] Activated model version_id=%s after gate pass", version_id)


def run_promotion_gate_for_version(
    version_id: str,
    version_name: str,
    db_path: str = DB_PATH,
    n_trials: int = 1,
) -> dict:
    """Run the promotion gate for an existing model version and record the result.

    Fetches shadow trade returns, runs the 5-method vote, and updates
    model_versions.status to 'promoted' / 'rejected_by_gate' / 'pending_review'.
    When no returns are available the gate is skipped (status unchanged).

    Returns a dict with keys: version_id, version_name, decision, status.
    """
    _gate_data = _resolve_returns_for_gate(db_path)
    if isinstance(_gate_data, tuple) and len(_gate_data) == 3:
        returns, dates, directions = _gate_data
    else:
        returns = list(_gate_data) if _gate_data else []
        dates = []
        directions = []
    if not returns:
        logger.info(
            "[PROMOTION_GATE] No qualifying returns for version %s — gate skipped",
            version_name,
        )
        print(f"[PROMOTION_GATE] No qualifying returns for {version_name} — gate skipped")
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM model_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        current_status = row[0] if row else "unknown"
        return {
            "version_id": version_id,
            "version_name": version_name,
            "decision": "skipped",
            "status": current_status,
        }

    print(f"[PROMOTION_GATE] Running gate for {version_name} ({len(returns)} trade returns) ...")
    result = promotion_gate(returns, n_trials=n_trials, dates=dates, directions=directions)
    decision = result.get("decision", "reject")
    _apply_gate_decision(decision, version_id, db_path)

    try:
        import json as _json
        from src.utils.activity_logger import log_activity
        log_activity(
            "promotion_gate",
            _json.dumps({
                "version_name": version_name,
                "decision": decision,
                "n_obs": result.get("n_obs"),
                "n_pass": result.get("details", {}).get("n_pass"),
            }),
            db_path=db_path,
        )
    except Exception as exc:
        logger.debug("[PROMOTION_GATE] activity_log write failed: %s", exc)

    status_map = {"promote": "promoted", "reject": "rejected_by_gate", "defer": "pending_review"}
    final_status = status_map.get(decision, decision)
    print(
        f"[PROMOTION_GATE] {version_name}: decision={decision} → status={final_status} "
        f"(n_obs={result.get('n_obs')}, n_pass={result.get('details', {}).get('n_pass')})"
    )
    return {
        "version_id": version_id,
        "version_name": version_name,
        "decision": decision,
        "status": final_status,
        "gate_result": result,
    }


def _find_gguf(directory: str) -> str | None:
    """Find GGUF file in directory."""
    for p in Path(directory).rglob("*.gguf"):
        return str(p)
    return None


def check_model_performance(db_path: str = DB_PATH) -> dict:
    """Check if the active model is performing well vs previous version.

    WHY auto-rollback: a fine-tuned model that degrades live trading
    performance must be reverted immediately -- even a few days of degraded
    conviction scoring can produce losing trades that take weeks to close.
    The 10-trade minimum before comparison prevents premature rollback from
    small-sample noise (e.g., 2 losses in 3 trades is not statistically
    meaningful, but 3 wins in 10 with worse expectancy is).

    Returns action dict with 'action' key: 'rolled_back', 'waiting', or 'none'.
    """
    config = load_config()
    training_cfg = config.get("training", {})
    expectancy_threshold = training_cfg.get("auto_rollback_expectancy_drop", 0.20)
    winrate_threshold = training_cfg.get("auto_rollback_winrate_drop", 0.10)

    perf = get_performance_by_version(db_path)
    if len(perf) < 2:
        # Need at least 2 versions to compare
        active = get_active_model_version(db_path)
        if active:
            current_perf = next((p for p in perf if p["version_name"] == active["version_name"]), None)
            if current_perf and current_perf["trade_count"] < 10:
                return {"action": "waiting", "trades_needed": 10 - current_perf["trade_count"]}
        return {"action": "waiting", "trades_needed": 10}

    current_version = perf[0]
    previous_version = perf[1]

    if current_version["trade_count"] < 10:
        return {"action": "waiting", "trades_needed": 10 - current_version["trade_count"]}

    # Compare performance
    current_exp = current_version.get("expectancy") or 0
    previous_exp = previous_version.get("expectancy") or 0
    exp_drop = previous_exp - current_exp

    current_wr = current_version.get("win_rate", 0)
    previous_wr = previous_version.get("win_rate", 0)
    wr_drop = (previous_wr - current_wr) / 100  # Convert percentage to decimal

    if exp_drop > expectancy_threshold:
        restored = rollback_model(db_path)
        restored_name = restored["version_name"] if restored else "base"
        print(f"[TRAINING] Auto-rollback: {current_version['version_name']} -> {restored_name} (expectancy dropped ${exp_drop:.2f})")
        return {
            "action": "rolled_back",
            "reason": f"Expectancy dropped ${exp_drop:.2f} (threshold: ${expectancy_threshold:.2f})",
            "restored_version": restored_name,
        }

    if wr_drop > winrate_threshold:
        restored = rollback_model(db_path)
        restored_name = restored["version_name"] if restored else "base"
        print(f"[TRAINING] Auto-rollback: {current_version['version_name']} -> {restored_name} (win rate dropped {wr_drop*100:.1f}%)")
        return {
            "action": "rolled_back",
            "reason": f"Win rate dropped {wr_drop*100:.1f}% (threshold: {winrate_threshold*100:.0f}%)",
            "restored_version": restored_name,
        }

    return {"action": "none", "status": "performing well"}


def quarantine_stuck_outcome_templates(db_path: str = DB_PATH) -> int:
    """Quarantine all outcome_template_* rows with empty output_text (#625).

    The deferred-batch fill process for these placeholder rows never ran,
    leaving 75 rows that the trainer defensively filters every cycle.  This
    function marks them quarantined=1 so the trainer's DB-level WHERE clause
    never fetches them, eliminating the recurring filtered-75 warning.

    Idempotent: rows already quarantined are not re-counted.

    Returns:
        Number of rows newly quarantined (0 if all already quarantined).
    """
    import sqlite3 as _sqlite3
    with _sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE training_examples "
            "SET quarantined = 1, quarantine_reason = 'OUTCOME_TEMPLATE_FILLER_UNSCHEDULED' "
            "WHERE source LIKE 'outcome_template_%' "
            "AND (output_text IS NULL OR TRIM(output_text) = '') "
            "AND COALESCE(quarantined, 0) = 0"
        )
        affected = cursor.rowcount
        conn.commit()
    if affected:
        logger.info(
            "[TRAINING] Quarantined %d stuck outcome_template_* rows "
            "(reason: OUTCOME_TEMPLATE_FILLER_UNSCHEDULED)",
            affected,
        )
    return affected
