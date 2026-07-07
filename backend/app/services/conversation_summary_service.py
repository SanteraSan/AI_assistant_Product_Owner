import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ChatMessage, ConversationSummary
from app.models.conversation_summary import LlmStructuredSummary
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient


@dataclass(frozen=True)
class ConversationSummaryContext:
    available: bool
    updated: bool
    summary: str | None
    features: list[str]
    message_count: int
    message_count_at_update: int
    stale_message_count: int
    token_estimate: int
    mode: str
    reason: str
    strategy: str
    summary_model: str | None
    structured_summary: dict[str, object]
    fallback_used: bool
    validation_error: str | None
    validation_warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "updated": self.updated,
            "summary": self.summary,
            "features": self.features,
            "message_count": self.message_count,
            "message_count_at_update": self.message_count_at_update,
            "stale_message_count": self.stale_message_count,
            "token_estimate": self.token_estimate,
            "mode": self.mode,
            "reason": self.reason,
            "strategy": self.strategy,
            "summary_model": self.summary_model,
            "structured_summary": self.structured_summary,
            "fallback_used": self.fallback_used,
            "validation_error": self.validation_error,
            "validation_warnings": self.validation_warnings,
        }


@dataclass(frozen=True)
class SummaryBuildResult:
    summary: str
    features: list[str]
    mode: str
    strategy: str
    summary_model: str | None
    structured_summary: dict[str, object]
    fallback_used: bool
    validation_error: str | None
    validation_warnings: list[str]


