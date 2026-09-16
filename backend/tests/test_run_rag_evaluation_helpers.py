import httpx

from scripts.run_rag_evaluation import (
    EvalSkip,
    EvaluationScenario,
    _build_quality_flags,
    _normalize_numeric_value,
    _normalized_numeric_values,
    _select_scenarios,
    aggregate_run_status,
    build_eval_payload,
    eval_outcome_from_response,
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


def test_select_sales_gold_suite_has_four_scenarios() -> None:
    scenarios = _select_scenarios("sales-gold", None, None)
    assert [scenario.id for scenario in scenarios] == [
        "sales_gold_nw104_amount",
        "sales_gold_au207_dates",
        "sales_gold_nw110_draft",
        "sales_gold_northwind_noleak",
    ]


def test_select_sales_catalog_suite_stays_in_planned_range() -> None:
    scenarios = _select_scenarios("sales-catalog", None, None)
    assert 8 <= len(scenarios) <= 15


def test_skip_http_errors_do_not_fail_the_run() -> None:
    skip = eval_outcome_from_response(
        httpx.Response(
            503,
            json={"error_type": "model_unavailable", "detail": "Gemini is not configured."},
        )
    )
    fail = eval_outcome_from_response(
        httpx.Response(
            502,
            json={"error_type": "external_provider_error", "detail": "boom"},
        )
    )
    skip_scope = eval_outcome_from_response(
        httpx.Response(
            503,
            json={
                "error_type": "external_provider_unavailable",
                "detail": "User location is not supported for the API use.",
            },
        )
    )
    assert isinstance(skip, EvalSkip)
    assert skip.reason == "model_unavailable"
    assert isinstance(skip_scope, EvalSkip)
    assert skip_scope.reason == "external_provider_unavailable"
    assert fail.reason == "external_provider_error"
    assert aggregate_run_status(["ok", "skip"]) == "completed"
    assert aggregate_run_status(["skip", "skip"]) == "completed"
    assert aggregate_run_status(["ok", "fail"]) == "failed"


def test_eval_payload_includes_approach_and_sales_bucket() -> None:
    scenario = EvaluationScenario(
        id="sales_payload",
        name="Sales payload",
        prompt="Сравни сумму карточки и договора по nw-104.",
        tenant_id="local_demo",
        bucket_ids=("sales_northwind",),
    )
    payload = build_eval_payload(
        scenario=scenario,
        model="qwen3.5:9b",
        top_k=8,
        approach="local_only",
        message=scenario.prompt,
    )
    assert payload["approach"] == "local_only"
    assert payload["bucket_ids"] == ["sales_northwind"]
    assert payload["tenant_id"] == "local_demo"


def test_sales_gold_flags_catch_amount_mismatch_and_layers() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_nw104_amount",
        name="Sales gold",
        prompt="Сравни сумму карточки и договора по nw-104.",
        expected_card_value="1250000",
        expected_contract_value="1180000",
        expect_mismatch=True,
        expect_layer_attribution=True,
        required_source_types=("deal_card", "sales_contract"),
        forbidden_bucket_ids=("sales_aurora",),
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "В карточке сумма 1 250 000 RUB, в договоре 1 180 000 RUB. "
                "Значения расходятся."
            ),
            "provider": "ollama",
            "sources": [
                {
                    "source_type": "deal_card",
                    "metadata": {"bucket_id": "sales_northwind"},
                },
                {
                    "source_type": "sales_contract",
                    "metadata": {"bucket_id": "sales_northwind"},
                },
            ],
            "retrieval": {
                "prompt_isolation_bucket_ids": ["sales_northwind"],
            },
        },
        expected_provider="ollama",
    )
    assert flags["both_values_present"] is True
    assert flags["mismatch_flagged"] is True
    assert flags["layer_attribution_ok"] is True
    assert flags["required_source_types_present"] is True
    assert flags["sales_sql_isolation_ok"] is True
    assert flags["sales_card_isolation_ok"] is True
    assert flags["provider_matches"] is True


def test_sales_gold_flags_accept_russian_dates() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_au207_dates",
        name="Sales gold dates",
        prompt="Сравни даты au-207.",
        expected_card_value="2026-11-01",
        expected_contract_value="2026-12-15",
        expect_mismatch=True,
        expect_layer_attribution=True,
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "В карточке закрытие 1 ноября 2026, в договоре 15 декабря 2026. "
                "Даты не совпадают."
            ),
            "sources": [],
        },
    )
    assert flags["both_values_present"] is True
    assert flags["mismatch_flagged"] is True
    assert flags["layer_attribution_ok"] is True


def test_sales_gold_flags_accept_razlichny_and_short_november() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_au207_dates",
        name="Sales gold dates",
        prompt="Сравни даты au-207.",
        expected_card_value="2026-11-01",
        expected_contract_value="2026-12-15",
        expect_mismatch=True,
        expect_layer_attribution=True,
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "В карточке ориентир 1 ноября, в договоре 15 декабря 2026. "
                "Даты различны."
            ),
            "sources": [],
        },
    )
    assert flags["card_value_present"] is True
    assert flags["contract_value_present"] is True
    assert flags["mismatch_flagged"] is True


