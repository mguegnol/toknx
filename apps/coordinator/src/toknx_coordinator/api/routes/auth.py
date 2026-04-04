import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.api.deps import get_db_session
from toknx_coordinator.core.config import get_settings
from toknx_coordinator.db.models import Account
from toknx_coordinator.services.credits import ensure_credit_balance
from toknx_coordinator.services.security import derive_stable_token, generate_token, hash_token

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.get("/github")
async def github_auth(
    redirect_uri: str | None = Query(default=None),
    state: str | None = Query(default=None),
    username: str | None = Query(default=None),
):
    callback_params = {}
    if redirect_uri:
        callback_params["redirect_uri"] = redirect_uri
    if state:
        callback_params["state"] = state

    if settings.auth_dev_bypass:
        callback_params["code"] = f"dev:{username or 'localdev'}"
        return RedirectResponse(url=f"{settings.github_redirect_url}?{urlencode(callback_params)}")

    if not settings.github_client_id:
        raise HTTPException(status_code=500, detail="github oauth is not configured")

    github_state = state or secrets.token_urlsafe(24)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": str(settings.github_redirect_url),
        "scope": "read:user",
        "state": github_state,
    }
    return RedirectResponse(url=f"https://github.com/login/oauth/authorize?{urlencode(params)}")


@router.get("/github/callback")
async def github_callback(
    code: str,
    state: str | None = None,
    redirect_uri: str | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    if code.startswith("dev:"):
        github_username = code.split(":", maxsplit=1)[1]
        github_id = f"dev-{github_username}"
    else:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": str(settings.github_redirect_url),
                },
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
            user_response.raise_for_status()
            user = user_response.json()
            github_username = user["login"]
            github_id = str(user["id"])

    account = (
        await session.execute(select(Account).where(Account.github_id == github_id))
    ).scalar_one_or_none()

    api_key = generate_token("toknx_api")
    node_token = derive_stable_token("toknx_node", subject=github_id, secret=settings.jwt_secret)

    if account is None:
        account = Account(
            github_id=github_id,
            github_username=github_username,
            api_key_hash=hash_token(api_key),
            node_token_hash=hash_token(node_token),
        )
        session.add(account)
        await session.flush()
        await ensure_credit_balance(session, account)
    else:
        account.github_username = github_username
        account.api_key_hash = hash_token(api_key)
        account.node_token_hash = hash_token(node_token)

    await session.commit()

    payload = {
        "github_username": github_username,
        "api_key": api_key,
        "node_token": node_token,
    }
    if redirect_uri:
        return RedirectResponse(url=f"{redirect_uri}?{urlencode(payload | {'state': state or ''})}")
    return payload
