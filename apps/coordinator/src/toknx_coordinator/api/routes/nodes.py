import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.api.deps import get_db_session, get_node_account, get_tunnel_manager
from toknx_coordinator.core.config import get_settings
from toknx_coordinator.db.models import Account, Node, Stake
from toknx_coordinator.services.credit_units import credits_to_subcredits
from toknx_coordinator.services.credits import lock_stake, refund_stake
from toknx_coordinator.services.job_router import TunnelManager
from toknx_coordinator.services.model_registry import resolve_or_create_model
from toknx_coordinator.services.security import decode_node_jwt, generate_token, hash_token, issue_node_jwt

router = APIRouter(prefix="/nodes", tags=["nodes"])
settings = get_settings()


def _derive_tunnel_base_url() -> str:
    if settings.node_tunnel_public_base_url:
        return str(settings.node_tunnel_public_base_url).rstrip("/")
    parsed = urlparse(str(settings.public_base_url))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}"


class NodeRegisterRequest(BaseModel):
    committed_models: list[str] = Field(min_length=1)
    hardware_spec: dict
    capability_mode: str = "solo"


@router.post("/register")
async def register_node(
    payload: NodeRegisterRequest,
    account: Account = Depends(get_node_account),
    session: AsyncSession = Depends(get_db_session),
):
    node_count = (
        await session.execute(
            select(func.count())
            .select_from(Node)
            .where(Node.account_id == account.id, Node.status != "deregistered")
        )
    ).scalar_one()
    if node_count >= account.max_nodes:
        raise HTTPException(status_code=400, detail="account has reached max nodes")

    total_ram = float(payload.hardware_spec.get("ram_gb", 0))
    required_ram = 0.0
    for model_id in payload.committed_models:
        model = await resolve_or_create_model(session, model_id)
        required_ram += model.estimated_ram_gb
    if required_ram > total_ram:
        raise HTTPException(status_code=400, detail="declared models exceed node ram budget")

    node_secret = generate_token("toknx_node_secret")
    node = Node(
        account_id=account.id,
        token_hash=hash_token(node_secret),
        committed_models=payload.committed_models,
        hardware_spec=payload.hardware_spec | {"capability_mode": payload.capability_mode},
        status="starting",
        stake_balance=credits_to_subcredits(settings.node_stake_credits),
    )
    session.add(node)
    await session.flush()
    try:
        await lock_stake(session, account, node_id=node.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tunnel_token = issue_node_jwt(node_id=node.id, account_id=account.id, secret=settings.jwt_secret)
    await session.commit()
    return {
        "node_id": node.id,
        "tunnel_token": tunnel_token,
        "tunnel_url": f"{_derive_tunnel_base_url()}/nodes/tunnel?token={tunnel_token}",
        "node_secret": node_secret,
        "models": payload.committed_models,
    }


@router.post("/{node_id}/deregister")
async def deregister_node(
    node_id: str,
    account: Account = Depends(get_node_account),
    session: AsyncSession = Depends(get_db_session),
):
    node = await session.get(Node, node_id)
    if node is None or node.account_id != account.id:
        raise HTTPException(status_code=404, detail="node not found")

    stake = (
        await session.execute(
            select(Stake).where(Stake.node_id == node.id, Stake.account_id == account.id, Stake.status == "active")
        )
    ).scalar_one_or_none()
    if stake:
        await refund_stake(session, stake)

    node.status = "deregistered"
    node.tunnel_connected = False
    node.stake_balance = 0
    node.last_ping_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "deregistered", "node_id": node_id}


async def _keepalive(websocket: WebSocket, node_id: str) -> None:
    while True:
        await asyncio.sleep(settings.node_keepalive_seconds)
        await websocket.send_text(json.dumps({"type": "ping", "node_id": node_id}))


@router.websocket("/tunnel")
async def node_tunnel(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = decode_node_jwt(token, settings.jwt_secret)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    node_id = str(payload["sub"])
    async with websocket.app.state.session_factory() as session:
        node = await session.get(Node, node_id)
        if node is None or node.status == "deregistered":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()
    tunnel_manager: TunnelManager = websocket.app.state.tunnel_manager
    await tunnel_manager.connect(node_id, websocket)
    keepalive_task = asyncio.create_task(_keepalive(websocket, node_id))

    try:
        while True:
            raw_message = await websocket.receive_text()
            message = json.loads(raw_message)
            if message.get("type") == "pong":
                async with websocket.app.state.session_factory() as session:
                    node = await session.get(Node, node_id)
                    if node:
                        node.last_ping_at = datetime.now(timezone.utc)
                        await session.commit()
            await tunnel_manager.handle_node_message(node_id, message)
    except WebSocketDisconnect:
        pass
    finally:
        keepalive_task.cancel()
        await tunnel_manager.disconnect(node_id)
