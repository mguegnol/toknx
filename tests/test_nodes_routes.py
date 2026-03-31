from urllib.parse import urlparse

import pytest
from sqlalchemy import select

from toknx_coordinator.api.routes import nodes as node_routes
from toknx_coordinator.db.models import CreditBalance, Stake


@pytest.mark.anyio
async def test_register_node_returns_explicit_tunnel_url(
    monkeypatch,
    db_session,
    account_factory,
):
    monkeypatch.setattr(node_routes.settings, "jwt_secret", "jwt-secret-with-sufficient-length")
    monkeypatch.setattr(node_routes.settings, "node_tunnel_public_base_url", "wss://nodes.toknx.dev")
    account = await account_factory(db_session, github_id="gh-1", github_username="alice")

    payload = node_routes.NodeRegisterRequest(
        committed_models=["mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"],
        hardware_spec={"chip": "M4", "ram_gb": 64},
        capability_mode="solo",
    )
    result = await node_routes.register_node(payload=payload, account=account, session=db_session)

    assert result["tunnel_url"].startswith("wss://nodes.toknx.dev/nodes/tunnel?token=")
    assert result["tunnel_token"] in result["tunnel_url"]


@pytest.mark.anyio
async def test_register_node_falls_back_to_public_base_url(monkeypatch, db_session, account_factory):
    monkeypatch.setattr(node_routes.settings, "jwt_secret", "jwt-secret-with-sufficient-length")
    monkeypatch.setattr(node_routes.settings, "node_tunnel_public_base_url", None)
    monkeypatch.setattr(node_routes.settings, "public_base_url", "https://toknx.example/api")
    account = await account_factory(db_session, github_id="gh-2", github_username="bob")

    payload = node_routes.NodeRegisterRequest(
        committed_models=["mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"],
        hardware_spec={"chip": "M4", "ram_gb": 64},
        capability_mode="solo",
    )
    result = await node_routes.register_node(payload=payload, account=account, session=db_session)

    parsed = urlparse(result["tunnel_url"])
    assert parsed.scheme == "wss"
    assert parsed.netloc == "toknx.example"
    assert parsed.path == "/nodes/tunnel"


@pytest.mark.anyio
async def test_register_node_locks_stake_against_account_balance(monkeypatch, db_session, account_factory):
    monkeypatch.setattr(node_routes.settings, "jwt_secret", "jwt-secret-with-sufficient-length")
    monkeypatch.setattr(node_routes.settings, "node_tunnel_public_base_url", "ws://localhost")
    account = await account_factory(db_session, github_id="gh-3", github_username="carol")

    payload = node_routes.NodeRegisterRequest(
        committed_models=["mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"],
        hardware_spec={"chip": "M4", "ram_gb": 64},
        capability_mode="solo",
    )
    result = await node_routes.register_node(payload=payload, account=account, session=db_session)

    balance = await db_session.get(CreditBalance, account.id)
    stake = (
        await db_session.execute(select(Stake).where(Stake.node_id == result["node_id"]))
    ).scalar_one()

    assert balance is not None
    assert balance.balance == node_routes.settings.coordinator_signup_bonus - node_routes.settings.node_stake_credits
    assert stake.status == "active"
    assert stake.amount == node_routes.settings.node_stake_credits
