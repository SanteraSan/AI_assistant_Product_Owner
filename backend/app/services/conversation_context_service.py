from dataclasses import dataclass

from app.services.chat_history_service import ChatHistoryMessage
from app.services.feature_extractor import FeatureExtractor


@dataclass(frozen=True)
class ConversationContextDecision:
    used: bool
    mode: str
    follow_up_detected: bool
    history_messages_used: int
    retrieval_query: str
    carried_features: list[str]
    current_features: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "used": self.used,
            "mode": self.mode,
            "follow_up_detected": self.follow_up_detected,
            "history_messages_used": self.history_messages_used,
            "retrieval_query": self.retrieval_query,
            "carried_features": self.carried_features,
            "current_features": self.current_features,
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
            "расскажи подробнее",
            "подробнее",
            "по ним",
            "по этой теме",
            "это",
        )

    def build_context(
        self,
        *,
        message: str,
        recent_messages: list[ChatHistoryMessage],
    ) -> ConversationContextDecision:
        normalized_message = message.lower()
        current_features = self._feature_extractor.extract(message)
        if not recent_messages:
            return self._empty_decision(
                message=message,
                mode="no_history",
                current_features=current_features,
            )

        follow_up_detected = self._is_follow_up(normalized_message)
        if current_features:
            return ConversationContextDecision(
                used=False,
                mode="topic_switch_or_standalone",
                follow_up_detected=follow_up_detected,
                history_messages_used=0,
                retrieval_query=message,
                carried_features=[],
                current_features=current_features,
            )
        if not follow_up_detected:
            return self._empty_decision(
                message=message,
                mode="standalone_question",
                current_features=current_features,
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
            )

        recent_user_context = " ".join(user_history[-2:])
        retrieval_query_parts = [
            message,
            f"Предыдущая тема: {recent_user_context}".strip(),
        ]
        if carried_features:
            retrieval_query_parts.append(
                f"Ключевые features из предыдущего контекста: {', '.join(carried_features)}."
            )
        retrieval_query = " ".join(part for part in retrieval_query_parts if part)

        return ConversationContextDecision(
            used=True,
            mode="follow_up_rewrite",
            follow_up_detected=True,
            history_messages_used=len(recent_messages),
            retrieval_query=retrieval_query,
            carried_features=carried_features,
            current_features=current_features,
        )

    def _is_follow_up(self, normalized_message: str) -> bool:
        if any(marker in normalized_message for marker in self._follow_up_markers):
            return True
        return len(normalized_message.split()) <= 6 and "?" in normalized_message

    def _empty_decision(
        self,
        *,
        message: str,
        mode: str,
        current_features: list[str],
        follow_up_detected: bool = False,
    ) -> ConversationContextDecision:
        return ConversationContextDecision(
            used=False,
            mode=mode,
            follow_up_detected=follow_up_detected,
            history_messages_used=0,
            retrieval_query=message,
            carried_features=[],
            current_features=current_features,
        )
