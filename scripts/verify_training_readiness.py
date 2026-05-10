"""Verify that the post-3090-upgrade trainer is ready to run end-to-end.

Non-destructive, fail-fast script. Runs 5 checks sequentially and stops at
the first hard failure. Intended to be run by the OPERATOR on the machine
with the RTX 3090 -- not in CI / worktrees that may lack torch.cuda.

OPERATOR EXPECTED OUTPUT (clean machine with RTX 3090 + all deps):
    [VERIFY-1] CUDA check: OK
      Device: NVIDIA GeForce RTX 3090, 22.3 GB free VRAM
    [VERIFY-2] Dependency imports: OK
      All trainer dependencies imported OK
    [VERIFY-3] Stage files: OK
      Stage 1: training_data/stage1_structure.jsonl -- 1200 examples
      Stage 2: training_data/stage2_evidence.jsonl -- MISSING (soft-warn)
      Stage 3: training_data/stage3_decision.jsonl -- MISSING (soft-warn)
    [VERIFY-4] Trainer dry-run: OK
      1-step trainer dry-run completed successfully
    [VERIFY-5] GGUF artifact: OK
      halcyon-latest.gguf present, 5134.7 MB
    READINESS: PASS

NOTE: Check 4 is intentionally capped at max_steps=1. Running full training
epochs is NOT readiness verification -- it is training itself (10+ minutes).
That is the operator's decision, not this script's responsibility.

Called by: operator (one-shot diagnostic)
Calls: torch, transformers, peft, trl, datasets
Owns tables: none
Config keys: none
Tests: tests/test_verify_training_readiness.py
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

try:
    import torch
except ImportError:
    torch = None

STAGE_PATHS = [
    "training_data/stage1_structure.jsonl",
    "training_data/stage2_evidence.jsonl",
    "training_data/stage3_decision.jsonl",
]

REQUIRED_KEYS = {"instruction", "input", "output"}


def _check_cuda():
    """Return (ok, message) for CUDA + VRAM check."""
    if torch is None or not torch.cuda.is_available():
        return (
            False,
            "CUDA not available; install a torch build with CUDA 12.x support",
        )

    device_name = torch.cuda.get_device_name(0)
    free_vram_gb = torch.cuda.mem_get_info()[0] / 1e9

    lines = [f"Device: {device_name}, {free_vram_gb:.1f} GB free VRAM"]

    if "3090" not in device_name:
        lines.append(f"  WARN: expected RTX 3090 but got '{device_name}' -- continuing")

    if free_vram_gb < 20.0:
        return (
            False,
            "\n".join(lines)
            + f"\n  FAIL: {free_vram_gb:.1f} GB free < 20.0 GB required for safe quantization",
        )

    return True, "\n".join(lines)


def _check_deps():
    """Return (ok, message) for trainer dependency imports."""
    import_specs = [
        ("transformers", "transformers", "AutoModelForCausalLM"),
        ("peft", "peft", "LoraConfig"),
        ("trl", "trl", "SFTTrainer"),
        ("datasets", "datasets", "Dataset"),
        ("bitsandbytes", "bitsandbytes", None),
    ]

    failures = []
    for pkg_name, module_name, attr in import_specs:
        try:
            mod = __import__(module_name)
            if attr:
                getattr(mod, attr)
        except ImportError as exc:
            failures.append(f"  MISSING {pkg_name}: {exc}")

    if failures:
        return False, "Dependency import failures:\n" + "\n".join(failures)
    return True, "All trainer dependencies imported OK"


def _validate_first_five(path):
    """Return (ok, msg) after validating first 5 lines of a jsonl file."""
    with open(path, encoding="utf-8") as fh:
        for i, raw_line in enumerate(fh):
            if i >= 5:
                break
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                return False, f"{path} line {i + 1}: malformed JSON -- {exc}"
            missing = REQUIRED_KEYS - set(record.keys())
            if missing:
                return (
                    False,
                    f"{path} line {i + 1}: invalid JSON record -- missing keys {sorted(missing)}",
                )
    return True, "OK"


def _check_stage_files(paths=None):
    """Return (ok, message) for stage jsonl file checks.

    Soft-warn on missing individual stages; hard-fail only if ALL are missing
    or any present file has malformed first-5 lines.
    """
    if paths is None:
        paths = STAGE_PATHS

    missing = []
    present = []
    summary_lines = []

    for i, path in enumerate(paths, start=1):
        p = Path(path)
        label = f"Stage {i}: {path}"
        if not p.exists():
            missing.append(path)
            summary_lines.append(f"  {label} -- MISSING (soft-warn)")
            continue

        line_count = sum(1 for _ in p.open(encoding="utf-8"))
        summary_lines.append(f"  {label} -- {line_count} examples")
        present.append(path)

    for path in present:
        ok, msg = _validate_first_five(path)
        if not ok:
            return False, f"JSON validation failed: {msg}"

    if missing and len(missing) == len(paths) and len(paths) >= 3:
        return False, "All stage files missing -- nothing to train on\n" + "\n".join(summary_lines)

    return True, "\n".join(summary_lines)


def _build_peft_model(tmp_dir):
    """Load base model + tokenizer + LoRA adapter for dry-run; return (model, tokenizer)."""
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype="float16",
    )
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-0.5B",
        quantization_config=bnb_config,
        device_map="auto",
    )
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = prepare_model_for_kbit_training(model)
    lora_cfg = LoraConfig(r=4, lora_alpha=8, target_modules=["q_proj", "v_proj"])
    return get_peft_model(model, lora_cfg), tokenizer


def _run_one_step(examples, tmp_dir):
    """Run a single SFT training step; return (ok, message)."""
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    def _fmt(ex):
        return {
            "text": (
                f"<|system|>{ex['instruction']}<|user|>{ex['input']}"
                f"<|assistant|>{ex['output']}"
            )
        }

    dataset = Dataset.from_list([_fmt(e) for e in examples])
    model, tokenizer = _build_peft_model(tmp_dir)

    sft_cfg = SFTConfig(
        output_dir=str(tmp_dir),
        num_train_epochs=1,
        max_steps=1,
        per_device_train_batch_size=1,
        report_to="none",
        logging_steps=1,
    )
    trainer = SFTTrainer(
        model=model,
        args=sft_cfg,
        train_dataset=dataset,
        processing_class=tokenizer,
    )
    trainer.train()
    return True, "1-step trainer dry-run completed successfully"


def _check_trainer_dry_run(stage_paths=None):
    """Return (ok, message) for the 1-step trainer dry-run."""
    if stage_paths is None:
        stage_paths = STAGE_PATHS

    source_path = None
    for p in stage_paths:
        if Path(p).exists():
            source_path = p
            break

    if source_path is None:
        return True, "Skipped -- no stage files present"

    examples = []
    with open(source_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
            if len(examples) >= 5:
                break

    if len(examples) < 1:
        return False, f"Could not read examples from {source_path}"

    ts = int(time.time())
    tmp_dir = Path(tempfile.gettempdir()) / f"trainer-dryrun-{ts}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        return _run_one_step(examples, tmp_dir)
    except Exception as exc:
        return False, f"Trainer dry-run raised: {exc}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _check_gguf():
    """Return (ok, message) for GGUF artifact presence check."""
    gguf_file = Path("training_data/halcyon-latest.gguf")
    gguf_dir = Path("training_data/halcyon-latest")

    if not gguf_file.exists() and not gguf_dir.exists():
        return True, "halcyon-latest.gguf / halcyon-latest/ not found -- soft-warn (first-run case)"

    if gguf_file.exists():
        size_mb = gguf_file.stat().st_size / 1e6
        if size_mb < 1.0:
            return (
                False,
                f"halcyon-latest.gguf exists but is only {size_mb:.3f} MB -- possible zero-byte corruption",
            )
        return True, f"halcyon-latest.gguf present, {size_mb:.1f} MB"

    return True, "halcyon-latest/ directory present (split GGUF)"


def main():
    """Run all 5 readiness checks sequentially; exit 0 on pass, non-zero on fail."""
    failed_checks = []
    cuda_ok = False
    all_missing = False

    ok, msg = _check_cuda()
    cuda_ok = ok
    print(f"[VERIFY-1] CUDA check: {'OK' if ok else 'FAIL'}")
    print(f"  {msg}")
    if not ok:
        failed_checks.append(1)

    ok, msg = _check_deps()
    print(f"[VERIFY-2] Dependency imports: {'OK' if ok else 'FAIL'}")
    print(f"  {msg}")
    if not ok:
        failed_checks.append(2)

    ok, msg = _check_stage_files()
    all_missing = "All stage files missing" in msg
    print(f"[VERIFY-3] Stage files: {'OK' if ok else 'FAIL'}")
    print(f"{msg}")
    if not ok:
        failed_checks.append(3)

    if not cuda_ok:
        print("[VERIFY-4] Trainer dry-run: SKIPPED (no CUDA)")
    elif all_missing:
        print("[VERIFY-4] Trainer dry-run: SKIPPED (no stage files)")
    else:
        ok, msg = _check_trainer_dry_run()
        print(f"[VERIFY-4] Trainer dry-run: {'OK' if ok else 'FAIL'}")
        print(f"  {msg}")
        if not ok:
            failed_checks.append(4)

    ok, msg = _check_gguf()
    print(f"[VERIFY-5] GGUF artifact: {'OK' if ok else 'FAIL'}")
    print(f"  {msg}")
    if not ok:
        failed_checks.append(5)

    if failed_checks:
        print(f"\nREADINESS: FAIL ({len(failed_checks)}/5 checks failed: {failed_checks})")
        sys.exit(1)
    else:
        print("\nREADINESS: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