class ConversationSummaryService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        feature_extractor: FeatureExtractor,
        ollama_client: OllamaClient | None = None,
        summary_strategy: str = "hybrid",
        summary_model: str | None = None,
        summary_temperature: float = 0.0,
        token_threshold: int = 600,
        message_count_threshold: int = 8,
        stale_message_threshold: int = 4,
        idle_seconds_threshold: int = 3600,
    ) -> None:
        self._session_factory = session_factory
        self._feature_extractor = feature_extractor
        self._ollama_client = ollama_client
        self._summary_strategy = summary_strategy.strip().lower()
        self._summary_model = summary_model
        self._summary_temperature = summary_temperature
        self._token_threshold = token_threshold
        self._message_count_threshold = message_count_threshold
        self._stale_message_threshold = stale_message_threshold
        self._idle_seconds_threshold = idle_seconds_threshold

    async def prepare_summary(
        self,
        *,
        session_id: str | None,
    ) -> ConversationSummaryContext:
        if not session_id:
            return _empty_summary_context(reason="no_session")

        async with self._session_factory() as session:
            messages = await self._load_session_messages(
                session=session,
                session_id=session_id,
            )
            message_count = len(messages)
            token_estimate = _estimate_tokens(
                "\n".join(message.content for message in messages)
            )
            existing_summary = await session.scalar(
                select(ConversationSummary).where(
                    ConversationSummary.session_id == session_id
                )
            )
            should_update, reason = self._should_update_summary(
                existing_summary=existing_summary,
                message_count=message_count,
                token_estimate=token_estimate,
                latest_message=messages[-1] if messages else None,
            )

            if should_update:
                summary_result = await self._build_summary(messages)
                metadata = {
                    "trigger": reason,
                    "strategy": summary_result.strategy,
                    "summary_model": summary_result.summary_model,
                    "structured_summary": summary_result.structured_summary,
                    "fallback_used": summary_result.fallback_used,
                    "validation_error": summary_result.validation_error,
                    "validation_warnings": summary_result.validation_warnings,
                }
                if existing_summary is None:
                    existing_summary = ConversationSummary(
                        session_id=session_id,
                        summary=summary_result.summary,
                        message_count_at_update=message_count,
                        features=summary_result.features,
                        metadata_json=metadata,
                    )
                    session.add(existing_summary)
                else:
                    existing_summary.summary = summary_result.summary
                    existing_summary.message_count_at_update = message_count
                    existing_summary.features = summary_result.features
                    existing_summary.metadata_json = metadata
                await session.commit()
                return ConversationSummaryContext(
                    available=bool(summary_result.summary),
                    updated=True,
                    summary=summary_result.summary,
                    features=summary_result.features,
                    message_count=message_count,
                    message_count_at_update=message_count,
                    stale_message_count=0,
                    token_estimate=token_estimate,
                    mode=summary_result.mode,
                    reason=reason,
                    strategy=summary_result.strategy,
                    summary_model=summary_result.summary_model,
                    structured_summary=summary_result.structured_summary,
                    fallback_used=summary_result.fallback_used,
                    validation_error=summary_result.validation_error,
                    validation_warnings=summary_result.validation_warnings,
                )

            if existing_summary is None:
                return ConversationSummaryContext(
                    available=False,
                    updated=False,
                    summary=None,
                    features=[],
                    message_count=message_count,
                    message_count_at_update=0,
                    stale_message_count=message_count,
                    token_estimate=token_estimate,
                    mode="not_available",
                    reason=reason,
                    strategy=self._summary_strategy,
                    summary_model=self._summary_model,
                    structured_summary={},
                    fallback_used=False,
                    validation_error=None,
                    validation_warnings=[],
                )

            stale_message_count = message_count - existing_summary.message_count_at_update
            metadata = existing_summary.metadata_json or {}
            return ConversationSummaryContext(
                available=True,
                updated=False,
                summary=existing_summary.summary,
                features=existing_summary.features,
                message_count=message_count,
                message_count_at_update=existing_summary.message_count_at_update,
                stale_message_count=stale_message_count,
                token_estimate=token_estimate,
                mode="stored_summary",
                reason=reason,
                strategy=str(metadata.get("strategy") or self._summary_strategy),
                summary_model=_optional_str(metadata.get("summary_model")),
                structured_summary=_as_dict(metadata.get("structured_summary")),
                fallback_used=metadata.get("fallback_used") is True,
                validation_error=_optional_str(metadata.get("validation_error")),
                validation_warnings=_as_str_list(metadata.get("validation_warnings")),
            )

    async def _load_session_messages(
        self,
        *,
        session: AsyncSession,
        session_id: str,
    ) -> list[ChatMessage]:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        return list(result.scalars())

    def _should_update_summary(
        self,
        *,
        existing_summary: ConversationSummary | None,
        message_count: int,
        token_estimate: int,
        latest_message: ChatMessage | None,
    ) -> tuple[bool, str]:
        if message_count == 0:
            return False, "no_messages"

        if existing_summary is not None:
            stale_message_count = message_count - existing_summary.message_count_at_update
            if stale_message_count >= self._stale_message_threshold:
                return True, "stale_message_threshold"
            if _idle_seconds_since(latest_message) >= self._idle_seconds_threshold:
                return True, "session_idle_boundary"
            return False, "stored_summary_fresh"

        if token_estimate >= self._token_threshold:
            return True, "token_threshold"
        if message_count >= self._message_count_threshold:
            return True, "message_count_fallback"
        return False, "below_summary_threshold"

    async def _build_summary(self, messages: list[ChatMessage]) -> SummaryBuildResult:
        rule_based_summary = self._build_rule_based_summary(messages)
        if self._summary_strategy == "rule_based" or self._ollama_client is None:
            return rule_based_summary

        try:
            return await self._build_llm_summary(messages=messages)
        except Exception as exc:
            return SummaryBuildResult(
                summary=rule_based_summary.summary,
                features=rule_based_summary.features,
                mode="llm_fallback_rule_based",
                strategy=self._summary_strategy,
                summary_model=self._summary_model,
                structured_summary=rule_based_summary.structured_summary,
                fallback_used=True,
                validation_error=str(exc),
                validation_warnings=rule_based_summary.validation_warnings,
            )

    def _build_rule_based_summary(self, messages: list[ChatMessage]) -> SummaryBuildResult:
        user_messages = [
            message.content.strip()
            for message in messages
            if message.role == "user" and message.content.strip()
        ]
        user_text = "\n".join(user_messages)
        features = self._feature_extractor.extract(user_text)
        recent_user_intents = user_messages[-4:]
        topic = ", ".join(features) if features else "unknown"
        summary = (
            f"Основные темы диалога: {topic}. "
            f"Последние запросы пользователя: {' | '.join(recent_user_intents)}"
        ).strip()
        structured_summary: dict[str, object] = {
            "main_topics": features,
            "user_goals": recent_user_intents[-2:],
            "decisions": [],
            "open_questions": recent_user_intents[-1:] if recent_user_intents else [],
            "constraints": [],
            "summary": summary,
        }
        return SummaryBuildResult(
            summary=summary,
            features=features,
            mode="rule_based_extractive",
            strategy="rule_based",
            summary_model=None,
            structured_summary=structured_summary,
            fallback_used=False,
            validation_error=None,
            validation_warnings=[],
        )

    async def _build_llm_summary(
        self,
        *,
        messages: list[ChatMessage],
    ) -> SummaryBuildResult:
        if self._ollama_client is None or not self._summary_model:
            raise ValueError("LLM summary requested without Ollama client or summary model.")

        user_text = "\n".join(
            message.content.strip()
            for message in messages
            if message.role == "user" and message.content.strip()
        )
        features = self._feature_extractor.extract(user_text)
        prompt = _build_llm_summary_prompt(
            messages=messages,
            allowed_features=features,
        )
        result = await self._ollama_client.generate(
            model=self._summary_model,
            prompt=prompt,
            keep_alive="10m",
            options={
                "temperature": self._summary_temperature,
                "top_p": 0.9,
            },
            think=False,
        )
        response_text = str(result.get("response") or "")
        structured_summary, validation_warnings = _parse_structured_summary(
            response_text=response_text,
            allowed_features=features,
        )
        summary = str(structured_summary["summary"])
        return SummaryBuildResult(
            summary=summary,
            features=features,
            mode="llm_structured",
            strategy=self._summary_strategy,
            summary_model=self._summary_model,
            structured_summary=structured_summary,
            fallback_used=False,
            validation_error=None,
            validation_warnings=validation_warnings,
        )


