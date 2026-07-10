# Text-to-SQL LoRA 100-Step Run 2026-07-10

## Goal

Run a longer corrected QLoRA experiment after the initial smoke and record VRAM usage during training and evaluation.

This run is still a small local experiment. It is useful for proving that the adapter can learn the V1 task shape, but it should not be treated as final model quality.

## Why VRAM Is Higher Than The Ollama Model Size

The Ollama model size, for example `4.7 GB`, is the quantized inference artifact size.

Training needs more memory:

- quantized base model in GPU memory;
- LoRA adapter weights;
- gradients for trainable LoRA weights;
- optimizer state;
- activations kept for backpropagation;
- CUDA kernels/workspace;
- PyTorch reserved memory and fragmentation;
- optional evaluation memory if evaluation runs during training.

Observed data confirms this:

- base model after training load: about `10.5 GB` by `nvidia-smi`;
- training peak: about `11.1 GB` by `nvidia-smi`;
- eval peak: about `6.65 GB` by `nvidia-smi`.

This explains why the earlier eval-inside-training attempt hit OOM even though the quantized model file itself is much smaller than 16GB.

## Changes

Added VRAM telemetry:

- `scripts/lora_memory.py`;
- training samples memory at start, after model load, after each training step, after train, and after save;
- evaluation samples memory at start, after model load, and after each example;
- summaries include PyTorch allocated/reserved/peak stats and `nvidia-smi` total process memory.

## Training Run

Command shape:

```bash
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
train_text_to_sql_lora.py \
  --model-name Qwen/Qwen2.5-Coder-7B-Instruct \
  --max-steps 100 \
  --max-length 768 \
  --lora-r 8 \
  --lora-alpha 16 \
  --no-eval
```

Training summary:

- train examples: `30`;
- validation examples loaded but not evaluated during training: `9`;
- steps: `100`;
- runtime: `228.8522s`;
- train samples/sec: `1.748`;
- train steps/sec: `0.437`;
- train loss: `0.1547`;
- epoch: `12.5333`;
- local adapter: `models/text_to_sql_lora/qwen2_5_coder_7b_v1_steps100`.

Training VRAM peak:

- PyTorch allocated: `7665 MB`;
- PyTorch reserved: `10174 MB`;
- PyTorch max allocated: `10052 MB`;
- PyTorch max reserved: `10174 MB`;
- `nvidia-smi` memory used: `11138 MB`.

## Evaluation

Dataset:

- `data/text_to_sql/v1/test.jsonl`;
- examples: `9`;
- max length: `768`;
- max new tokens: `256`.

Base model, same max length:

- valid SQL: `9/9`;
- required tables present: `9/9`;
- normalized exact match: `0/9`;
- average latency: `758ms`;
- eval VRAM peak by `nvidia-smi`: `6524 MB`.

100-step LoRA adapter:

- valid SQL: `9/9`;
- required tables present: `9/9`;
- normalized exact match: `9/9`;
- average latency: `896ms`;
- eval VRAM peak by `nvidia-smi`: `6650 MB`.

## Interpretation

The adapter learned the V1 test patterns very strongly:

- it outputs plain SQL without markdown;
- it uses the expected tables;
- it reproduces the expected SQL exactly on all V1 test examples.

Important caveat:

- V1 is small;
- train/validation/test examples are split by examples, not fully by unseen intent families;
- `100` steps means more than `12` epochs over only `30` train examples;
- the result proves the training pipeline and project-specific memorization/adaptation, not broad Text-to-SQL generalization.

## Decision

The corrected LoRA path is viable and now has memory accounting.

Next quality step:

- build dataset V2 with intent-level split;
- add more paraphrases and harder unseen questions;
- include semantic metrics beyond exact match;
- optionally execute SQL in read-only mode during evaluation;
- keep training eval separate from training to avoid avoidable VRAM spikes.
