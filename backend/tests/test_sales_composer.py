from datetime import date

import pytest

from app.models.chat import SourceChunk
from app.services.rag_service import RagSearchResult
from app.services.sales_composer import (
    SalesComposer,
    build_deal_card_source,
    build_sales_prompt_preview,
    prefer_deal_document_sources,
)
from app.services.sales_deal_code import DealIdentity, normalize_deal_code, resolve_deal_from_message
from app.services.sales_deal_repository import DemoDealRecord
from app.services.sales_demo_data import (
    AURORA_LEAK_MARKERS,
    GOLD_NW_104_CARD_AMOUNT,
    GOLD_NW_104_CONTRACT_AMOUNT,
)
from app.services.sales_scope import (
    SALES_AURORA_BUCKET_ID,
    SALES_NORTHWIND_BUCKET_ID,
    SALES_RETRIEVAL_FEATURES,
    SALES_RETRIEVAL_SOURCE_TYPES,
    is_sales_rag_scope,
)
from app.services.llm.types import GenerationResult


def test_prefer_deal_document_sources_keeps_matching_paths_first() -> None:
    playbook = SourceChunk(
        id="p",
        source_type="sales_playbook",
        source_path="sales_northwind/northwind-playbook.md",
        content="rules",
    )
    other = SourceChunk(
        id="o",
        source_type="sales_contract",
        source_path="sales_northwind/nw-101-contract.md",
        content="320000",
    )
    contract = SourceChunk(
        id="c",
        source_type="sales_contract",
        source_path="sales_northwind/nw-104-contract.md",
        content="1180000",
        metadata={"document_metadata": {"deal_code": "nw-104"}},
    )
    email = SourceChunk(
        id="e",
        source_type="sales_email",
        source_path="sales_northwind/nw-104-email.md",
        content="card",
    )
    ranked = prefer_deal_document_sources(
        [playbook, other, contract, email],
        "nw-104",
        limit=3,
    )
    assert [item.id for item in ranked] == ["c", "e", "p"]
    ranked_full = prefer_deal_document_sources(
        [playbook, other, contract, email],
        "nw-104",
        limit=8,
    )
    assert "o" not in [item.id for item in ranked_full]


def test_normalize_deal_code_collapses_separators() -> None:
    assert normalize_deal_code(" NW_104 ") == "nw-104"
    assert normalize_deal_code("nw 104") == "nw-104"
    assert normalize_deal_code("northwind-104") == "northwind-104"


def test_resolve_deal_from_canonical_code_in_sentence() -> None:
    deals = [
        DealIdentity("nw-104", SALES_NORTHWIND_BUCKET_ID, "Enterprise CRM rollout", ("northwind-104",)),
        DealIdentity("nw-101", SALES_NORTHWIND_BUCKET_ID, "CRM Starter"),
    ]
    resolved = resolve_deal_from_message("Какая сумма по сделке nw-104?", deals)
    assert resolved is not None
    assert resolved.deal_code == "nw-104"


def test_resolve_deal_from_alias_and_ignores_vague_name() -> None:
    deals = [
        DealIdentity("nw-104", SALES_NORTHWIND_BUCKET_ID, "Enterprise CRM rollout", ("northwind-104",)),
    ]
    assert resolve_deal_from_message("посмотри northwind 104", deals).deal_code == "nw-104"
    assert resolve_deal_from_message("сделка Север", deals) is None


def test_sales_scope_requires_sales_only_buckets() -> None:
    assert is_sales_rag_scope(["sales_northwind"]) is True
    assert is_sales_rag_scope(["sales_northwind", "sales_aurora"]) is True
    assert is_sales_rag_scope(["sales_northwind", "taskflow_seed"]) is False
    assert is_sales_rag_scope([]) is False


