
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
        if len(ds) < 5:
            print(f"  Dataset too small for {name} ({len(ds)} examples) -- skipping")
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
