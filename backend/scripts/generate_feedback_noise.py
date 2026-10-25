#!/usr/bin/env python3
"""Шум и короткие сигналы для корпуса фидбека. LLM не вызывается."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

SEED = 20261023
NOISE_COUNT = 350
CHURN_COUNT = 75

NOISE = (
    "Класс!",
    "ок",
    "Ок.",
    "ааа",
    "норм",
    "супер",
    "угу",
    "спасибо",
    "ясно",
    "понятно",
    "круто",
    "ладно",
    "збс",
    "огонь",
    "++",
    "хз",
    "КЛАСС",
    "ОКЕЙ",
    "Супер!!!",
    "ааааа",
    "ок ок",
    "класс класс",
    "👍",
    "...",
    " ",
    "",
)

CHURN = (
    "Удаляю",
    "УДАЛЯЮ",
    "Ниче не работает",
    "Ничего не работает",
    "ниче не работает",
    "всё сломалось, удаляю",
    "опять не работает",
    "хватит, удаляю",
    "не работает и всё",
    "сношу",
    "удаляю приложение",
    "ниче не работает, сношу",
    "бесполезно, удаляю",
    "опять ничего",
    "не работает. удаляю",
)


def build_rows(
    count: int,
    label: str,
    phrases: tuple[str, ...],
    rng: random.Random,
) -> list[dict[str, str | None]]:
    return [
        {
            "generator_class": label,
            "scenario_id": None,
            "text": rng.choice(phrases),
        }
        for _ in range(count)
    ]


def write_jsonl(path: Path, rows: list[dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/home/santera/ML|LLM|RAG/sintetic_data"),
    )
    args = parser.parse_args()
    rng = random.Random(SEED)
    write_jsonl(args.out_dir / "noise.jsonl", build_rows(NOISE_COUNT, "noise", NOISE, rng))
    write_jsonl(
        args.out_dir / "churn.jsonl",
        build_rows(CHURN_COUNT, "churn_signal", CHURN, rng),
    )


if __name__ == "__main__":
    main()
