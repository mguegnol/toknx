import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from toknx_coordinator.db.models import Job, Node
from toknx_coordinator.services.events import EventBus


@dataclass
class NodeConnection:
    node_id: str
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_jobs: set[str] = field(default_factory=set)
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TunnelManager:
    def __init__(self, event_bus: EventBus, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._connections: dict[str, NodeConnection] = {}
        self._job_streams: dict[str, asyncio.Queue[dict]] = {}
        self._event_bus = event_bus
        self._session_factory = session_factory

    async def connect(self, node_id: str, websocket: WebSocket) -> None:
        self._connections[node_id] = NodeConnection(node_id=node_id, websocket=websocket)
        async with self._session_factory() as session:
            node = await session.get(Node, node_id)
            if node:
                node.tunnel_connected = True
                node.status = "online"
                node.last_ping_at = datetime.now(timezone.utc)
                await session.commit()
                await self._event_bus.publish(
                    "node_online",
                    {
                        "node_id": node.id,
                        "hardware": node.hardware_spec,
                        "models": node.committed_models,
                    },
                )

    async def disconnect(self, node_id: str) -> None:
        connection = self._connections.pop(node_id, None)
        if connection is None:
            return
        for job_id in list(connection.pending_jobs):
            await self.push_job_event(job_id, {"type": "failed", "job_id": job_id, "error": "node disconnected"})
        async with self._session_factory() as session:
            node = await session.get(Node, node_id)
            if node:
                node.tunnel_connected = False
                node.status = "offline"
                await session.commit()
                await self._event_bus.publish(
                    "node_offline",
                    {
                        "node_id": node.id,
                        "hardware": node.hardware_spec,
                        "models": node.committed_models,
                    },
                )

    async def mark_seen(self, node_id: str) -> None:
        connection = self._connections.get(node_id)
        if connection:
            connection.last_seen = datetime.now(timezone.utc)

    def is_connected(self, node_id: str) -> bool:
        return node_id in self._connections

    def open_job_stream(self, job_id: str) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._job_streams[job_id] = queue
        return queue

    def close_job_stream(self, job_id: str) -> None:
        self._job_streams.pop(job_id, None)
        for connection in self._connections.values():
            connection.pending_jobs.discard(job_id)

    async def push_job_event(self, job_id: str, payload: dict) -> None:
        queue = self._job_streams.get(job_id)
        if queue:
            await queue.put(payload)

    async def dispatch(self, node_id: str, job: Job) -> None:
        connection = self._connections.get(node_id)
        if connection is None:
            raise RuntimeError(f"node {node_id} disconnected before dispatch")
        payload = {
            "type": "inference",
            "job_id": job.id,
            "model": job.model,
            "request": job.request_payload,
        }
        async with connection.send_lock:
            await connection.websocket.send_text(json.dumps(payload))
        connection.pending_jobs.add(job.id)

    async def handle_node_message(self, node_id: str, message: dict) -> None:
        await self.mark_seen(node_id)
        event_type = message.get("type")
        if event_type in {"token", "completed", "failed", "accepted"}:
            job_id = message.get("job_id")
            if job_id:
                await self.push_job_event(job_id, message)

    async def find_matching_node(self, session: AsyncSession, model_id: str) -> Node | None:
        connected_node_ids = list(self._connections)
        if not connected_node_ids:
            return None
        nodes = (
            await session.execute(
                select(Node)
                .where(Node.status == "online", Node.id.in_(connected_node_ids))
                .order_by(Node.last_ping_at.desc())
            )
        ).scalars()
        for node in nodes:
            if model_id in node.committed_models:
                return node
        return None
