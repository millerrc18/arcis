"""Fine-tuning orchestrator with Unsloth and auto-rollback.

Called by: api.routes.actions, cli.commands, scheduler.watch, services.training_service, training.report
Calls: config, llm.client, training.canary, training.claude_client, training.curriculum, training.dpo_pipeline, training.versioning
Owns tables: none
Config keys: auto_rollback_expectancy_drop, auto_rollback_winrate_drop, auto_train_min_examples, auto_train_threshold, auto_train_time_days, enabled, training
Tests: tests/test_holdout.py, tests/test_leakage_detector.py, tests/test_trainer.py, tests/test_training_data.py
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import load_config
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

TRAIN_SCRIPT = '''# training_data/train.py — DEPRECATED: legacy single-stage trainer
# Uses old Unsloth API. The curriculum script (CURRICULUM_TRAIN_SCRIPT) is the
# primary training path and uses standard PEFT/TRL 0.24 API instead.
import json, sys, os
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
    with open("training_data/dataset.jsonl") as f:
        for line in f: examples.append(json.loads(line))

    def fmt(ex):
        return {"text": tokenizer.apply_chat_template(
            [{"role":"system","content":ex["instruction"]},
             {"role":"user","content":ex["input"]},
             {"role":"assistant","content":ex["output"]}], tokenize=False)}

    dataset = Dataset.from_list(examples).map(fmt)
    trainer = SFTTrainer(model=model, processing_class=tokenizer,
        train_dataset=dataset, max_seq_length=1024,
        args=TrainingArguments(per_device_train_batch_size=1, gradient_accumulation_steps=16,
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

CURRICULUM_TRAIN_SCRIPT = '''
import json, sys, os, torch

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
        with open(fn) as f:
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
        sft_config = SFTConfig(
            per_device_train_batch_size=1,
            gradient_accumulation_steps=16,
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
    print("[TRAIN] Merging LoRA and exporting GGUF...")
    try:
        from unsloth import FastLanguageModel
        merged_model, merged_tok = FastLanguageModel.from_pretrained(
            model_name="training_data/lora_adapter", max_seq_length=512, dtype=None, load_in_4bit=True)
        merged_model.save_pretrained_gguf("training_data/halcyon-latest", merged_tok, quantization_method="q5_k_m")
    except Exception as e:
        print(f"[TRAIN] GGUF export via Unsloth failed: {e}")
        print("[TRAIN] LoRA adapter saved. Convert to GGUF manually with llama.cpp if needed.")

    print("TRAINING COMPLETE")

if __name__ == "__main__":
    main()
'''

DPO_TRAIN_SCRIPT = '''
import json, sys, os
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
    with open("training_data/preference_pairs.jsonl") as f:
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


def should_train(db_path: str = "ai_research_desk.sqlite3") -> tuple[bool, str]:
    """Check if fine-tuning should be triggered.

    Returns (should_train, reason_string).
    """
    config = load_config()
    training_cfg = config.get("training", {})
    if not training_cfg.get("enabled", False):
        return False, "Training disabled in config"

    threshold = training_cfg.get("auto_train_threshold", 50)
    time_days = training_cfg.get("auto_train_time_days", 7)
    min_examples = training_cfg.get("auto_train_min_examples", 20)

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
        return True, f"{new_count} new examples since last train (threshold: {threshold})"

    if days_since >= time_days and new_count >= min_examples:
        return True, f"{days_since} days since last train, {new_count} new examples"

    return False, f"{new_count} new examples, {days_since} days since last train (need {threshold} examples or {time_days} days with {min_examples}+ examples)"


def export_training_data(
    output_dir: str = "training_data",
    holdout_pct: float = 0.15,
    db_path: str = "ai_research_desk.sqlite3",
) -> tuple[dict, int]:
    """Export training data with curriculum split and chronological holdout.

    Creates:
        training_data/dataset.jsonl            (combined training — backward compat)
        training_data/stage1_structure.jsonl    (easy/clean examples)
        training_data/stage2_evidence.jsonl     (multi-source examples)
        training_data/stage3_decision.jsonl     (hard/conflicting examples)
        training_data/holdout.jsonl             (validation split — never trained on)
        training_data/split_info.json           (metadata about the split)

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

    import sqlite3 as _sqlite3
    with _sqlite3.connect(db_path) as conn:
        conn.row_factory = _sqlite3.Row
        rows = conn.execute(
            "SELECT instruction, input_text, output_text, created_at, quality_score, "
            "curriculum_stage, quality_score_auto "
            "FROM training_examples ORDER BY created_at ASC"
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

    # Quality filter: only export examples where quality_score_auto >= 3.0 (or NULL)
    examples = [e for e in examples
                if e.get("quality_score_auto") is None or e["quality_score_auto"] >= 3.0]

    # Calculate split point with 5-day temporal gap
    split_idx = int(len(examples) * (1 - holdout_pct))
    if split_idx >= len(examples):
        split_idx = len(examples) - 1

    split_date = examples[split_idx]["created_at"][:10] if split_idx < len(examples) else ""

    from datetime import datetime as _dt, timedelta as _td
    holdout_start_idx = split_idx
    if split_date:
        try:
            split_dt = _dt.fromisoformat(split_date)
            gap_dt = split_dt + _td(days=5)  # 5-day temporal gap per research recommendation
            gap_date = gap_dt.strftime("%Y-%m-%d")
            for i in range(split_idx, len(examples)):
                if examples[i]["created_at"][:10] >= gap_date:
                    holdout_start_idx = i
                    break
            else:
                holdout_start_idx = len(examples)
        except (ValueError, TypeError):
            holdout_start_idx = split_idx

    train_examples = examples[:split_idx]
    holdout_examples = examples[holdout_start_idx:]

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
                        db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Run the trained model on holdout examples and measure quality.

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


def run_fine_tune(db_path: str = "ai_research_desk.sqlite3") -> dict | None:
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

    # Step 2: Write training script (curriculum if stage files exist, legacy otherwise)
    script_path = Path("training_data") / "train.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    stage1 = Path("training_data") / "stage1_structure.jsonl"
    if stage1.exists() and stage1.stat().st_size > 0:
        with open(script_path, "w") as f:
            f.write(CURRICULUM_TRAIN_SCRIPT)
        print("[TRAINING] Using three-stage curriculum training")
    else:
        with open(script_path, "w") as f:
            f.write(TRAIN_SCRIPT)
        print("[TRAINING] Using single-stage training (no curriculum data)")

    print("[TRAINING] Running fine-tuning script...")

    # Step 3: Run as subprocess
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
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
        f.write(f"FROM ./{gguf_path}\n")

    # Create model in Ollama with versioned name
    version_name = get_next_semver(db_path)
    try:
        subprocess.run(
            ["ollama", "create", version_name, "-f", str(modelfile_path)],
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        # Also keep halcyonlatest as alias for backward compatibility
        subprocess.run(
            ["ollama", "cp", version_name, "halcyonlatest"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[TRAINING] ERROR: Failed to register model in Ollama: {e}")
        return None

    # Step 4b: Run canary evaluation before model promotion
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
        logger.warning("[CANARY] Canary evaluation failed: %s — continuing without", e)
        print(f"[TRAINING] Canary evaluation failed: {e} — continuing without")

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
            print(f"[TRAINING] Holdout evaluation failed: {e} — continuing without")

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
    )

    # Update local config to point to new version
    update_config_model(version_name)

    # Step 7: DPO refinement (if enough preference pairs exist)
    try:
        from src.training.dpo_pipeline import export_preference_pairs
        dpo_count = export_preference_pairs(output_dir="training_data", db_path=db_path)
        if dpo_count >= 100:
            print(f"[TRAINING] Running DPO refinement with {dpo_count} preference pairs...")
            dpo_script_path = Path("training_data") / "train_dpo.py"
            with open(dpo_script_path, "w") as f:
                f.write(DPO_TRAIN_SCRIPT)
            try:
                dpo_result = subprocess.run(
                    [sys.executable, str(dpo_script_path)],
                    capture_output=True, text=True, timeout=3600,
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
    }


def _find_gguf(directory: str) -> str | None:
    """Find GGUF file in directory."""
    for p in Path(directory).rglob("*.gguf"):
        return str(p)
    return None


def check_model_performance(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Check if the active model is performing well vs previous version.

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
