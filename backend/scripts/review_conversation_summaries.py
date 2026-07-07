import argparse
import asyncio
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine, database_available
from app.services.feature_extractor import FeatureExtractor


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    engine = create_engine(settings.postgres_dsn)
    try:
        if not await database_available(engine):
            raise RuntimeError("PostgreSQL is not available. Start docker compose first.")

        async with engine.connect() as connection:
            summaries = await _fetch_summaries(
                connection=connection,
                limit=args.limit,
                strategy=args.strategy,
            )
            if not summaries:
                print("No conversation summaries found.")
                return
            for index, summary in enumerate(summaries, start=1):
                messages = await _fetch_messages(
                    connection=connection,
                    session_id=summary["session_id"],
                    limit=args.messages_limit,
                )
                _print_review_card(index=index, summary=summary, messages=messages)
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print conversation summary review cards for manual QA."
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--messages-limit", type=int, default=12)
    parser.add_argument(
        "--strategy",
        default=None,
        help="Optional summary strategy filter, e.g. hybrid, llm, rule_based.",
    )
    return parser.parse_args()


async def _fetch_summaries(
    *,
    connection: Any,
    limit: int,
    strategy: str | None,
) -> list[dict[str, Any]]:
    where_clause = ""
    params: dict[str, Any] = {"limit": limit}
    if strategy:
        where_clause = "where metadata_json->>'strategy' = :strategy"
        params["strategy"] = strategy

    result = await connection.execute(
        text(
            f"""
            select
                session_id,
                summary,
                features,
                message_count_at_update,
                metadata_json,
                updated_at
            from conversation_summaries
            {where_clause}
            order by updated_at desc
            limit :limit
            """
        ),
        params,
    )
    return [dict(row) for row in result.mappings()]


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


def _print_review_card(
    *,
    index: int,
    summary: dict[str, Any],
    messages: list[dict[str, Any]],
) -> None:
    metadata = summary.get("metadata_json") or {}
    structured_summary = metadata.get("structured_summary") or {}
    rule_based_summary = _build_rule_based_summary(messages)

    print("=" * 100)
    print(f"Review card #{index}")
    print(f"session_id: {summary['session_id']}")
    print(f"updated_at: {summary['updated_at']}")
    print(f"message_count_at_update: {summary['message_count_at_update']}")
    print(f"features: {summary.get('features') or []}")
    print(
        "summary_meta: "
        f"strategy={metadata.get('strategy')} | "
        f"model={metadata.get('summary_model')} | "
        f"trigger={metadata.get('trigger')} | "
        f"fallback={metadata.get('fallback_used')} | "
        f"validation_error={metadata.get('validation_error')}"
    )
    print()
    print("Transcript excerpt:")
    for message in messages:
        content = _compact(message["content"], limit=500)
        print(f"- {message['role']}: {content}")
    print()
    print("Rule-based baseline:")
    print(rule_based_summary)
    print()
    print("Stored summary:")
    print(summary["summary"])
    print()
    print("Structured summary:")
    print(f"- main_topics: {structured_summary.get('main_topics') or []}")
    print(f"- user_goals: {structured_summary.get('user_goals') or []}")
    print(f"- decisions: {structured_summary.get('decisions') or []}")
    print(f"- open_questions: {structured_summary.get('open_questions') or []}")
    print(f"- constraints: {structured_summary.get('constraints') or []}")
    print()
    print("Manual checklist:")
    print("[ ] no_hallucinated_features")
    print("[ ] keeps_user_goal")
    print("[ ] keeps_constraints")
    print("[ ] keeps_open_questions")
    print("[ ] separates_memory_from_product_facts")
    print("[ ] concise_enough")
    print("[ ] safe_for_prompt_memory")
    print()


def _build_rule_based_summary(messages: list[dict[str, Any]]) -> str:
    user_messages = [
        str(message["content"]).strip()
        for message in messages
        if message["role"] == "user" and str(message["content"]).strip()
    ]
    user_text = "\n".join(user_messages)
    features = FeatureExtractor().extract(user_text)
    recent_user_intents = user_messages[-4:]
    topic = ", ".join(features) if features else "unknown"
    return (
        f"Основные темы диалога: {topic}. "
        f"Последние запросы пользователя: {' | '.join(recent_user_intents)}"
    ).strip()


def _compact(text_value: object, *, limit: int) -> str:
    compact = " ".join(str(text_value).split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


if __name__ == "__main__":
    asyncio.run(main())