def test_sales_mismatch_flagged_accepts_razlichayutsya() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_au207_dates",
        name="Sales gold dates",
        prompt="Сравни даты au-207.",
        expected_card_value="2026-11-01",
        expected_contract_value="2026-12-15",
        expect_mismatch=True,
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "По карточке 1 ноября 2026 (2026-11-01), "
                "по договору 15 декабря 2026 (2026-12-15). "
                "Даты закрытия различаются в зависимости от слоя."
            ),
            "sources": [],
        },
    )
    assert flags["mismatch_flagged"] is True


def test_sales_mismatch_flagged_when_legal_date_does_not_change() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_au207_dates",
        name="Sales gold dates",
        prompt="Сравни даты au-207.",
        expected_card_value="2026-11-01",
        expected_contract_value="2026-12-15",
        expect_mismatch=True,
        expect_layer_attribution=True,
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "карточка — 1 ноября 2026 (2026-11-01)\n"
                "документ — 15 декабря 2026 (2026-12-15)\n"
                "Ноябрьский ориентир не меняет официальный срок договора."
            ),
            "sources": [],
        },
    )
    assert flags["both_values_present"] is True
    assert flags["mismatch_flagged"] is True
    assert flags["layer_attribution_ok"] is True


def test_sales_noleak_accepts_grounded_refusal_wording() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_northwind_noleak",
        name="No leak",
        prompt="Что такое Aurora Polar Rebate?",
        required_marker_groups=(
            (
                "нет в контексте",
                "контексте нет",
                "нет данных",
                "дать невозможно",
                "невозможно",
            ),
        ),
        forbidden_response_markers=("777000", "au-201"),
        forbidden_bucket_ids=("sales_aurora",),
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "Программы «Aurora Polar Rebate» в предоставленном контексте нет, "
                "поэтому информацию о её существовании или сумме дать невозможно."
            ),
            "sources": [
                {
                    "source_type": "sales_note",
                    "metadata": {"bucket_id": "sales_northwind"},
                }
            ],
            "retrieval": {"prompt_isolation_bucket_ids": ["sales_northwind"]},
        },
    )
    assert flags["response_has_required_marker_groups"] is True
    assert flags["response_no_forbidden_fact"] is True


def test_sales_noleak_accepts_otsutstvuet_wording() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_northwind_noleak",
        name="No leak",
        prompt="Что такое Aurora Polar Rebate?",
        required_marker_groups=(
            (
                "нет в контексте",
                "контексте нет",
                "отсутству",
                "в них нет",
            ),
        ),
        forbidden_response_markers=("777000", "au-201"),
        forbidden_bucket_ids=("sales_aurora",),
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "На основе предоставленных фрагментов информации о программе "
                "Aurora Polar Rebate в них нет. Программа отсутствует."
            ),
            "sources": [
                {
                    "source_type": "sales_note",
                    "metadata": {"bucket_id": "sales_northwind"},
                }
            ],
            "retrieval": {"prompt_isolation_bucket_ids": ["sales_northwind"]},
        },
    )
    assert flags["response_has_required_marker_groups"] is True
    assert flags["response_no_forbidden_fact"] is True


def test_sales_noleak_rejects_aurora_amount() -> None:
    scenario = EvaluationScenario(
        id="sales_gold_northwind_noleak",
        name="No leak",
        prompt="Что такое Aurora Polar Rebate?",
        forbidden_response_markers=("777000", "au-201"),
        forbidden_bucket_ids=("sales_aurora",),
    )
    leak_flags = _build_quality_flags(
        scenario,
        {
            "response": "Программа стоит 777000 RUB.",
            "sources": [
                {
                    "source_type": "deal_card",
                    "metadata": {"bucket_id": "sales_aurora"},
                }
            ],
            "retrieval": {"prompt_isolation_bucket_ids": ["sales_northwind", "sales_aurora"]},
        },
    )
    ok_flags = _build_quality_flags(
        scenario,
        {
            "response": "В предоставленном контексте нет данных об этой программе.",
            "sources": [
                {
                    "source_type": "sales_note",
                    "metadata": {"bucket_id": "sales_northwind"},
                }
            ],
            "retrieval": {"prompt_isolation_bucket_ids": ["sales_northwind"]},
        },
    )
    assert leak_flags["response_no_forbidden_fact"] is False
    assert leak_flags["sales_card_isolation_ok"] is False
    assert leak_flags["sales_sql_isolation_ok"] is False
    assert ok_flags["response_no_forbidden_fact"] is True
    assert ok_flags["sales_card_isolation_ok"] is True
    assert ok_flags["sales_sql_isolation_ok"] is True


def test_sales_unknown_deal_accepts_v_nih_net_wording() -> None:
    scenario = EvaluationScenario(
        id="sales_catalog_unknown_deal",
        name="Unknown deal",
        prompt="Сравни сумму карточки и договора по xyz-000.",
        required_marker_groups=(
            (
                "не найден",
                "нет карточки",
                "в них нет",
                "в источниках нет",
            ),
        ),
    )
    flags = _build_quality_flags(
        scenario,
        {
            "response": (
                "договора или карточки с кодом сделки xyz-000 в них нет"
            ),
            "sources": [],
        },
    )
    assert flags["response_has_required_marker_groups"] is True
