from __future__ import annotations

from datetime import date
from time import perf_counter

from app.models.chat import RagChatResponse, SourceChunk
from app.services.external_scope import decide_external_scope, sources_include_non_synthetic
from app.services.llm.gateway import ModelGateway
from app.services.rag_service import RagService, build_rag_prompt, _estimate_tokens
from app.services.sales_deal_code import resolve_deal_from_message
from app.services.sales_deal_repository import DealCardRepository, DemoDealRecord
from app.services.sales_scope import SALES_RETRIEVAL_FEATURES, SALES_RETRIEVAL_SOURCE_TYPES

SALES_PROMPT_RULES = [
    (
        "Если в контексте есть карточка сделки (source_type=deal_card) и текст "
        "договора или письма — различай слои. Не смешивай числа и даты между слоями."
    ),
    (
        "Если среди источников есть source_type=deal_card, его сумма, статус и дата "
        "закрытия — факты. Назови их цифрами из этого источника. Не утверждай, что "
        "суммы или даты карточки нет в контексте, пока этот источник присутствует."
    ),
    (
        "Пожелание, ориентир, комфортная дата или промежуточный пилот в договоре "
        "или письме не являются значениями карточки. Даже если месяц или сумма "
        "рядом похожи, копируй карточку только из источника deal_card."
    ),
    (
        "Не утверждай, что письмо уже отправлено, если в контексте нет явного "
        "факта отправки."
    ),
    (
        "Если вопрос про сумму, дату или статус сделки, начни ответ с двух коротких "
        "строк: «карточка — <значение из deal_card>»; «документ — <значение из "
        "договора или письма>». Потом коротко сравни слои. Если значения не "
        "совпадают, напиши что слои различны."
    ),
]

_RU_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_close_date(value: date) -> str:
    return f"{value.day} {_RU_MONTHS[value.month - 1]} {value.year} ({value.isoformat()})"


def deal_card_layer_rule(deal: DemoDealRecord) -> str:
    formatted_close = format_close_date(deal.close_date)
    return (
        "Слой карточки "
        f"{deal.deal_code}: сумма {deal.amount} {deal.currency}, "
        f"статус {deal.status}, дата закрытия {formatted_close}. "
        "Назови эти значения как карточку. Значения из договоров и писем называй отдельно. "
        "Пожелание, ориентир, комфортная дата или пилот в документе их не заменяют. "
        "Если документ содержит другое значение — назови оба слоя и напиши, что они различны."
    )


def deal_card_closing_reminder(deal: DemoDealRecord) -> str:
    formatted_close = format_close_date(deal.close_date)
    return (
        f"Карточка {deal.deal_code}: сумма {deal.amount} {deal.currency}; "
        f"статус {deal.status}; дата закрытия {formatted_close}. "
        "Копируй сумму, статус и дату карточки из этого напоминания дословно. "
        "Не подменяй их пожеланием или ориентиром из договора или письма. "
        "Если в документе другая дата или сумма — слои различны."
    )


def prefer_deal_document_sources(
    sources: list[SourceChunk],
    deal_code: str,
    *,
    limit: int,
) -> list[SourceChunk]:
    """Keep the resolved deal's files first.

    Cabinet playbooks may follow. Other deals' contracts stay out so they cannot
    drown the gold facts of the asked code.
    """
    code = deal_code.strip().lower()
    matched: list[SourceChunk] = []
    playbookish: list[SourceChunk] = []
    rest: list[SourceChunk] = []
    for source in sources:
        if _source_matches_deal_code(source, code):
            matched.append(source)
        elif (source.source_type or "") in {"sales_playbook", "sales_note"}:
            playbookish.append(source)
        else:
            rest.append(source)
    preferred = matched + playbookish if matched else rest + playbookish
    merged: list[SourceChunk] = []
    seen: set[str] = set()
    for source in preferred:
        if source.id in seen:
            continue
        merged.append(source)
        seen.add(source.id)
        if len(merged) >= limit:
            break
    return merged


def _merge_unique_sources(*groups: list[SourceChunk]) -> list[SourceChunk]:
    merged: list[SourceChunk] = []
    seen: set[str] = set()
    for group in groups:
        for source in group:
            if source.id in seen:
                continue
            merged.append(source)
            seen.add(source.id)
    return merged


def _source_matches_deal_code(source: SourceChunk, deal_code: str) -> bool:
    if not deal_code:
        return False
    path = (source.source_path or "").lower()
    if deal_code in path:
        return True
    metadata = source.metadata or {}
    if str(metadata.get("deal_code") or "").strip().lower() == deal_code:
        return True
    nested = metadata.get("document_metadata")
    if isinstance(nested, dict) and str(nested.get("deal_code") or "").strip().lower() == deal_code:
        return True
    return False