def test_northwind_prompt_does_not_contain_aurora_markers() -> None:
    deal = DemoDealRecord(
        tenant_id="local_demo",
        bucket_id=SALES_NORTHWIND_BUCKET_ID,
        deal_code="nw-104",
        title="Enterprise CRM rollout",
        amount=GOLD_NW_104_CARD_AMOUNT,
        currency="RUB",
        status="proposed",
        close_date=date(2026, 10, 20),
        owner="Anna Petrova",
        aliases=("northwind-104",),
    )
    contract = SourceChunk(
        id="c1",
        title="nw-104 contract",
        source_type="sales_contract",
        source_path="sales_northwind/nw-104-contract.md",
        feature=["sales"],
        content=f"Сумма договора: {GOLD_NW_104_CONTRACT_AMOUNT} RUB.",
        metadata={"synthetic": True},
    )
    prompt = build_sales_prompt_preview(
        question="Сравни сумму карточки и договора по nw-104",
        deal=deal,
        document_sources=[contract],
    )
    assert str(GOLD_NW_104_CARD_AMOUNT) in prompt
    assert str(GOLD_NW_104_CONTRACT_AMOUNT) in prompt
    assert "deal_card" in prompt
    for marker in AURORA_LEAK_MARKERS:
        assert marker not in prompt


def test_format_close_date_keeps_iso_and_russian_month() -> None:
    from app.services.sales_composer import format_close_date

    assert format_close_date(date(2026, 11, 1)) == "1 ноября 2026 (2026-11-01)"
    deal = DemoDealRecord(
        tenant_id="local_demo",
        bucket_id=SALES_NORTHWIND_BUCKET_ID,
        deal_code="nw-104",
        title="Enterprise CRM rollout",
        amount=GOLD_NW_104_CARD_AMOUNT,
        currency="RUB",
        status="proposed",
        close_date=date(2026, 10, 20),
        owner="Anna Petrova",
    )
    source = build_deal_card_source(deal)
    assert source.source_type == "deal_card"
    assert source.metadata["synthetic"] is True
    assert "20 октября 2026 (2026-10-20)" in source.content
    assert "Пожелание или ориентир в договоре эти факты не заменяют" in source.content


def test_sales_prompt_repeats_card_facts_after_context() -> None:
    deal = DemoDealRecord(
        tenant_id="local_demo",
        bucket_id=SALES_AURORA_BUCKET_ID,
        deal_code="au-207",
        title="Storefront analytics pack",
        amount=890_000,
        currency="RUB",
        status="proposed",
        close_date=date(2026, 11, 1),
        owner="Igor Smirnov",
    )
    contract = SourceChunk(
        id="c1",
        title="au-207 contract",
        source_type="sales_contract",
        source_path="sales_aurora/au-207-contract.md",
        feature=["sales"],
        content=(
            "Юридическая дата закрытия: 15 декабря 2026 (2026-12-15). "
            "Пожелание заказчика — ориентир ноября. Это не дата карточки."
        ),
        metadata={"synthetic": True},
    )
    prompt = build_sales_prompt_preview(
        question="Сравни дату закрытия в карточке и в договоре по au-207.",
        deal=deal,
        document_sources=[contract],
    )
    reminder_at = prompt.find("Напоминание перед ответом:")
    question_at = prompt.find("Вопрос пользователя:")
    context_at = prompt.find("Контекст:")
    assert context_at != -1
    assert reminder_at != -1
    assert question_at != -1
    assert context_at < reminder_at < question_at
    reminder = prompt[reminder_at:question_at]
    assert "1 ноября 2026 (2026-11-01)" in reminder
    assert "дословно" in reminder
    assert "слои различны" in reminder
    assert "ориентир ноября" in prompt
    assert "не являются значениями карточки" in prompt


