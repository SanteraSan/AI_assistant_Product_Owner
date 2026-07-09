from scripts.run_rag_evaluation import (
    EvaluationScenario,
    _build_quality_flags,
    _normalize_numeric_value,
    _normalized_numeric_values,
)


def test_normalize_numeric_value_handles_common_amount_formats() -> None:
    assert _normalize_numeric_value("1 416 960,00") == "1416960"
    assert _normalize_numeric_value("1,416,960.00") == "1416960"
    assert _normalize_numeric_value("1.416.960") == "1416960"
    assert _normalize_numeric_value("000793,00") == "793"


def test_normalized_numeric_values_preserves_decimal_values() -> None:
    assert "5.76" in _normalized_numeric_values("AVG — 5.76 мс")


def test_quality_flags_check_required_numeric_values() -> None:
    scenario = EvaluationScenario(
        id="numeric_smoke",
        name="Numeric Smoke",
        prompt="Какая общая стоимость?",
        required_numeric_values=("1416960",),
    )

    flags = _build_quality_flags(
        scenario,
        {
            "response": "Общая сумма указана как 1 416 960,00 руб.",
            "sources": [{"source_type": "image_digest"}],
        },
    )

    assert flags["response_has_required_numeric_values"] is True


def test_quality_flags_check_required_marker_groups() -> None:
    scenario = EvaluationScenario(
        id="marker_group_smoke",
        name="Marker Group Smoke",
        prompt="Какая рекомендация?",
        required_response_markers=("enterprise", "excel"),
        required_marker_groups=(("провер", "валидац", "validation"),),
    )

    flags = _build_quality_flags(
        scenario,
        {
            "response": "Enterprise onboarding требует guided Excel import validation.",
            "sources": [{"source_type": "docx"}],
        },
    )

    assert flags["response_has_required_markers"] is True
    assert flags["response_has_required_marker_groups"] is True
