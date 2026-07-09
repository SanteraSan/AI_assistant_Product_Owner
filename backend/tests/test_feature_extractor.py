from app.services.feature_extractor import FeatureExtractor


def test_extracts_multiple_features_from_mixed_language_text() -> None:
    extractor = FeatureExtractor()

    features = extractor.extract(
        "Slack notifications задерживаются, а admin роли ломают доступ."
    )

    assert "notifications" in features
    assert "permissions" in features


def test_returns_empty_list_for_unknown_text() -> None:
    extractor = FeatureExtractor()

    assert extractor.extract("Совершенно посторонний вопрос про погоду.") == []
