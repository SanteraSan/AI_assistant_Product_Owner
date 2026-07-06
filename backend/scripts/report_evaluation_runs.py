import argparse
import asyncio
from collections import defaultdict
from statistics import mean
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine, database_available


async def main() -> None:
    args = _parse_args()
    settings = get_settings()
    engine = create_engine(settings.postgres_dsn)
    try:
        if not await database_available(engine):
            raise RuntimeError("PostgreSQL is not available. Start docker compose first.")

        async with engine.connect() as connection:
            if args.command == "list":
                rows = await _fetch_runs(connection, args.limit)
                _print_runs(rows)
            elif args.command == "summary":
                run_id = args.run_id or await _fetch_latest_run_id(connection)
                if run_id is None:
                    print("No evaluation runs found.")
                    return
                run = await _fetch_run(connection, run_id)
                results = await _fetch_results(connection, run_id)
                _print_summary(run, results)
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report persisted RAG evaluations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Show recent evaluation runs.")
    list_parser.add_argument("--limit", type=int, default=10)

    summary_parser = subparsers.add_parser("summary", help="Summarize one evaluation run.")
    summary_parser.add_argument("--run-id", default=None)

    return parser.parse_args()


async def _fetch_runs(connection: Any, limit: int) -> list[dict[str, Any]]:
    result = await connection.execute(
        text(
            """
            select id, name, status, models, scenario_count, started_at, completed_at
            from evaluation_runs
            order by started_at desc
            limit :limit
            """
        ),
        {"limit": limit},
    )
    return [dict(row) for row in result.mappings()]


async def _fetch_latest_run_id(connection: Any) -> str | None:
    result = await connection.execute(
        text("select id from evaluation_runs order by started_at desc limit 1")
    )
    row = result.mappings().first()
    if row is None:
        return None
    return str(row["id"])


async def _fetch_run(connection: Any, run_id: str) -> dict[str, Any]:
    result = await connection.execute(
        text(
            """
            select id, name, status, models, scenario_count, started_at, completed_at
            from evaluation_runs
            where id = :run_id
            """
        ),
        {"run_id": run_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(f"Evaluation run not found: {run_id}")
    return dict(row)


async def _fetch_results(connection: Any, run_id: str) -> list[dict[str, Any]]:
    result = await connection.execute(
        text(
            """
            select scenario_id, model, latency_ms, source_count, quality_flags, error
            from evaluation_results
            where run_id = :run_id
            order by scenario_id, model
            """
        ),
        {"run_id": run_id},
    )
    return [dict(row) for row in result.mappings()]


def _print_runs(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No evaluation runs found.")
        return

    print("Recent evaluation runs:")
    for row in rows:
        models = ", ".join(row["models"] or [])
        print(
            f"- {row['id']} | {row['status']} | scenarios={row['scenario_count']} | "
            f"models=[{models}] | {row['name']}"
        )


def _print_summary(run: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print(f"Evaluation run: {run['id']}")
    print(f"Name: {run['name']}")
    print(f"Status: {run['status']}")
    print(f"Models: {', '.join(run['models'] or [])}")
    print(f"Scenarios declared: {run['scenario_count']}")
    print(f"Results stored: {len(results)}")
    print()

    if not results:
        print("No results stored for this run.")
        return

    _print_model_summary(results)
    print()
    _print_scenario_summary(results)
    print()
    _print_flag_failures(results)


def _print_model_summary(results: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[row["model"]].append(row)

    print("By model:")
    for model, rows in sorted(grouped.items()):
        latencies = [
            row["latency_ms"]
            for row in rows
            if row["latency_ms"] is not None
        ]
        source_counts = [row["source_count"] or 0 for row in rows]
        error_count = sum(1 for row in rows if row["error"])
        failed_flag_count = sum(_count_failed_flags(row["quality_flags"] or {}) for row in rows)
        avg_latency = int(mean(latencies)) if latencies else None
        avg_sources = round(mean(source_counts), 2) if source_counts else 0
        print(
            f"- {model}: results={len(rows)}, avg_latency_ms={avg_latency}, "
            f"avg_sources={avg_sources}, errors={error_count}, failed_flags={failed_flag_count}"
        )


def _print_scenario_summary(results: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[row["scenario_id"]].append(row)

    print("By scenario:")
    for scenario_id, rows in sorted(grouped.items()):
        error_count = sum(1 for row in rows if row["error"])
        zero_source_count = sum(1 for row in rows if (row["source_count"] or 0) == 0)
        failed_flag_count = sum(_count_failed_flags(row["quality_flags"] or {}) for row in rows)
        print(
            f"- {scenario_id}: results={len(rows)}, zero_sources={zero_source_count}, "
            f"errors={error_count}, failed_flags={failed_flag_count}"
        )


def _print_flag_failures(results: list[dict[str, Any]]) -> None:
    failures = []
    for row in results:
        quality_flags = row["quality_flags"] or {}
        failed_flags = [
            key
            for key, value in quality_flags.items()
            if isinstance(value, bool) and value is False
        ]
        if row["error"]:
            failed_flags.append("error")
        if failed_flags:
            failures.append((row["scenario_id"], row["model"], failed_flags))

    print("Flag failures:")
    if not failures:
        print("- none")
        return

    for scenario_id, model, failed_flags in failures:
        print(f"- {scenario_id} | {model}: {', '.join(failed_flags)}")


def _count_failed_flags(quality_flags: dict[str, Any]) -> int:
    return sum(
        1
        for value in quality_flags.values()
        if isinstance(value, bool) and value is False
    )


if __name__ == "__main__":
    asyncio.run(main())
