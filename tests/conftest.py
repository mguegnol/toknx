from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from toknx_coordinator.db.base import Base
from toknx_coordinator.db.models import Account
from toknx_coordinator.services.security import hash_token


@pytest.fixture
async def session_factory(tmp_path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def account_factory() -> Callable[..., Awaitable[Account]]:
    async def _create_account(
        session: AsyncSession,
        *,
        github_id: str = "github-1",
        github_username: str = "alice",
        api_key: str = "toknx_api_test",
        node_token: str = "toknx_node_test",
        max_nodes: int = 5,
    ) -> Account:
        account = Account(
            github_id=github_id,
            github_username=github_username,
            api_key_hash=hash_token(api_key),
            node_token_hash=hash_token(node_token),
            max_nodes=max_nodes,
        )
        session.add(account)
        await session.commit()
        return account

    return _create_account
