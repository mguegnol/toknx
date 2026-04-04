import base64
import hashlib
import hmac
import json
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


def _encode_oauth_state(*, state: str | None, redirect_uri: str | None) -> str:
    payload = {"state": state or "", "redirect_uri": redirect_uri or ""}
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def _decode_oauth_state(raw_state: str | None) -> tuple[str | None, str | None]:
    if not raw_state or "." not in raw_state:
        return raw_state, None

    payload_b64, signature = raw_state.rsplit(".", 1)
    expected_signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return raw_state, None

    try:
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception:
        return raw_state, None

    state = payload.get("state") or None
    redirect_uri = payload.get("redirect_uri") or None
    return state, redirect_uri


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

    github_state = _encode_oauth_state(
        state=state or secrets.token_urlsafe(24),
        redirect_uri=redirect_uri,
    )
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
    state, encoded_redirect_uri = _decode_oauth_state(state)
    redirect_uri = redirect_uri or encoded_redirect_uri

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
