import os
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from google.protobuf.message import Message
from mireacrm_common import tracing
from mireacrm_common.db import create_engine, create_session_factory
from mireacrm_common.events import EventPublisher
from mireacrm_common.lifespan import AppContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import Settings

TEST_DSN = os.getenv(
    "ANALYTICS_TEST_POSTGRES_DSN",
    "postgresql+asyncpg://analytics_user:analytics_pass@localhost:5432/analytics_db_test",
)

_TABLES = (
    "appointment_facts",
    "invoice_facts",
    "consumable_facts",
    "client_facts",
    "processed_events",
)


class RecordingPublisher(EventPublisher):
    """Собирает опубликованное вместо отправки в брокер."""

    def __init__(self) -> None:
        super().__init__("", "analytics-service")
        self.published: list[tuple[str, Message]] = []
        self.envelopes: list[str] = []

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def ping(self, timeout: float = 2.0) -> bool:
        return True

    async def publish(self, routing_key: str, **payload: Message) -> None:
        self.published.append((routing_key, next(iter(payload.values()))))
        self.envelopes.append(tracing.current())

    def routing_keys(self) -> list[str]:
        return [key for key, _ in self.published]


@pytest.fixture(scope="session")
def migrated_database() -> str:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DSN)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return TEST_DSN


@pytest.fixture
def publisher() -> RecordingPublisher:
    return RecordingPublisher()


@pytest_asyncio.fixture
async def context(
    migrated_database: str, publisher: RecordingPublisher
) -> AsyncIterator[AppContext]:
    """Тот же AppContext, что в бою, но с движком на тестовой базе и без брокера."""
    engine = create_engine(migrated_database)
    yield AppContext(
        settings=Settings(postgres_dsn=migrated_database),
        engine=engine,
        sessions=create_session_factory(engine),
        publisher=publisher,
    )
    await engine.dispose()


@pytest_asyncio.fixture
async def session(context: AppContext) -> AsyncIterator[AsyncSession]:
    async with context.session() as db:
        yield db
        # Тесты коммитят, поэтому чистим таблицы, а не откатываем транзакцию.
        for table in _TABLES:
            await db.execute(text(f"TRUNCATE {table} CASCADE"))
        await db.commit()


@pytest_asyncio.fixture
async def api(context: AppContext) -> AsyncIterator[httpx.AsyncClient]:
    """Приложение целиком: проверки на границе HTTP доменными вызовами не видны."""
    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app(context))
    async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
        yield client
