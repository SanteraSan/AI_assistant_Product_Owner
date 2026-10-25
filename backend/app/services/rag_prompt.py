from __future__ import annotations

import re

from app.models.chat import SourceChunk


def build_rag_prompt(
    question: str,
    sources: list[SourceChunk],
    extra_rules: list[str] | None = None,
    memory_context: dict[str, object] | None = None,
    closing_instructions: str | None = None,
) -> str:
    context_blocks = []
    for index, source in enumerate(sources, start=1):
        title = source.title or "Untitled source"
        source_type = source.source_type or "unknown"
        features = ", ".join(source.feature) if source.feature else "unknown"
        file_name = _source_file_name(source)
        context_blocks.append(
            "\n".join(
                [
                    (
                        f"[Источник {index}: {source_type} | title={title} | "
                        f"file={file_name} | feature={features}]"
                    ),
                    source.content.strip(),
                ]
            )
        )

    context = "\n\n".join(context_blocks) if context_blocks else "Контекст не найден."
    memory_text = _build_memory_prompt_text(memory_context)
    memory_rules = [
        (
            "Память диалога помогает учитывать предыдущие цели и формулировки "
            "пользователя, но не является источником фактов и не отменяет "
            "актуальный блок Контекст."
        ),
        (
            "Факты из пользовательских документов, метрики, причины инцидентов "
            "и рекомендации бери только из блока Контекст."
        ),
    ] if memory_text else []
    dynamic_rules = "\n".join(
        f"- {rule}"
        for rule in [*memory_rules, *(extra_rules or [])]
    )
    rules = "\n".join(
        [
            "- Отвечай на русском языке.",
            "- Пиши кратко и по делу: обычно 3–6 предложений или короткий список.",
            "- Не пиши длинные эссе, вступления и повторения.",
            "- Не выдумывай факты, которых нет в контексте.",
            (
                "- Если вопрос про стек или технологии конкретного работодателя, "
                "бери их только из фрагмента, где названа эта организация. "
                "Блоки «Навыки», «Обо мне» и другие места работы не подмешивай."
            ),
            (
                "- Если в контексте есть релевантный фрагмент, ответь по нему, "
                "даже если документ не относится к продукту TaskFlow AI."
            ),
            (
                "- Если header источника содержит `file=<имя файла>`, считай этот фрагмент "
                "частью указанного файла. Не говори, что файл отсутствует, если "
                "в Контексте есть фрагмент с таким `file`."
            ),
            (
                "- Если пользователь спрашивает про конкретный файл по имени, а в Контексте "
                "нет источника с таким же `file=...`, ответь только что этого файла нет "
                "в доступном контексте. На этом остановись: не описывай, не сравнивай и "
                "не упоминай другие файлы, изображения или документы из Контекста."
            ),
            (
                "- Если источник выглядит как шутка, заметка или черновик, "
                "можно указать это как оговорку, но не отказывайся отвечать "
                "только из-за типа источника."
            ),
            "- Если в контексте нет ответа, скажи, каких данных не хватает.",
            "- Сначала факты, потом короткая интерпретация только если она нужна.",
            "- Если используешь числа, бери их только из контекста.",
            (
                "- Не перечисляй источники, файлы, CHUNK, номера фрагментов, UUID "
                "и служебные metadata в ответе. Пиши только содержание ответа."
            ),
            dynamic_rules,
        ]
    ).strip()

    closing = ""
    if closing_instructions and closing_instructions.strip():
        closing = (
            "\nНапоминание перед ответом:\n"
            f"{closing_instructions.strip()}\n"
        )

    return f"""Ты — AI-ассистент для Product Owner, который отвечает по пользовательским документам.

Твоя задача: дать короткий grounded-ответ на вопрос пользователя строго на основе предоставленного контекста.

Правила:
{rules}

Контекст:

{context}

Память диалога:

{memory_text or "Память диалога не используется."}
{closing}
Вопрос пользователя:
{question}
"""


def _build_memory_prompt_text(memory_context: dict[str, object] | None) -> str:
    if not memory_context or memory_context.get("used") is not True:
        return ""
    content = str(memory_context.get("content") or "").strip()
    return content


def _source_file_name(source: SourceChunk) -> str:
    document_metadata = source.metadata.get("document_metadata") or {}
    if isinstance(document_metadata, dict):
        for key in ("document_file_name", "file_name"):
            value = document_metadata.get(key)
            if value:
                return str(value)
    if source.source_path:
        return _display_file_name(source.source_path.rsplit("/", maxsplit=1)[-1])
    return "unknown"


def _display_file_name(file_name: str) -> str:
    # Storage paths look like `<uuid>_<original_name>`; prefer the original name in prompts.
    if len(file_name) > 37 and file_name[36] == "_":
        prefix = file_name[:36]
        if all(char in "0123456789abcdefABCDEF-" for char in prefix):
            return file_name[37:] or file_name
    return file_name


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _build_context_policy(query_hints: dict[str, object]) -> dict[str, object]:
    return {
        "numeric_line_sanitization": query_hints.get("metric_negative_marker") is True,
    }


def _apply_context_policy(
    sources: list[SourceChunk],
    *,
    context_policy: dict[str, object],
) -> list[SourceChunk]:
    if context_policy.get("numeric_line_sanitization") is not True:
        return sources

    return [
        source.model_copy(
            update={
                "title": _sanitize_metric_title(source.title),
                "content": _remove_numeric_metric_lines(source.content),
            }
        )
        for source in sources
    ]


def _build_extra_prompt_rules(query_hints: dict[str, object]) -> list[str]:
    if query_hints.get("metric_negative_marker") is True:
        return [
            (
                "Пользователь попросил не использовать метрики. "
                "Не упоминай числовые KPI, проценты, счетчики тикетов, adoption, "
                "latency/delay metrics и не давай рекомендации про метрики. "
                "Отвечай качественно, без числовых метрик."
            )
        ]
    return []


def _remove_numeric_metric_lines(text: str) -> str:
    kept_lines = [
        line
        for line in text.splitlines()
        if not _looks_like_numeric_metric_line(line)
    ]
    sanitized = "\n".join(kept_lines).strip()
    return sanitized or "Контент источника скрыт из-за ограничения пользователя не использовать метрики."


def _sanitize_metric_title(title: str | None) -> str | None:
    if title is None:
        return None
    if _looks_like_numeric_metric_line(title):
        # TODO: hide sanitized titles from prompt metadata instead of replacing them.
        return "Источник без числовых метрик"
    return title


def _looks_like_numeric_metric_line(line: str) -> bool:
    normalized = line.strip().lower()
    if not normalized:
        return False

    if "%" in normalized:
        return True

    numeric_metric_markers = (
        "metric",
        "метрик",
        "kpi",
        "adoption",
        "tickets",
        "тикет",
        "support tickets",
        "latency",
        "delay",
        "задержк",
        "минут",
        "ms",
        "мс",
    )
    has_number = re.search(r"\d", normalized) is not None
    has_metric_marker = any(marker in normalized for marker in numeric_metric_markers)
    return has_number and has_metric_marker