def _empty_summary_context(reason: str) -> ConversationSummaryContext:
    return ConversationSummaryContext(
        available=False,
        updated=False,
        summary=None,
        features=[],
        message_count=0,
        message_count_at_update=0,
        stale_message_count=0,
        token_estimate=0,
        mode="not_available",
        reason=reason,
        strategy="rule_based",
        summary_model=None,
        structured_summary={},
        fallback_used=False,
        validation_error=None,
        validation_warnings=[],
    )


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _idle_seconds_since(latest_message: ChatMessage | None) -> int:
    if latest_message is None or latest_message.created_at is None:
        return 0
    created_at = latest_message.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return int((datetime.now(UTC) - created_at).total_seconds())


def _build_llm_summary_prompt(
    *,
    messages: list[ChatMessage],
    allowed_features: list[str],
) -> str:
    transcript = _format_transcript(messages[-20:])
    allowed_features_text = ", ".join(allowed_features) if allowed_features else "нет"
    return f"""Ты сжимаешь историю диалога для backend memory layer AI-ассистента Product Owner.

Нужно вернуть только валидный JSON без markdown и пояснений.

Важные правила:
- Summary описывает только диалог: цели пользователя, решения, ограничения и открытые вопросы.
- Не добавляй факты о продукте, которых нет в диалоге.
- Не используй summary как доказательную базу: продуктовые факты будут взяты из RAG sources отдельно.
- Product features в `main_topics` можно использовать только из списка allowed_features.
- Если в ответах ассистента упоминались другие product features для сравнения, не добавляй их в `main_topics`.
- `decisions` включает только явные договоренности или конкретные рекомендованные действия, которые были центральны для диалога. Если это рекомендация ассистента, формулируй как "рекомендовано ...".
- Если решений, ограничений или открытых вопросов нет, верни пустой массив.
- Пиши кратко на русском языке.

allowed_features: {allowed_features_text}

JSON schema:
{{
  "main_topics": ["короткие темы или allowed product features"],
  "user_goals": ["что пользователь пытается понять или сделать"],
  "decisions": ["явные договоренности или центральные рекомендованные действия"],
  "open_questions": ["что осталось выяснить"],
  "constraints": ["явные ограничения пользователя"],
  "summary": "2-4 предложения компактного summary диалога"
}}

Диалог:
{transcript}
"""


def _format_transcript(messages: list[ChatMessage]) -> str:
    lines = []
    for message in messages:
        content = " ".join(message.content.split())
        lines.append(f"{message.role}: {content}")
    return "\n".join(lines)


def _parse_structured_summary(
    *,
    response_text: str,
    allowed_features: list[str],
) -> tuple[dict[str, object], list[str]]:
    raw_json = _extract_json_object(response_text)
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM summary returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM summary JSON must be an object.")

    try:
        summary_model = LlmStructuredSummary(**parsed)
    except ValueError as exc:
        raise ValueError(f"LLM summary JSON failed schema validation: {exc}") from exc
    compact_summary = summary_model.to_compact_dict()
    if not compact_summary["summary"]:
        raise ValueError("LLM summary JSON must include a non-empty summary string.")

    main_topics, discarded_topics = _filter_allowed_main_topics(
        main_topics=_as_str_list(compact_summary.get("main_topics")),
        allowed_features=allowed_features,
    )
    structured_summary: dict[str, object] = {
        "main_topics": main_topics,
        "user_goals": _as_str_list(compact_summary.get("user_goals")),
        "decisions": _as_str_list(compact_summary.get("decisions")),
        "open_questions": _as_str_list(compact_summary.get("open_questions")),
        "constraints": _as_str_list(compact_summary.get("constraints")),
        "summary": compact_summary["summary"],
    }
    validation_warnings = [
        f"discarded_main_topics_not_in_allowed_features: {', '.join(discarded_topics)}"
    ] if discarded_topics else []
    return structured_summary, validation_warnings


def _filter_allowed_main_topics(
    *,
    main_topics: list[str],
    allowed_features: list[str],
) -> tuple[list[str], list[str]]:
    allowed_by_normalized = {
        _normalize_feature_topic(feature): feature
        for feature in allowed_features
    }
    filtered: list[str] = []
    discarded: list[str] = []
    for topic in main_topics:
        normalized_topic = _normalize_feature_topic(topic)
        allowed_topic = allowed_by_normalized.get(normalized_topic)
        if allowed_topic is None:
            discarded.append(topic)
            continue
        if allowed_topic not in filtered:
            filtered.append(allowed_topic)
    return filtered, discarded


def _normalize_feature_topic(value: str) -> str:
    return value.strip().strip("`").lower()


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM summary response did not contain a JSON object.")
    return stripped[start : end + 1]


def _as_str_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if not isinstance(item, str):
            continue
        compact = " ".join(item.split())
        if not compact or compact in normalized:
            continue
        normalized.append(compact[:240])
        if len(normalized) >= limit:
            break
    return normalized


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
