from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data/text_to_sql/v1"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "models/text_to_sql_lora/qwen2_5_coder_7b_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a LoRA adapter for Text-to-SQL.")
    parser.add_argument(
        "--model-name",
        default="Qwen/Qwen2.5-Coder-7B-Instruct",
        help="Hugging Face model id.",
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--no-eval", action="store_true")
    parser.add_argument("--no-4bit", action="store_true")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def format_example(example: dict[str, Any]) -> str:
    return f"""<|im_start|>system
Ты генерируешь безопасный PostgreSQL SQL для аналитики.
Верни только один read-only SELECT или WITH ... SELECT statement без markdown и объяснений.<|im_end|>
<|im_start|>user
{example["input"]}

Вопрос:
{example["instruction"]}<|im_end|>
<|im_start|>assistant
{example["output"]}<|im_end|>"""


def tokenize_dataset(
    *,
    rows: list[dict[str, Any]],
    tokenizer: AutoTokenizer,
    max_length: int,
) -> Dataset:
    texts = [format_example(row) for row in rows]
    dataset = Dataset.from_dict({"text": texts})

    def tokenize(batch: dict[str, list[str]]) -> dict[str, list[list[int]]]:
        tokenized = tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding=False,
        )
        tokenized["labels"] = [input_ids.copy() for input_ids in tokenized["input_ids"]]
        return tokenized

    return dataset.map(tokenize, batched=True, remove_columns=["text"])


def data_collator(tokenizer: AutoTokenizer):
    def collate(features: list[dict[str, list[int]]]) -> dict[str, torch.Tensor]:
        max_length = max(len(feature["input_ids"]) for feature in features)
        input_ids: list[list[int]] = []
        attention_mask: list[list[int]] = []
        labels: list[list[int]] = []
        pad_token_id = tokenizer.pad_token_id
        for feature in features:
            pad_length = max_length - len(feature["input_ids"])
            input_ids.append(feature["input_ids"] + [pad_token_id] * pad_length)
            attention_mask.append(feature["attention_mask"] + [0] * pad_length)
            labels.append(feature["labels"] + [-100] * pad_length)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    return collate


def load_model(
    *,
    model_name: str,
    use_4bit: bool,
    lora_r: int,
    lora_alpha: int,
    lora_dropout: float,
):
    quantization_config = None
    if use_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=quantization_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    if use_4bit:
        model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    return get_peft_model(model, lora_config)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_rows = read_jsonl(Path(args.data_dir) / "train.jsonl")
    validation_rows = read_jsonl(Path(args.data_dir) / "validation.jsonl")

    tokenizer = AutoTokenizer.from_pretrained(
        args.model_name,
        trust_remote_code=True,
        use_fast=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_dataset = tokenize_dataset(
        rows=train_rows,
        tokenizer=tokenizer,
        max_length=args.max_length,
    )
    eval_dataset = tokenize_dataset(
        rows=validation_rows,
        tokenizer=tokenizer,
        max_length=args.max_length,
    )

    model = load_model(
        model_name=args.model_name,
        use_4bit=not args.no_4bit,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
    )
    model.print_trainable_parameters()

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.per_device_train_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        eval_strategy="no" if args.no_eval else "steps",
        eval_steps=max(1, args.max_steps // 2) if not args.no_eval else None,
        save_steps=args.max_steps,
        logging_steps=1,
        bf16=True,
        gradient_checkpointing=True,
        report_to="none",
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator(tokenizer),
    )
    train_result = trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    metrics = {
        "model_name": args.model_name,
        "max_steps": args.max_steps,
        "train_examples": len(train_rows),
        "validation_examples": len(validation_rows),
        "train_metrics": train_result.metrics,
    }
    (output_dir / "training_summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
