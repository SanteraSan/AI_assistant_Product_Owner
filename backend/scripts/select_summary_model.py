import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine, database_available
from app.models.conversation_summary import LlmStructuredSummary
from app.services.feature_extractor import FeatureExtractor
from app.services.ollama_client import OllamaClient


KNOWN_FEATURES = {
    "notifications",
    "csv_import",
    "permissions",
    "reports",
    "search",
    "webhooks",
    "integrations",
}


@dataclass(frozen=True)
class TranscriptExample:
    session_id: str
    messages: list[dict[str, Any]]
    expected_features: list[str]


@dataclass(frozen=True)
class SummaryCandidateResult:
    session_id: str
    model: str
    latency_ms: int | None
    structured_summary: dict[str, object]
    raw_response: str
    error: str | None
    guardrails: dict[str, object]
    validation_warnings: list[str]


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    engine = create_engine(settings.postgres_dsn)
    try:
        if not await database_available(engine):
            raise RuntimeError("PostgreSQL is not available. Start docker compose first.")

        async with engine.connect() as connection:
            examples = await _fetch_examples(
                connection=connection,
                limit=args.limit,
                messages_limit=args.messages_limit,
                min_messages=args.min_messages,
            )

        if not examples:
            print("No transcript examples found.")
            return

        client = OllamaClient(
            base_url=settings.ollama_base_url,
            timeout_seconds=args.timeout_seconds,
        )
        results: list[SummaryCandidateResult] = []
        for example_index, example in enumerate(examples, start=1):
            print(
                f"example={example_index}/{len(examples)} "
                f"session_id={example.session_id} "
                f"expected_features={example.expected_features}"
            )
            for model in args.models:
                result = await _run_candidate(
                    client=client,
                    model=model,
                    example=example,
                    temperature=args.temperature,
                )
                results.append(result)
                status = "ok" if result.error is None else "error"
                print(
                    f"  {status} model={model} latency_ms={result.latency_ms} "
                    f"guardrails={result.guardrails}"
                )

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = output_dir / "summary_model_selection_latest.jsonl"
        markdown_path = output_dir / "SUMMARY_MODEL_SELECTION_REVIEW.md"
        _write_jsonl(path=jsonl_path, results=results)
        _write_markdown(
            path=markdown_path,
            examples=examples,
            results=results,
        )
        _print_summary(results)
        print(f"jsonl={jsonl_path}")
        print(f"review_markdown={markdown_path}")
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare summarizer models manually.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--messages-limit", type=int, default=20)
    parser.add_argument("--min-messages", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--output-dir",
        default="/home/santera/Projects/research",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="Candidate Ollama summarizer models.",
    )
    return parser.parse_args()


async def _fetch_examples(
    *,
    connection: Any,
    limit: int,
    messages_limit: int,
    min_messages: int,
) -> list[TranscriptExample]:
    session_rows = await connection.execute(
        text(
            """
            select session_id, count(*) as message_count, max(created_at) as last_message_at
            from chat_messages
            group by session_id
            having count(*) >= :min_messages
            order by last_message_at desc
            limit :limit
            """
        ),
        {"limit": limit, "min_messages": min_messages},
    )

    examples: list[TranscriptExample] = []
    feature_extractor = FeatureExtractor()
    for session_row in session_rows.mappings():
        messages = await _fetch_messages(
            connection=connection,
            session_id=str(session_row["session_id"]),
            limit=messages_limit,
        )
        user_text = "\n".join(
            str(message["content"])
            for message in messages
            if message["role"] == "user"
        )
        examples.append(
            TranscriptExample(
                session_id=str(session_row["session_id"]),
                messages=messages,
                expected_features=feature_extractor.extract(user_text),
            )
        )
    return examples


