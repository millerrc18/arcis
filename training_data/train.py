# training_data/train.py -- DEPRECATED: legacy single-stage trainer
#
# This file is OVERWRITTEN by `src/training/trainer.py` on every training run
# (see `TRAIN_SCRIPT` and `CURRICULUM_TRAIN_SCRIPT` constants there). Whatever
# is committed here is a placeholder; trainer.py picks CURRICULUM_TRAIN_SCRIPT
# (PEFT/TRL 0.24, the hardware-validated primary path) when curriculum data
# exists, else falls back to TRAIN_SCRIPT (this Unsloth single-stage path,
# kept only for legacy archive purposes).
#
# Editing this file directly has NO production effect — to change training
# behavior, edit `src/training/trainer.py:TRAIN_SCRIPT` or `:CURRICULUM_TRAIN_SCRIPT`.
#
# Rationale: Unsloth was rejected as the production training stack because
# it OOMs on 12GB. Do not revive this path without re-validating GPU memory.
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