class SalesComposer:
    def __init__(
        self,
        *,
        rag_service: RagService,
        deal_repository: DealCardRepository,
        model_gateway: ModelGateway | None,
        default_model: str,
        generation_keep_alive: str,
        generation_temperature: float,
        generation_top_p: float,
        collection_name: str,
        default_top_k: int = 8,
        default_score_threshold: float = 0.45,
    ) -> None:
        self._rag_service = rag_service
        self._deal_repository = deal_repository
        self._model_gateway = model_gateway
        self._default_model = default_model
        self._collection_name = collection_name
        self._generation_keep_alive = generation_keep_alive
        self._generation_temperature = generation_temperature
        self._generation_top_p = generation_top_p
        self._default_top_k = default_top_k
        self._default_score_threshold = default_score_threshold

    async def answer(
        self,
        message: str,
        model: str | None = None,
        retrieval_query: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
        tenant_id: str | None = None,
        bucket_ids: list[str] | None = None,
        features: list[str] | None = None,
        source_types: list[str] | None = None,
        document_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        allowed_source_paths: list[str] | None = None,
        max_sources_per_title: int | None = None,
        max_sources_per_source_type: int | None = None,
        max_sources_per_source_path: int | None = None,
        memory_context: dict[str, object] | None = None,
        additional_sources: list[SourceChunk] | None = None,
        approach: str | None = None,
        session_seen_non_synthetic: bool = False,
    ) -> RagChatResponse:
        del features, source_types, additional_sources
        selected_model = model or self._default_model
        selected_retrieval_query = retrieval_query or message
        selected_tenant_id = (tenant_id or "").strip()
        selected_bucket_ids = [item.strip() for item in (bucket_ids or []) if item.strip()]
        selected_top_k = top_k or self._default_top_k
        selected_max_per_title = (
            max_sources_per_title if max_sources_per_title is not None else 2
        )
        selected_max_per_path = (
            max_sources_per_source_path if max_sources_per_source_path is not None else 2
        )
        selected_score_threshold = (
            score_threshold if score_threshold is not None else self._default_score_threshold
        )
        started_at = perf_counter()

        identities = []
        if selected_tenant_id and selected_bucket_ids:
            identities = await self._deal_repository.list_identities(
                tenant_id=selected_tenant_id,
                bucket_ids=selected_bucket_ids,
            )
        resolved = resolve_deal_from_message(message, identities)
        deal_card: DemoDealRecord | None = None
        if resolved is not None and selected_tenant_id:
            deal_card = await self._deal_repository.get_card(
                tenant_id=selected_tenant_id,
                bucket_ids=selected_bucket_ids,
                deal_code=resolved.deal_code,
            )

        selected_search_top_k = max(selected_top_k * 2, selected_top_k)
        search = await self._rag_service.search(
            query=selected_retrieval_query,
            top_k=selected_search_top_k,
            score_threshold=selected_score_threshold,
            tenant_id=selected_tenant_id or None,
            bucket_ids=selected_bucket_ids,
            features=SALES_RETRIEVAL_FEATURES,
            source_types=SALES_RETRIEVAL_SOURCE_TYPES,
            document_ids=document_ids,
            source_paths=source_paths,
            allowed_source_paths=allowed_source_paths,
            max_sources_per_title=selected_max_per_title,
            max_sources_per_source_type=max_sources_per_source_type,
            max_sources_per_source_path=selected_max_per_path,
        )
        document_sources = list(search.sources)
        extra_rules = list(SALES_PROMPT_RULES)
        if deal_card is not None:
            targeted = await self._rag_service.search(
                query=f"{deal_card.deal_code} {deal_card.title}",
                top_k=selected_top_k,
                score_threshold=selected_score_threshold,
                tenant_id=selected_tenant_id or None,
                bucket_ids=selected_bucket_ids,
                features=SALES_RETRIEVAL_FEATURES,
                source_types=SALES_RETRIEVAL_SOURCE_TYPES,
                document_ids=document_ids,
                source_paths=source_paths,
                allowed_source_paths=allowed_source_paths,
                max_sources_per_title=selected_max_per_title,
                max_sources_per_source_type=max_sources_per_source_type,
                max_sources_per_source_path=selected_max_per_path,
            )
            document_sources = prefer_deal_document_sources(
                _merge_unique_sources(targeted.sources, document_sources),
                deal_card.deal_code,
                limit=selected_top_k,
            )
            extra_rules.append(deal_card_layer_rule(deal_card))
        else:
            document_sources = document_sources[:selected_top_k]
            extra_rules.append(
                "Карточка сделки по каноническому коду не найдена. "
                "Не выдумывай сумму, статус и дату карточки."
            )

        sources: list[SourceChunk] = []
        closing_instructions = None
        if deal_card is not None:
            sources.append(build_deal_card_source(deal_card))
            closing_instructions = deal_card_closing_reminder(deal_card)
        sources.extend(document_sources)
        prompt = build_rag_prompt(
            question=message,
            sources=sources,
            extra_rules=extra_rules,
            memory_context=memory_context,
            closing_instructions=closing_instructions,
        )
        retrieved_non_synthetic = sources_include_non_synthetic(sources)
        scope_decision = decide_external_scope(
            approach=approach,
            endpoint="rag",
            session_seen_non_synthetic_flag=session_seen_non_synthetic,
            retrieved_non_synthetic=retrieved_non_synthetic,
        )
        generation_options = {
            "temperature": self._generation_temperature,
            "top_p": self._generation_top_p,
        }
        if self._model_gateway is None:
            raise RuntimeError("SalesComposer requires ModelGateway")
        generation = await self._model_gateway.generate(
            model=selected_model,
            prompt=prompt,
            approach=approach,
            endpoint="rag",
            allow_external_fallback=scope_decision.allow_external_fallback,
            keep_alive=self._generation_keep_alive,
            options=generation_options,
            think=False,
        )
        latency_ms = int((perf_counter() - started_at) * 1000)
        retrieval = {
            **search.retrieval,
            "mode": "sales_composer",
            "deal_code": deal_card.deal_code if deal_card is not None else None,
            "deal_bucket_id": deal_card.bucket_id if deal_card is not None else None,
            "deal_card_present": deal_card is not None,
            "final_top_k": len(sources),
            "prompt_ isolation_bucket_ids": selected_bucket_ids,
            "external_scope": {
                "allow_external_fallback": scope_decision.allow_external_fallback,
                "persist_session_seen_non_synthetic": (
                    scope_decision.persist_session_seen_non_synthetic
                ),
                "deny_reason": scope_decision.deny_reason,
            },
        }
        return RagChatResponse(
            model=selected_model,
            response=generation.response,
            latency_ms=latency_ms,
            provider=generation.provider,
            provider_response_model_id=generation.provider_response_model_id,
            fallback_from=generation.fallback_from,
            fallback_to=generation.fallback_to,
            finish_reason=generation.finish_reason,
            prompt_tokens=generation.prompt_tokens,
            completion_tokens=generation.completion_tokens,
            cost_estimated=generation.cost_estimated,
            estimated_cost_usd=generation.estimated_cost_usd,
            collection=self._collection_name,
            sources=sources,
            score_threshold=search.score_threshold,
            features=search.features,
            source_types=search.source_types,
            diversity={
                "max_sources_per_title": selected_max_per_title,
                "max_sources_per_source_type": max_sources_per_source_type,
                "max_sources_per_source_path": selected_max_per_path,
            },
            retrieval=retrieval,
            query_hints={
                **search.query_hints,
                "sales_composer": True,
                "resolved_deal_code": deal_card.deal_code if deal_card else None,
            },
            context_policy={"mode": "sales_composer"},
            prompt_tokens_estimate=_estimate_tokens(prompt),
        )


