from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from toknx_coordinator.api.routes import auth as auth_routes
from toknx_coordinator.db.models import Account
from toknx_coordinator.services.security import hash_token


@pytest.mark.anyio
async def test_github_auth_uses_configured_redirect_uri_for_github(monkeypatch):
    monkeypatch.setattr(auth_routes.settings, "auth_dev_bypass", False)
    monkeypatch.setattr(auth_routes.settings, "github_client_id", "github-client")
    monkeypatch.setattr(
        auth_routes.settings,
        "github_redirect_url",
        "https://toknx.example/auth/github/callback",
    )

    response = await auth_routes.github_auth(
        redirect_uri="https://evil.example/callback",
        state="state-123",
        username="alice",
    )

    parsed = urlparse(response.headers["location"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "github.com"
    assert params["redirect_uri"] == ["https://toknx.example/auth/github/callback"]
    assert "evil.example" not in response.headers["location"]


def test_oauth_state_round_trip_preserves_cli_redirect():
    auth_routes.settings.jwt_secret = "test-secret"

    encoded = auth_routes._encode_oauth_state(
        state="state-123",
        redirect_uri="http://127.0.0.1:8787/callback",
    )

    state, redirect_uri = auth_routes._decode_oauth_state(encoded)

    assert state == "state-123"
    assert redirect_uri == "http://127.0.0.1:8787/callback"


@pytest.mark.anyio
async def test_github_callback_reuses_node_token_across_relogin(monkeypatch, db_session):
    monkeypatch.setattr(auth_routes.settings, "jwt_secret", "stable-secret")

    first = await auth_routes.github_callback(code="dev:alice", session=db_session)
    second = await auth_routes.github_callback(code="dev:alice", session=db_session)

    assert first["github_username"] == "alice"
    assert second["github_username"] == "alice"
    assert second["node_token"] == first["node_token"]
    assert second["api_key"] != first["api_key"]

    account = (
        await db_session.execute(select(Account).where(Account.github_id == "dev-alice"))
    ).scalar_one()
    assert account.node_token_hash == hash_token(first["node_token"])
    assert account.api_key_hash == hash_token(second["api_key"])


@pytest.mark.anyio
async def test_github_callback_redirects_back_to_cli_callback(monkeypatch, db_session):
    monkeypatch.setattr(auth_routes.settings, "jwt_secret", "stable-secret")
    encoded_state = auth_routes._encode_oauth_state(
        state="state-123",
        redirect_uri="http://127.0.0.1:8787/callback",
    )

    response = await auth_routes.github_callback(
        code="dev:alice",
        state=encoded_state,
        session=db_session,
    )

    parsed = urlparse(response.headers["location"])
    params = parse_qs(parsed.query)

    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8787"
    assert parsed.path == "/callback"
    assert params["state"] == ["state-123"]
    assert params["github_username"] == ["alice"]
    assert "api_key" in params
    assert "node_token" in params
