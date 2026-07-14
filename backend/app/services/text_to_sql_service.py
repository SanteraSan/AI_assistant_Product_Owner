from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.services.ollama_client import OllamaClient
from app.services.sql_execution_service import SqlExecutionService
from app.services.sql_schema_card import build_schema_card
from app.services.sql_validator import extract_sql_from_response


@dataclass(frozen=True)
class TextToSqlGeneration:
    question: str
    sql: str | None
    model_used: str
    fallback_used: bool
    validation_valid: bool
    validation_error: str | None
    tables: list[str]
    raw_response: str
    warning: str | None = None


class TextToSqlService:
    def __init__(
        self,
        *,
        ollama_client: OllamaClient,
        sql_execution_service: SqlExecutionService,
        preferred_model: str,
        fallback_model: str,
        allowed_tables: frozenset[str],
    ) -> None:
        self._ollama_client = ollama_client
        self._sql_execution_service = sql_execution_service
        self._preferred_model = preferred_model.strip()
        self._fallback_model = fallback_model.strip()
        self._allowed_tables = allowed_tables
        self._schema_card = build_schema_card(allowed_tables=allowed_tables)

    @property
    def schema_card(self) -> str:
        return self._schema_card

    async def generate(self, *, question: str) -> TextToSqlGeneration:
        prompt = _build_prompt(schema_card=self._schema_card, question=question)
        model_used = self._preferred_model
        fallback_used = False
        warning: str | None = None
        try:
            raw = await self._ollama_client.generate(
                model=model_used,
                prompt=prompt,
                think=False,
                options={"temperature": 0.0},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 400} or model_used == self._fallback_model:
                raise
            model_used = self._fallback_model
            fallback_used = True
            warning = (
                f"Preferred text-to-SQL model '{self._preferred_model}' unavailable; "
                f"fell back to '{self._fallback_model}'."
            )
            raw = await self._ollama_client.generate(
                model=model_used,
                prompt=prompt,
                think=False,
                options={"temperature": 0.0},
            )

        response_text = str(raw.get("response") or "")
        extracted = extract_sql_from_response(response_text)
        validation = self._sql_execution_service.validate(extracted)
        return TextToSqlGeneration(
            question=question,
            sql=validation.normalized_sql if validation.valid else extracted or None,
            model_used=model_used,
            fallback_used=fallback_used,
            validation_valid=validation.valid,
            validation_error=validation.error,
            tables=validation.tables,
            raw_response=response_text,
            warning=warning,
        )


def _build_prompt(*, schema_card: str, question: str) -> str:
    return f"""Ты генерируешь безопасный PostgreSQL SQL для аналитики.

Правила:
- Верни только один SQL statement.
- Разрешены только SELECT или WITH ... SELECT.
- Нельзя INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE.
- Используй только таблицы из схемы ниже.
- Не добавляй markdown, комментарии или объяснения.

{schema_card}

Вопрос:
{question}

SQL:"""