@pytest.mark.anyio
async def test_composer_search_stays_in_selected_sales_bucket() -> None:
    captured: dict[str, object] = {}

    class _Repo:
        async def list_identities(self, *, tenant_id: str, bucket_ids: list[str]):
            assert tenant_id == "local_demo"
            assert bucket_ids == [SALES_NORTHWIND_BUCKET_ID]
            return [
                DealIdentity(
                    "nw-104",
                    SALES_NORTHWIND_BUCKET_ID,
                    "Enterprise CRM rollout",
                    ("northwind-104",),
                )
            ]

        async def get_card(self, *, tenant_id: str, bucket_ids: list[str], deal_code: str):
            captured["card_kwargs"] = {
                "tenant_id": tenant_id,
                "bucket_ids": bucket_ids,
                "deal_code": deal_code,
            }
            return DemoDealRecord(
                tenant_id=tenant_id,
                bucket_id=SALES_NORTHWIND_BUCKET_ID,
                deal_code=deal_code,
                title="Enterprise CRM rollout",
                amount=GOLD_NW_104_CARD_AMOUNT,
                currency="RUB",
                status="proposed",
                close_date=date(2026, 10, 20),
                owner="Anna Petrova",
            )

    class _Rag:
        async def search(self, **kwargs):
            captured.setdefault("searches", []).append(kwargs)
            captured["search_kwargs"] = kwargs
            return RagSearchResult(
                sources=[
                    SourceChunk(
                        id="c1",
                        content="Сумма договора: 1180000 RUB.",
                        source_type="sales_contract",
                        metadata={"synthetic": True},
                    )
                ],
                features=["sales"],
                source_types=["sales_contract"],
                score_threshold=0.45,
                retrieval={"mode": "search"},
                query_hints={},
                latency_ms=1,
            )

    class _Gateway:
        async def generate(self, **kwargs):
            captured["prompt"] = kwargs["prompt"]
            return GenerationResult(
                response="карточка 1250000, договор 1180000",
                model=kwargs["model"],
                provider="ollama",
            )

    composer = SalesComposer(
        rag_service=_Rag(),  # type: ignore[arg-type]
        deal_repository=_Repo(),  # type: ignore[arg-type]
        model_gateway=_Gateway(),  # type: ignore[arg-type]
        default_model="qwen3.5:9b",
        generation_keep_alive="10m",
        generation_temperature=0.1,
        generation_top_p=0.9,
        collection_name="documents",
    )
    response = await composer.answer(
        message="Сравни сумму по nw-104",
        tenant_id="local_demo",
        bucket_ids=[SALES_NORTHWIND_BUCKET_ID],
        approach="local_only",
    )
    searches = captured["searches"]
    assert isinstance(searches, list) and len(searches) == 2
    assert searches[0]["top_k"] == 16
    assert searches[1]["top_k"] == 8
    assert "nw-104" in str(searches[1]["query"])
    search_kwargs = captured["search_kwargs"]
    assert search_kwargs["bucket_ids"] == [SALES_NORTHWIND_BUCKET_ID]
    assert search_kwargs["features"] == SALES_RETRIEVAL_FEATURES
    assert search_kwargs["source_types"] == SALES_RETRIEVAL_SOURCE_TYPES
    assert captured["card_kwargs"]["deal_code"] == "nw-104"
    assert captured["card_kwargs"]["bucket_ids"] == [SALES_NORTHWIND_BUCKET_ID]
    assert SALES_AURORA_BUCKET_ID not in str(captured["prompt"])
    for marker in AURORA_LEAK_MARKERS:
        assert marker not in str(captured["prompt"])
    assert "source_type=deal_card" in str(captured["prompt"])
    assert "1250000" in str(captured["prompt"])
    assert "Слой карточки nw-104" in str(captured["prompt"])
    assert "Напоминание перед ответом:" in str(captured["prompt"])
    assert "20 октября 2026 (2026-10-20)" in str(captured["prompt"])
    assert search_kwargs["max_sources_per_title"] == 2
    assert search_kwargs["max_sources_per_source_path"] == 2
    assert response.retrieval["mode"] == "sales_composer"
    assert response.sources[0].source_type == "deal_card"
