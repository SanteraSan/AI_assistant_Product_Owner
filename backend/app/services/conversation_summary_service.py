from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ChatMessage, ConversationSummary
from app.services.feature_extractor import FeatureExtractor


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
        }


class ConversationSummaryService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        feature_extractor: FeatureExtractor,
        token_threshold: int = 600,
        message_count_threshold: int = 8,
        stale_message_threshold: int = 4,
        idle_seconds_threshold: int = 3600,
    ) -> None:
        self._session_factory = session_factory
        self._feature_extractor = feature_extractor
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
                summary_text, features = self._build_summary(messages)
                if existing_summary is None:
                    existing_summary = ConversationSummary(
                        session_id=session_id,
                        summary=summary_text,
                        message_count_at_update=message_count,
                        features=features,
                        metadata_json={"trigger": reason},
                    )
                    session.add(existing_summary)
                else:
                    existing_summary.summary = summary_text
                    existing_summary.message_count_at_update = message_count
                    existing_summary.features = features
                    existing_summary.metadata_json = {"trigger": reason}
                await session.commit()
                return ConversationSummaryContext(
                    available=bool(summary_text),
                    updated=True,
                    summary=summary_text,
                    features=features,
                    message_count=message_count,
                    message_count_at_update=message_count,
                    stale_message_count=0,
                    token_estimate=token_estimate,
                    mode="rule_based_extractive",
                    reason=reason,
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
                )

            stale_message_count = message_count - existing_summary.message_count_at_update
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

    def _build_summary(self, messages: list[ChatMessage]) -> tuple[str, list[str]]:
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
        return summary, features


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
