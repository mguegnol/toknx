from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.db.models import Account
from toknx_coordinator.db.session import get_session
from toknx_coordinator.services.security import hash_token


async def get_db_session(session: AsyncSession = Depends(get_session)) -> AsyncIterator[AsyncSession]:
    yield session


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization header")
    return token


async def get_api_account(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> Account:
    token = _bearer_token(authorization)
    account = (
        await session.execute(select(Account).where(Account.api_key_hash == hash_token(token)))
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
    return account


async def get_node_account(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> Account:
    token = _bearer_token(authorization)
    account = (
        await session.execute(select(Account).where(Account.node_token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid node token")
    return account


def get_tunnel_manager(request: Request):
    return request.app.state.tunnel_manager


def get_event_bus(request: Request):
    return request.app.state.event_bus

