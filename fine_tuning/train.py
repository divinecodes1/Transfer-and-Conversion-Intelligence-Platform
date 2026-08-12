"""
Transfer & Conversion Intelligence Platform :: LoRA fine-tuning experiment.

**This is not on the critical path, and the platform does not depend on it.**
Everything the assistant does today is deterministic: resolution, filters,
permissions and arithmetic. A tuned model would only ever improve *phrasing* --
how fluently a governed answer is expressed -- and would still emit the same
validated MetricQuery against the same catalogue.

Stated plainly, because it is the honest position: in production I would first
establish whether governed metric tools plus retrieval are sufficient, and expect
that they are. Fine-tuning is worth demonstrating and worth understanding; it is
not worth putting in the answer path for a reporting platform where being wrong
is expensive and being fluent is not the problem.

Deliberately kept out of requirements.txt -- torch, transformers and peft are a
multi-gigabyte install for an experiment the system does not need:

    pip install torch transformers peft datasets accelerate bitsandbytes
    python fine_tuning/dataset.py
    python fine_tuning/train.py --model Qwen/Qwen2.5-0.5B-Instruct
"""
import argparse
import json
import os


def load_pairs(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def format_example(pair, eos):
    """Chat-style supervised target. Only the response is learned."""
    return (f"<|user|>\n{pair['instruction']}\n"
            f"<|assistant|>\n{pair['response']}{eos}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct",
                    help="a small instruct model; this is a demonstration")
    ap.add_argument("--data", default=os.path.join(
        os.path.dirname(__file__), "dataset.jsonl"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "adapter"))
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              DataCollatorForLanguageModeling, Trainer,
                              TrainingArguments)

    pairs = load_pairs(args.data)
    print(f"{len(pairs)} instruction pairs "
          f"({sum(p['kind'] == 'behaviour' for p in pairs)} behavioural)")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    texts = [format_example(p, tokenizer.eos_token) for p in pairs]
    ds = Dataset.from_dict({"text": texts}).map(
        lambda b: tokenizer(b["text"], truncation=True, max_length=512),
        batched=True, remove_columns=["text"])

    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.float32)

    # LoRA rather than full fine-tuning: a few million trainable parameters
    # against a corpus of a few hundred examples. Full fine-tuning on this much
    # data would overfit and damage the base model's general ability.
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    model.print_trainable_parameters()

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.out, num_train_epochs=args.epochs,
            per_device_train_batch_size=4, gradient_accumulation_steps=4,
            learning_rate=args.lr, logging_steps=10, save_strategy="epoch",
            report_to=[]),
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"Adapter written to {args.out}")
    print("The assistant does not load this. Run fine_tuning/evaluate.py to see "
          "whether it would have been worth loading.")


if __name__ == "__main__":
    main()