async def _fetch_messages(
    *,
    connection: Any,
    session_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    result = await connection.execute(
        text(
            """
            select role, content, created_at
            from (
                select role, content, created_at
                from chat_messages
                where session_id = :session_id
                order by created_at desc
                limit :limit
            ) recent_messages
            order by created_at
            """
        ),
        {"session_id": session_id, "limit": limit},
    )
    return [dict(row) for row in result.mappings()]


async def _run_candidate(
    *,
    client: OllamaClient,
    model: str,
    example: TranscriptExample,
    temperature: float,
) -> SummaryCandidateResult:
    started_at = asyncio.get_running_loop().time()
    raw_response = ""
    try:
        result = await client.generate(
            model=model,
            prompt=_build_prompt(
                messages=example.messages,
                allowed_features=example.expected_features,
            ),
            keep_alive="10m",
            options={
                "temperature": temperature,
                "top_p": 0.9,
            },
            think=False,
        )
        raw_response = str(result.get("response") or "")
        try:
            structured_summary, validation_warnings = _parse_structured_summary(
                response_text=raw_response,
                allowed_features=example.expected_features,
            )
            repair_retry_used = False
        except ValueError as exc:
            structured_summary, validation_warnings, raw_response = await _repair_summary(
                client=client,
                model=model,
                original_response=raw_response,
                validation_error=str(exc),
                allowed_features=example.expected_features,
                temperature=temperature,
            )
            repair_retry_used = True
        latency_ms = int((asyncio.get_running_loop().time() - started_at) * 1000)
        return SummaryCandidateResult(
            session_id=example.session_id,
            model=model,
            latency_ms=latency_ms,
            structured_summary=structured_summary,
            raw_response=raw_response,
            error=None,
            guardrails=_build_guardrails(
                structured_summary=structured_summary,
                expected_features=example.expected_features,
                validation_warnings=validation_warnings,
                repair_retry_used=repair_retry_used,
            ),
            validation_warnings=validation_warnings,
        )
    except (httpx.HTTPError, ValueError) as exc:
        latency_ms = int((asyncio.get_running_loop().time() - started_at) * 1000)
        return SummaryCandidateResult(
            session_id=example.session_id,
            model=model,
            latency_ms=latency_ms,
            structured_summary={},
            raw_response=raw_response,
            error=str(exc),
            guardrails={
                "valid_json": False,
                "russian_language_ok": False,
                "no_hallucinated_known_features": False,
                "hallucinated_known_features": [],
                "forbidden_known_features_in_main_topics": [],
                "discarded_known_features_from_main_topics": [],
                "forbidden_known_features_in_text": [],
                "allowed_contextual_forbidden_mentions": [],
                "validation_warnings": [],
                "repair_retry_used": False,
                "safe_for_prompt_review": False,
            },
            validation_warnings=[],
        )


async def _repair_summary(
    *,
    client: OllamaClient,
    model: str,
    original_response: str,
    validation_error: str,
    allowed_features: list[str],
    temperature: float,
) -> tuple[dict[str, object], list[str], str]:
    result = await client.generate(
        model=model,
        prompt=_build_repair_prompt(
            original_response=original_response,
            validation_error=validation_error,
            allowed_features=allowed_features,
        ),
        keep_alive="10m",
        options={
            "temperature": temperature,
            "top_p": 0.9,
        },
        think=False,
    )
    repaired_response = str(result.get("response") or "")
    structured_summary, validation_warnings = _parse_structured_summary(
        response_text=repaired_response,
        allowed_features=allowed_features,
    )
    return structured_summary, validation_warnings, repaired_response


def _build_prompt(
    *,
    messages: list[dict[str, Any]],
    allowed_features: list[str],
) -> str:
    transcript = "\n".join(
        f"{message['role']}: {' '.join(str(message['content']).split())}"
        for message in messages
    )
    allowed_features_text = ", ".join(allowed_features) if allowed_features else "нет"
    return f"""Ты сжимаешь историю диалога для memory layer AI-ассистента Product Owner.

Верни только валидный JSON без markdown.

Правила:
- Пиши на русском языке.
- Summary описывает только диалог: цели пользователя, решения, ограничения и открытые вопросы.
- Не добавляй product facts или features, которых нет в диалоге.
- Product features в `main_topics` можно использовать только из списка allowed_features.
- Если в ответах ассистента упоминались другие product features для сравнения, не добавляй их в `main_topics`.
- `decisions` включает только явные договоренности или конкретные рекомендованные действия, которые были центральны для диалога. Если это рекомендация ассистента, формулируй как "рекомендовано ...".
- Если открытых вопросов или решений нет, верни пустой массив.
- Будь кратким: summary 2-4 предложения.

allowed_features: {allowed_features_text}

JSON schema:
{{
  "main_topics": ["темы или allowed product features"],
  "user_goals": ["что пользователь пытается понять или сделать"],
  "decisions": ["явные договоренности или центральные рекомендованные действия"],
  "open_questions": ["что осталось выяснить"],
  "constraints": ["явные ограничения пользователя"],
  "summary": "2-4 предложения компактного summary диалога"
}}

Диалог:
{transcript}
"""


def _build_repair_prompt(
    *,
    original_response: str,
    validation_error: str,
    allowed_features: list[str],
) -> str:
    allowed_features_text = ", ".join(allowed_features) if allowed_features else "нет"
    return f"""Предыдущий JSON summary не прошел validation.

Ошибка:
{validation_error}

Исправь только структуру JSON. Не добавляй новые факты и product features.
Если отсутствует `summary`, составь 1-2 кратких предложения только на основе уже имеющихся полей JSON.
`main_topics` можно использовать только из allowed_features.

allowed_features: {allowed_features_text}

Верни только валидный JSON без markdown:
{{
  "main_topics": ["allowed product features"],
  "user_goals": ["что пользователь пытается понять или сделать"],
  "decisions": ["явные договоренности или центральные рекомендованные действия"],
  "open_questions": ["что осталось выяснить"],
  "constraints": ["явные ограничения пользователя"],
  "summary": "1-2 предложения summary диалога"
}}

Исходный JSON:
{original_response}
"""


def _parse_structured_summary(
    *,
    response_text: str,
    allowed_features: list[str],
) -> tuple[dict[str, object], list[str]]:
    raw_json = _extract_json_object(response_text)
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("summary JSON must be an object")
    try:
        summary_model = LlmStructuredSummary(**parsed)
    except ValueError as exc:
        raise ValueError(f"summary JSON failed schema validation: {exc}") from exc
    compact_summary = summary_model.to_compact_dict()
    if not compact_summary["summary"]:
        raise ValueError("summary JSON must include a non-empty summary")
    main_topics, discarded_topics = _filter_allowed_main_topics(
        main_topics=_as_str_list(compact_summary.get("main_topics")),
        allowed_features=allowed_features,
    )
    return {
        "main_topics": main_topics,
        "user_goals": _as_str_list(compact_summary.get("user_goals")),
        "decisions": _as_str_list(compact_summary.get("decisions")),
        "open_questions": _as_str_list(compact_summary.get("open_questions")),
        "constraints": _as_str_list(compact_summary.get("constraints")),
        "summary": compact_summary["summary"],
    }, _build_validation_warnings(discarded_topics)


def _filter_allowed_main_topics(
    *,
    main_topics: list[str],
    allowed_features: list[str],
) -> tuple[list[str], list[str]]:
    allowed_by_normalized = {
        _normalize_feature_topic(feature): feature
        for feature in allowed_features
    }
    filtered: list[str] = []
    discarded: list[str] = []
    for topic in main_topics:
        normalized_topic = _normalize_feature_topic(topic)
        allowed_topic = allowed_by_normalized.get(normalized_topic)
        if allowed_topic is None:
            discarded.append(topic)
            continue
        if allowed_topic not in filtered:
            filtered.append(allowed_topic)
    return filtered, discarded


def _build_validation_warnings(discarded_topics: list[str]) -> list[str]:
    if not discarded_topics:
        return []
    return [
        "discarded_main_topics_not_in_allowed_features: "
        + ", ".join(discarded_topics)
    ]


def _normalize_feature_topic(value: str) -> str:
    return value.strip().strip("`").lower()


def _extract_json_object(text_value: str) -> str:
    stripped = text_value.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response did not contain a JSON object")
    return stripped[start : end + 1]


def _as_str_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        compact = " ".join(item.split())
        if not compact or compact in normalized:
            continue
        normalized.append(compact[:240])
        if len(normalized) >= limit:
            break
    return normalized


def _build_guardrails(
    *,
    structured_summary: dict[str, object],
    expected_features: list[str],
    validation_warnings: list[str],
    repair_retry_used: bool = False,
) -> dict[str, object]:
    expected_feature_set = set(expected_features)
    forbidden_known_features_in_main_topics = sorted(
        _known_features_in_value(structured_summary.get("main_topics"))
        - expected_feature_set
    )
    discarded_known_features_from_main_topics = sorted(
        _known_features_in_value(validation_warnings) - expected_feature_set
    )
    text_fields = {
        "user_goals": structured_summary.get("user_goals"),
        "decisions": structured_summary.get("decisions"),
        "open_questions": structured_summary.get("open_questions"),
        "constraints": structured_summary.get("constraints"),
        "summary": structured_summary.get("summary"),
    }
    allowed_contextual_forbidden_mentions = sorted(
        _contextually_allowed_forbidden_features(
            value=text_fields,
            expected_features=expected_features,
        )
    )
    forbidden_known_features_in_text = sorted(
        _known_features_in_value(text_fields)
        - expected_feature_set
        - set(allowed_contextual_forbidden_mentions)
    )
    hallucinated_known_features = sorted(
        {
            *forbidden_known_features_in_main_topics,
            *discarded_known_features_from_main_topics,
            *forbidden_known_features_in_text,
        }
    )
    text_value = json.dumps(structured_summary, ensure_ascii=False).lower()
    russian_language_ok = _looks_russian(text_value)
    no_hallucinated_known_features = not hallucinated_known_features
    return {
        "valid_json": True,
        "russian_language_ok": russian_language_ok,
        "no_hallucinated_known_features": no_hallucinated_known_features,
        "hallucinated_known_features": hallucinated_known_features,
        "forbidden_known_features_in_main_topics": forbidden_known_features_in_main_topics,
        "discarded_known_features_from_main_topics": discarded_known_features_from_main_topics,
        "forbidden_known_features_in_text": forbidden_known_features_in_text,
        "allowed_contextual_forbidden_mentions": allowed_contextual_forbidden_mentions,
        "validation_warnings": validation_warnings,
        "repair_retry_used": repair_retry_used,
        "has_summary": bool(str(structured_summary.get("summary") or "").strip()),
        "has_user_goals": bool(structured_summary.get("user_goals")),
        "has_decisions": bool(structured_summary.get("decisions")),
        "has_open_questions": bool(structured_summary.get("open_questions")),
        "summary_length": len(str(structured_summary.get("summary") or "")),
        "safe_for_prompt_review": russian_language_ok and no_hallucinated_known_features,
    }


def _known_features_in_value(value: object) -> set[str]:
    text_value = json.dumps(value, ensure_ascii=False).lower()
    return {feature for feature in KNOWN_FEATURES if feature in text_value}


def _contextually_allowed_forbidden_features(
    *,
    value: object,
    expected_features: list[str],
) -> set[str]:
    text_value = json.dumps(value, ensure_ascii=False).lower()
    expected_feature_set = set(expected_features)
    allowed_mentions: set[str] = set()
    for feature in KNOWN_FEATURES - expected_feature_set:
        start = 0
        while True:
            index = text_value.find(feature, start)
            if index < 0:
                break
            window = text_value[max(0, index - 100) : index + len(feature) + 100]
            if _is_contextually_allowed_mention(window, feature):
                allowed_mentions.add(feature)
            start = index + len(feature)
    return allowed_mentions


def _is_contextually_allowed_mention(text_value: str, feature: str) -> bool:
    return _is_contextual_boundary_mention(text_value) or _is_operational_team_mention(
        text_value=text_value,
        feature=feature,
    )


def _is_contextual_boundary_mention(text_value: str) -> bool:
    boundary_markers = (
        "не смеш",
        "не классифиц",
        "не относ",
        "не добав",
        "не включ",
        "не считать",
        "не следует пут",
        "отдел",
        "раздел",
        "не пут",
        "не является",
        "не относится",
    )
    return any(marker in text_value for marker in boundary_markers)


def _is_operational_team_mention(*, text_value: str, feature: str) -> bool:
    if feature != "integrations":
        return False
    operational_markers = (
        "integrations team",
        "integration team",
        "команду интеграц",
        "команда интеграц",
        "команде интеграц",
    )
    return any(marker in text_value for marker in operational_markers)


def _looks_russian(text_value: str) -> bool:
    cyrillic_count = sum("а" <= char <= "я" or char == "ё" for char in text_value)
    latin_or_cjk_count = sum(
        ("a" <= char <= "z") or ("\u4e00" <= char <= "\u9fff")
        for char in text_value
    )
    return cyrillic_count > 20 and cyrillic_count >= latin_or_cjk_count


def _write_jsonl(path: Path, results: list[SummaryCandidateResult]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(
                json.dumps(
                    {
                        "session_id": result.session_id,
                        "model": result.model,
                        "latency_ms": result.latency_ms,
                        "structured_summary": result.structured_summary,
                        "raw_response": result.raw_response,
                        "error": result.error,
                        "guardrails": result.guardrails,
                        "validation_warnings": result.validation_warnings,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _write_markdown(
    *,
    path: Path,
    examples: list[TranscriptExample],
    results: list[SummaryCandidateResult],
) -> None:
    results_by_session = {
        (result.session_id, result.model): result
        for result in results
    }
    models = sorted({result.model for result in results})
    lines = [
        "# Summary Model Selection Review",
        "",
        "Manual rubric per candidate:",
        "",
        "- Отлично: можно использовать в prompt без правок.",
        "- Хорошо: minor issue, still safe.",
        "- Средне: useful, but missing decisions/open questions or too noisy.",
        "- Плохо: hallucination, wrong language, invalid structure, unsafe.",
        "",
    ]
    for index, example in enumerate(examples, start=1):
        lines.extend(
            [
                "---",
                "",
                f"## Example #{index}",
                "",
                f"`session_id`: `{example.session_id}`",
                f"`expected_features`: `{example.expected_features}`",
                "",
                "### Transcript",
                "",
            ]
        )
        for message in example.messages:
            lines.append(f"- **{message['role']}**: {_compact(message['content'], 700)}")
        lines.append("")
        for model in models:
            result = results_by_session.get((example.session_id, model))
            if result is None:
                continue
            lines.extend(
                [
                    f"### Candidate: `{model}`",
                    "",
                    f"- latency_ms: `{result.latency_ms}`",
                    f"- error: `{result.error}`",
                    f"- guardrails: `{result.guardrails}`",
                    f"- validation_warnings: `{result.validation_warnings}`",
                    "",
                    "**Structured summary**",
                    "",
                    "```json",
                    json.dumps(result.structured_summary, ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "**Manual score:** ",
                    "",
                    "**Notes:** ",
                    "",
                ]
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def _print_summary(results: list[SummaryCandidateResult]) -> None:
    print()
    print("Automatic guardrail summary:")
    for model in sorted({result.model for result in results}):
        model_results = [result for result in results if result.model == model]
        latencies = [
            result.latency_ms
            for result in model_results
            if result.latency_ms is not None
        ]
        errors = sum(1 for result in model_results if result.error)
        repair_retry_count = sum(
            1
            for result in model_results
            if result.guardrails.get("repair_retry_used") is True
        )
        safe_count = sum(
            1
            for result in model_results
            if result.guardrails.get("safe_for_prompt_review") is True
        )
        hallucinated_count = sum(
            1
            for result in model_results
            if result.guardrails.get("no_hallucinated_known_features") is False
        )
        text_forbidden_count = sum(
            1
            for result in model_results
            if result.guardrails.get("forbidden_known_features_in_text")
        )
        contextual_allowed_count = sum(
            1
            for result in model_results
            if result.guardrails.get("allowed_contextual_forbidden_mentions")
        )
        main_topic_forbidden_count = sum(
            1
            for result in model_results
            if result.guardrails.get("forbidden_known_features_in_main_topics")
        )
        discarded_topic_count = sum(
            1
            for result in model_results
            if result.guardrails.get("discarded_known_features_from_main_topics")
        )
        russian_fail_count = sum(
            1
            for result in model_results
            if result.guardrails.get("russian_language_ok") is False
        )
        avg_latency = int(mean(latencies)) if latencies else None
        print(
            f"- {model}: results={len(model_results)}, avg_latency_ms={avg_latency}, "
            f"errors={errors}, safe={safe_count}, repair_retries={repair_retry_count}, "
            f"hallucinated_known_feature_cases={hallucinated_count}, "
            f"text_forbidden_cases={text_forbidden_count}, "
            f"contextual_allowed_cases={contextual_allowed_count}, "
            f"main_topic_forbidden_cases={main_topic_forbidden_count}, "
            f"discarded_topic_cases={discarded_topic_count}, "
            f"russian_failures={russian_fail_count}"
        )


def _compact(text_value: object, limit: int) -> str:
    compact = " ".join(str(text_value).split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


if __name__ == "__main__":
    asyncio.run(main())
