from app.services.query_router import QueryRouter


def test_metric_intent_selects_metric_sources_and_lowers_threshold() -> None:
    decision = QueryRouter().route(
        message="Какие метрики по notifications изменились у enterprise-клиентов?",
        source_types=[],
        score_threshold=0.68,
        user_provided_source_types=False,
        user_provided_score_threshold=False,
    )

    assert decision.hints["metric_intent"] is True
    assert "metric_row" in decision.source_types
    assert decision.score_threshold == 0.60
    assert "metric_row" in decision.hints["required_source_types"]


def test_negative_metric_marker_prevents_metric_intent() -> None:
    decision = QueryRouter().route(
        message="Какие проблемы важны для enterprise-клиентов, без метрик?",
        source_types=[],
        score_threshold=0.68,
        user_provided_source_types=False,
        user_provided_score_threshold=False,
    )

    assert decision.hints["metric_negative_marker"] is True
    assert decision.hints["metric_intent"] is False
    assert decision.source_types == []
    assert decision.score_threshold == 0.68


def test_user_provided_source_types_are_not_overridden() -> None:
    decision = QueryRouter().route(
        message="Какие метрики по notifications изменились?",
        source_types=["pdf"],
        score_threshold=0.68,
        user_provided_source_types=True,
        user_provided_score_threshold=False,
    )

    assert decision.hints["metric_intent"] is True
    assert decision.source_types == ["pdf"]
