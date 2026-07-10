from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from time import perf_counter
from uuid import uuid4

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local HTTP burst smoke test against the backend."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/chat")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--message", default="Ответь одним коротким предложением: ok.")
    parser.add_argument("--model", default=None)
    return parser.parse_args()


async def _send_one(
    *,
    client: httpx.AsyncClient,
    url: str,
    message: str,
    model: str | None,
    semaphore: asyncio.Semaphore,
) -> int | str:
    payload: dict[str, str] = {"message": message}
    if model:
        payload["model"] = model
    async with semaphore:
        try:
            response = await client.post(
                url,
                json=payload,
                headers={"X-Request-ID": f"burst-{uuid4()}"},
            )
            return response.status_code
        except httpx.HTTPError as exc:
            return type(exc).__name__


async def run_burst(args: argparse.Namespace) -> None:
    started_at = perf_counter()
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
        results = await asyncio.gather(
            *[
                _send_one(
                    client=client,
                    url=args.url,
                    message=args.message,
                    model=args.model,
                    semaphore=semaphore,
                )
                for _ in range(args.requests)
            ]
        )

    elapsed_ms = int((perf_counter() - started_at) * 1000)
    counts = Counter(results)
    print(f"requests={args.requests}")
    print(f"concurrency={args.concurrency}")
    print(f"elapsed_ms={elapsed_ms}")
    print(
        "status_counts="
        + ",".join(
            f"{key}:{value}" for key, value in sorted(counts.items(), key=lambda item: str(item[0]))
        )
    )


def main() -> None:
    asyncio.run(run_burst(parse_args()))


if __name__ == "__main__":
    main()
