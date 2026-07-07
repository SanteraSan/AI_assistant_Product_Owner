from dataclasses import dataclass

from app.services.chat_history_service import ChatHistoryMessage
from app.services.conversation_summary_service import ConversationSummaryContext
from app.services.feature_extractor import FeatureExtractor


@dataclass(frozen=True)
class ConversationContextDecision:
    used: bool
    mode: str
    follow_up_detected: bool
    topic_switch_detected: bool
    history_messages_used: int
    retrieval_query: str
    carried_features: list[str]
    current_features: list[str]
    decision_reason: str
    summary_available: bool
    summary_used: bool
    summary_updated: bool
    summary_message_count: int
    summary_features: list[str]
    summary_mode: str
    summary_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "used": self.used,
            "mode": self.mode,
            "follow_up_detected": self.follow_up_detected,
            "topic_switch_detected": self.topic_switch_detected,
            "history_messages_used": self.history_messages_used,
            "retrieval_query": self.retrieval_query,
            "carried_features": self.carried_features,
            "current_features": self.current_features,
            "decision_reason": self.decision_reason,
            "summary_available": self.summary_available,
            "summary_used": self.summary_used,
            "summary_updated": self.summary_updated,
            "summary_message_count": self.summary_message_count,
            "summary_features": self.summary_features,
            "summary_mode": self.summary_mode,
            "summary_reason": self.summary_reason,
        }


