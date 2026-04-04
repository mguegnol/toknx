import pytest
from sqlalchemy import select

from toknx_coordinator.api.routes import consumer as consumer_routes
from toknx_coordinator.db.models import Job
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
    statement_text = str(statement)
    if "count" in statement_text.lower():
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
    )

    job = await _queued_job(original_execute)

    assert response.status_code == 503
    assert job.request_payload == {
        "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }
