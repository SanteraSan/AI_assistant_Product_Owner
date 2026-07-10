import asyncio

from app.db.session import init_db


class ExplodingEngine:
    def begin(self) -> None:
        raise AssertionError("engine.begin should not be called")


def test_init_db_skips_create_all_when_auto_create_disabled() -> None:
    asyncio.run(init_db(ExplodingEngine(), auto_create=False))  # type: ignore[arg-type]
