# Text-to-SQL LoRA Training Spike 2026-07-10

## Goal

Verify that local QLoRA training works for `M7: LoRA Text-to-SQL Fine-Tuning` on the current machine and dataset.

This was a training spike, not the final fine-tuned model.

## Environment

- GPU: NVIDIA GeForce RTX 5070 Ti, 16GB VRAM
- Python env: `.venv-lora`, Python 3.11
- PyTorch: `2.12.0.dev20260408+cu128`
- CUDA visible to PyTorch: `true`
- CUDA op check: `cuda_op_ok [2.0]`
- Base model: `Qwen/Qwen2.5-Coder-7B-Instruct`
- Dataset: `data/text_to_sql/v1`

## Compatibility Finding

Initial PyTorch `2.5.1+cu121` was not compatible with RTX 5070 Ti compute capability `sm_120`.

Resolution:

- remove old `torch`, `torchvision`, `torchaudio`;
- install nightly `torch` with CUDA 12.8;
- do not install `torchvision`/`torchaudio` for this LoRA task;
- install `kernels>=0.11.1` for bitsandbytes support.

## First Attempt

Command shape:

```bash
train_text_to_sql_lora.py \
  --model-name Qwen/Qwen2.5-Coder-7B-Instruct \
  --max-steps 5 \
  --max-length 768
```

Result:

- model loaded in 4-bit;
- LoRA adapter was created;
- trainable params: `40,370,176`;
- first 2 training steps completed;
- failed during evaluation with CUDA OOM.

Root cause:

- evaluation step required additional memory on top of the loaded 7B 4-bit model and LoRA adapter;
- GPU had only about `206 MB` free at failure time.

## Successful Smoke

Command shape:

```bash
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
train_text_to_sql_lora.py \
  --model-name Qwen/Qwen2.5-Coder-7B-Instruct \
  --max-steps 5 \
  --max-length 512 \
  --lora-r 8 \
  --lora-alpha 16 \
  --no-eval
```

Result:

- exit code: `0`;
- trainable params: `20,185,088`;
- all params: `7,635,801,600`;
- trainable ratio: `0.2643%`;
- steps: `5`;
- train runtime: `11.0894s`;
- train samples/sec: `1.804`;
- train steps/sec: `0.451`;
- train loss: `1.5536`;
- observed loss values: `1.735`, `1.657`, `1.547`, `1.447`, `1.382`;
- local adapter artifact saved to `models/text_to_sql_lora/qwen2_5_coder_7b_v1_smoke`.

## Git Policy

The adapter directory is local-only and is not committed:

- size: about `320 MB`;
- includes checkpoint optimizer state;
- `models/` is ignored in `.gitignore`.

Committed artifacts should be:

- training script;
- dataset;
- report;
- compact training summary if needed.

## Decision

QLoRA training is viable on the local GPU.

For the next evaluation stage:

- keep `max_length=512` or use a larger value only after memory checks;
- keep evaluation separate from training for the first 7B runs;
- use saved LoRA adapter for generation/evaluation against the Text-to-SQL test split;
- only then decide whether to expand dataset V2 or tune hyperparameters.
