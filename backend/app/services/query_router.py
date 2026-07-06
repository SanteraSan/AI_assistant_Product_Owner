from dataclasses import dataclass


@dataclass(frozen=True)
class QueryRoutingDecision:
    source_types: list[str]
    score_threshold: float | None
    hints: dict[str, object]


class QueryRouter:
    def __init__(self) -> None:
        self._metric_positive_markers = (
            "metric",
            "metrics",
            "метрик",
            "вырос",
            "выросл",
            "снизил",
            "снижен",
            "adoption",
            "tickets",
            "тикет",
            "delay",
            "задержк",
        )
        self._metric_negative_markers = (
            "без метрик",
            "без metrics",
            "не перечисляй метрик",
            "не перечисляя метрики",
            "не нужны метрики",
            "не надо метрик",
            "не используй метрики",
            "не показывай метрики",
        )
        self._metric_source_types = [
            "metric_row",
            "incident_note",
            "support_ticket",
            "release_note",
        ]
        self._support_feedback_markers = (
            "жалоб",
            "отзыв",
            "feedback",
            "клиенты сообщают",
            "клиент сообщает",
            "пользователи сообщают",
            "support",
            "тикет",
            "tickets",
        )
        self._support_feedback_source_types = [
            "support_ticket",
            "incident_note",
            "metric_row",
        ]
        self._technical_root_cause_markers = (
            "техническ",
            "причин",
            "root cause",
            "почему",
            "rate limit",
            "rate limits",
            "retry",
            "backoff",
            "worker",
            "очеред",
            "api",
        )
        self._strong_technical_root_cause_markers = (
            "root cause",
            "rate limit",
            "rate limits",
            "retry",
            "backoff",
            "worker",
        )
        self._technical_root_cause_source_types = [
            "markdown",
            "incident_note",
            "support_ticket",
        ]

    def route(
        self,
        *,
        message: str,
        source_types: list[str],
        score_threshold: float | None,
        user_provided_source_types: bool,
        user_provided_score_threshold: bool,
    ) -> QueryRoutingDecision:
        normalized = message.lower()
        has_metric_negative_marker = _contains_any(
            normalized,
            self._metric_negative_markers,
        )
        has_metric_positive_marker = _contains_any(
            normalized,
            self._metric_positive_markers,
        )
        has_strong_technical_marker = _contains_any(
            normalized,
            self._strong_technical_root_cause_markers,
        )
        metric_intent = (
            has_metric_positive_marker
            and not has_metric_negative_marker
            and not has_strong_technical_marker
        )
        support_feedback_intent = (
            _contains_any(normalized, self._support_feedback_markers)
            and not metric_intent
        )
        technical_root_cause_intent = (
            _contains_any(normalized, self._technical_root_cause_markers)
            and (has_strong_technical_marker or not metric_intent)
            and not support_feedback_intent
        )

        selected_source_types = source_types
        selected_score_threshold = score_threshold
        applied_hints: list[str] = []

        if metric_intent and not user_provided_source_types:
            selected_source_types = self._metric_source_types
            applied_hints.append("metric_source_types")

        if metric_intent and not user_provided_score_threshold:
            selected_score_threshold = _lower_threshold(score_threshold, 0.60)
            applied_hints.append("metric_score_threshold")

        if support_feedback_intent and not user_provided_source_types:
            selected_source_types = self._support_feedback_source_types
            applied_hints.append("support_feedback_source_types")

        if technical_root_cause_intent and not user_provided_source_types:
            selected_source_types = self._technical_root_cause_source_types
            applied_hints.append("technical_root_cause_source_types")

        if technical_root_cause_intent and not user_provided_score_threshold:
            selected_score_threshold = _lower_threshold(score_threshold, 0.60)
            applied_hints.append("technical_root_cause_score_threshold")

        return QueryRoutingDecision(
            source_types=selected_source_types,
            score_threshold=selected_score_threshold,
            hints={
                "metric_intent": metric_intent,
                "metric_negative_marker": has_metric_negative_marker,
                "support_feedback_intent": support_feedback_intent,
                "technical_root_cause_intent": technical_root_cause_intent,
                "applied_hints": applied_hints,
                "user_provided_source_types": user_provided_source_types,
                "user_provided_score_threshold": user_provided_score_threshold,
            },
        )


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _lower_threshold(current: float | None, target: float) -> float:
    if current is None:
        return target
    return min(current, target)