def build_deal_card_source(deal: DemoDealRecord) -> SourceChunk:
    formatted_close = format_close_date(deal.close_date)
    content = "\n".join(
        [
            "Слой: карточка сделки (demo_deals)",
            f"Код: {deal.deal_code}",
            f"Название: {deal.title}",
            (
                "ФАКТЫ КАРТОЧКИ — назови эти цифры отдельно от договора: "
                f"сумма {deal.amount} {deal.currency}; "
                f"статус {deal.status}; "
                f"дата закрытия {formatted_close}. "
                "Пожелание или ориентир в договоре эти факты не заменяют."
            ),
            f"Сумма: {deal.amount} {deal.currency}",
            f"Статус: {deal.status}",
            f"Дата закрытия: {formatted_close}",
            f"Владелец: {deal.owner}",
            f"Кабинет: {deal.bucket_id}",
        ]
    )
    return SourceChunk(
        id=f"deal_card:{deal.bucket_id}:{deal.deal_code}",
        title=f"Deal card {deal.deal_code}",
        source_type="deal_card",
        source_path=f"demo_deals/{deal.bucket_id}/{deal.deal_code}",
        feature=["sales"],
        content=content,
        metadata={
            "synthetic": True,
            "deal_code": deal.deal_code,
            "bucket_id": deal.bucket_id,
            "layer": "deal_card",
            "document_metadata": {
                "synthetic": True,
                "deal_code": deal.deal_code,
                "file_name": f"{deal.deal_code}-card.sql",
            },
        },
    )


def build_sales_prompt_preview(
    *,
    question: str,
    deal: DemoDealRecord | None,
    document_sources: list[SourceChunk],
) -> str:
    sources: list[SourceChunk] = []
    extra_rules = list(SALES_PROMPT_RULES)
    closing_instructions = None
    if deal is not None:
        sources.append(build_deal_card_source(deal))
        extra_rules.append(deal_card_layer_rule(deal))
        closing_instructions = deal_card_closing_reminder(deal)
    else:
        extra_rules.append(
            "Карточка сделки по каноническому коду не найдена. "
            "Не выдумывай сумму, статус и дату карточки."
        )
    sources.extend(document_sources)
    return build_rag_prompt(
        question=question,
        sources=sources,
        extra_rules=extra_rules,
        closing_instructions=closing_instructions,
    )
