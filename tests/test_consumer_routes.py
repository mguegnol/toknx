import asyncio

import pytest
from sqlalchemy import select

from toknx_coordinator.api.routes import consumer as consumer_routes
from toknx_coordinator.db.models import Job, Node
from toknx_coordinator.services.events import EventBus
from toknx_coordinator.services.job_router import TunnelManager


class DummyModel:
    credits_per_1k_tokens = 1


async def _never_find_node(*_args, **_kwargs):
    return None


async def _resolve_model(*_args, **_kwargs):
    return DummyModel()


async def _zero_inflight(*_args, **_kwargs):
    return 0


async def _zero_pending_count(*_args, **_kwargs):
    return 0


async def _fake_count_execute(*_args, **_kwargs):
    return None


async def _queued_job(execute_fn):
    return (await execute_fn(select(Job))).scalar_one()


async def _counting_execute(execute_fn, *args, **kwargs):
    statement = args[0]
    raw_columns = getattr(statement, "_raw_columns", ())
    if any("count" in str(column).lower() for column in raw_columns):
        class Result:
            def scalar_one(self):
                return 0

        return Result()
    return await execute_fn(*args, **kwargs)


@pytest.mark.anyio
async def test_create_chat_completion_excludes_none_fields_from_forwarded_request(
    monkeypatch,
    db_session,
    account_factory,
):
    account = await account_factory(db_session, github_id="gh-consumer-1", github_username="alice")
    payload = consumer_routes.ChatCompletionRequest(
        model="mlx-community/Llama-3.2-1B-Instruct-4bit",
        messages=[consumer_routes.Message(role="user", content="hi")],
        stream=False,
        temperature=None,
        max_tokens=None,
    )

    monkeypatch.setattr(consumer_routes, "_find_node", _never_find_node)
    monkeypatch.setattr(consumer_routes, "_active_jobs_for_account", _zero_inflight)
    monkeypatch.setattr(consumer_routes, "resolve_or_create_model", _resolve_model)
    original_execute = db_session.execute
    monkeypatch.setattr(
        db_session,
        "execute",
        lambda *args, **kwargs: _counting_execute(original_execute, *args, **kwargs),
    )

    response = await consumer_routes.create_chat_completion(
        payload=payload,
        account=account,
        session=db_session,
        tunnel_manager=TunnelManager(None, None),
        event_bus=EventBus(),
    )

    job = await _queued_job(original_execute)

    assert response.status_code == 503
    assert job.request_payload == {
        "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }


class FakeTunnelManager:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict] | None = None
        self.dispatched_request: dict | None = None

    def open_job_stream(self, job_id: str) -> asyncio.Queue[dict]:
        self.queue = asyncio.Queue()
        return self.queue

    def close_job_stream(self, job_id: str) -> None:
        return None

    async def dispatch(self, node_id: str, job: Job) -> None:
        self.dispatched_request = job.request_payload
        assert self.queue is not None
        await self.queue.put(
            {
                "type": "token",
                "job_id": job.id,
                "chunk": "hello",
                "output_tokens": 1,
            }
        )
        await self.queue.put(
            {
                "type": "completed",
                "job_id": job.id,
                "output_tokens": 1,
                "prompt_tokens": 7,
            }
        )


@pytest.mark.anyio
async def test_create_chat_completion_returns_prompt_tokens_in_usage(
    monkeypatch,
    db_session,
    account_factory,
):
    consumer = await account_factory(db_session, github_id="gh-consumer-2", github_username="alice")
    contributor = await account_factory(
        db_session,
        github_id="gh-contributor-1",
        github_username="bob",
        api_key="toknx_api_contributor",
        node_token="toknx_node_contributor",
    )
    node = Node(
        id="node-123",
        account_id=contributor.id,
        token_hash="node-hash",
        committed_models=["mlx-community/Llama-3.2-1B-Instruct-4bit"],
        hardware_spec={"chip": "M2", "ram_gb": 16},
        status="online",
        tunnel_connected=True,
    )
    db_session.add(node)
    await db_session.commit()

    payload = consumer_routes.ChatCompletionRequest(
        model="mlx-community/Llama-3.2-1B-Instruct-4bit",
        messages=[consumer_routes.Message(role="user", content="hi")],
        stream=False,
    )

    async def _find_node(*_args, **_kwargs):
        return node

    monkeypatch.setattr(consumer_routes, "_find_node", _find_node)
    monkeypatch.setattr(consumer_routes, "_active_jobs_for_account", _zero_inflight)
    monkeypatch.setattr(consumer_routes, "resolve_or_create_model", _resolve_model)
    original_execute = db_session.execute
    monkeypatch.setattr(
        db_session,
        "execute",
        lambda *args, **kwargs: _counting_execute(original_execute, *args, **kwargs),
    )

    event_bus = EventBus()
    stream = event_bus.subscribe()
    tunnel_manager = FakeTunnelManager()
    response = await consumer_routes.create_chat_completion(
        payload=payload,
        account=consumer,
        session=db_session,
        tunnel_manager=tunnel_manager,
        event_bus=event_bus,
    )

    job = await _queued_job(original_execute)
    events = [stream.get_nowait(), stream.get_nowait()]

    assert tunnel_manager.dispatched_request == {
        "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }
    assert response["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 1,
        "total_tokens": 8,
    }
    assert job.prompt_tokens == 7
    assert job.output_tokens == 1
    assert job.status == "completed"
    assert [event.event for event in events] == ["job_started", "job_completed"]
    assert events[0].payload == {
        "job_id": job.id,
        "node_id": "node-123",
        "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
    }
    assert events[1].payload == {
        "job_id": job.id,
        "node_id": "node-123",
        "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "output_tokens": 1,
    }
