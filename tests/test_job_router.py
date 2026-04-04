import asyncio
import json

import pytest

from toknx_coordinator.db.models import Job
from toknx_coordinator.services.events import EventBus
from toknx_coordinator.services.job_router import NodeConnection, TunnelManager


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.messages.append(payload)


@pytest.mark.anyio
async def test_dispatch_raises_when_node_disconnected():
    manager = TunnelManager(EventBus(), None)
    job = Job(id="job-1", account_id="acct-1", model="model-1", request_payload={"prompt": "hi"})

    with pytest.raises(RuntimeError, match="disconnected before dispatch"):
        await manager.dispatch("missing-node", job)


@pytest.mark.anyio
async def test_dispatch_sends_payload_and_tracks_pending_job():
    manager = TunnelManager(EventBus(), None)
    websocket = DummyWebSocket()
    manager._connections["node-1"] = NodeConnection(node_id="node-1", websocket=websocket)
    job = Job(id="job-1", account_id="acct-1", model="model-1", request_payload={"prompt": "hi"})

    await manager.dispatch("node-1", job)

    assert "job-1" in manager._connections["node-1"].pending_jobs
    assert json.loads(websocket.messages[0]) == {
        "type": "inference",
        "job_id": "job-1",
        "model": "model-1",
        "request": {"prompt": "hi"},
    }


@pytest.mark.anyio
async def test_handle_node_message_ignores_event_without_job_id():
    manager = TunnelManager(EventBus(), None)
    stream = manager.open_job_stream("job-1")

    await manager.handle_node_message("node-1", {"type": "token", "chunk": "hello"})

    with pytest.raises(asyncio.QueueEmpty):
        stream.get_nowait()