class ConversationContextService:
    def __init__(
        self,
        *,
        feature_extractor: FeatureExtractor,
    ) -> None:
        self._feature_extractor = feature_extractor
        self._follow_up_markers = (
            "а какие",
            "а какой",
            "а какая",
            "а что",
            "а почему",
            "а как",
            "из этих",
            "из них",
            "этих проблем",
            "эти проблемы",
            "самые критичные",
            "самое критичное",
            "что из этого",
            "что с этим делать",
            "что делать",
            "какой action plan",
            "action plan",
            "план действий",
            "какие действия",
            "что показать",
            "что показать po",
            "какие рекомендации",
            "рекомендации",
            "какие метрики",
            "какие показатели",
            "можешь без метрик",
            "без метрик",
            "без цифр",
            "по ним",
            "по нему",
            "по ней",
            "расскажи подробнее",
            "подробнее",
            "по ним",
            "по этой теме",
            "это",
        )
        self._topic_switch_markers = (
            "а теперь про",
            "теперь про",
            "перейдем к",
            "перейдём к",
            "забудь",
            "другая тема",
            "а что с",
            "что с",
            "сравни это с",
            "сравни с",
        )
        self._soft_follow_up_features = {"reports"}

    def build_context(
        self,
        *,
        message: str,
        recent_messages: list[ChatHistoryMessage],
        summary_context: ConversationSummaryContext | None = None,
    ) -> ConversationContextDecision:
        normalized_message = message.lower()
        current_features = self._feature_extractor.extract(message)
        summary_context = summary_context or _empty_summary_context()
        if not recent_messages:
            return self._empty_decision(
                message=message,
                mode="no_history",
                current_features=current_features,
                summary_context=summary_context,
            )

        follow_up_detected = self._is_follow_up(normalized_message)
        topic_switch_detected = self._is_topic_switch(
            normalized_message=normalized_message,
            current_features=current_features,
            follow_up_detected=follow_up_detected,
        )
        if topic_switch_detected:
            topic_switch_query = self._build_topic_switch_query(message)
            topic_switch_features = self._feature_extractor.extract(topic_switch_query)
            return ConversationContextDecision(
                used=False,
                mode="topic_switch_or_standalone",
                follow_up_detected=follow_up_detected,
                topic_switch_detected=True,
                history_messages_used=0,
                retrieval_query=topic_switch_query,
                carried_features=[],
                current_features=topic_switch_features or current_features,
                decision_reason="current_message_has_explicit_topic_feature",
                summary_available=summary_context.available,
                summary_used=False,
                summary_updated=summary_context.updated,
                summary_message_count=summary_context.message_count,
                summary_features=summary_context.features,
                summary_mode=summary_context.mode,
                summary_reason=summary_context.reason,
            )
        if not follow_up_detected:
            return self._empty_decision(
                message=message,
                mode="standalone_question",
                current_features=current_features,
                summary_context=summary_context,
            )

        user_history = [
            history_message.content
            for history_message in recent_messages
            if history_message.role == "user"
        ]
        user_history_text = "\n".join(user_history)
        carried_features = self._feature_extractor.extract(user_history_text)
        if not carried_features and not user_history:
            return self._empty_decision(
                message=message,
                mode="no_reusable_history",
                current_features=current_features,
                follow_up_detected=follow_up_detected,
                summary_context=summary_context,
            )

        recent_user_context = " ".join(user_history[-2:])
        summary_used = summary_context.available and not carried_features
        effective_features = _merge_unique(
            carried_features,
            summary_context.features if summary_used else [],
        )
        retrieval_query_parts = [
            message,
            f"Предыдущая тема: {recent_user_context}".strip(),
        ]
        if summary_used and summary_context.summary:
            retrieval_query_parts.append(
                f"Summary предыдущего диалога: {summary_context.summary}"
            )
        if effective_features:
            retrieval_query_parts.append(
                f"Ключевые features из предыдущего контекста: {', '.join(effective_features)}."
            )
        retrieval_query = " ".join(part for part in retrieval_query_parts if part)

        return ConversationContextDecision(
            used=True,
            mode="follow_up_rewrite",
            follow_up_detected=True,
            topic_switch_detected=False,
            history_messages_used=len(recent_messages),
            retrieval_query=retrieval_query,
            carried_features=effective_features,
            current_features=current_features,
            decision_reason=(
                "follow_up_with_summary"
                if summary_used
                else "follow_up_without_explicit_topic_switch"
            ),
            summary_available=summary_context.available,
            summary_used=summary_used,
            summary_updated=summary_context.updated,
            summary_message_count=summary_context.message_count,
            summary_features=summary_context.features,
            summary_mode=summary_context.mode,
            summary_reason=summary_context.reason,
        )

    def _is_follow_up(self, normalized_message: str) -> bool:
        if any(marker in normalized_message for marker in self._follow_up_markers):
            return True
        return len(normalized_message.split()) <= 6 and "?" in normalized_message

    def _is_topic_switch(
        self,
        *,
        normalized_message: str,
        current_features: list[str],
        follow_up_detected: bool,
    ) -> bool:
        if not current_features:
            return False
        hard_features = [
            feature
            for feature in current_features
            if feature not in self._soft_follow_up_features
        ]
        if hard_features:
            return True
        if not follow_up_detected:
            return True
        return any(marker in normalized_message for marker in self._topic_switch_markers)

    def _build_topic_switch_query(self, message: str) -> str:
        normalized_message = message.lower()
        for marker in ("а теперь про", "теперь про", "перейдем к", "перейдём к"):
            marker_index = normalized_message.find(marker)
            if marker_index >= 0:
                return message[marker_index:].strip(" ,.")
        return message

    def _empty_decision(
        self,
        *,
        message: str,
        mode: str,
        current_features: list[str],
        follow_up_detected: bool = False,
        summary_context: ConversationSummaryContext | None = None,
    ) -> ConversationContextDecision:
        summary_context = summary_context or _empty_summary_context()
        return ConversationContextDecision(
            used=False,
            mode=mode,
            follow_up_detected=follow_up_detected,
            topic_switch_detected=False,
            history_messages_used=0,
            retrieval_query=message,
            carried_features=[],
            current_features=current_features,
            decision_reason=mode,
            summary_available=summary_context.available,
            summary_used=False,
            summary_updated=summary_context.updated,
            summary_message_count=summary_context.message_count,
            summary_features=summary_context.features,
            summary_mode=summary_context.mode,
            summary_reason=summary_context.reason,
        )


def _empty_summary_context() -> ConversationSummaryContext:
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
        reason="not_provided",
    )


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*first, *second]:
        if item in merged:
            continue
        merged.append(item)
    return merged
