import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.api.deps import get_db_session, get_event_bus
from toknx_coordinator.db.models import Account, CreditTransaction, Job, Node
from toknx_coordinator.services.events import EventBus
from toknx_coordinator.services.model_registry import list_live_models

router = APIRouter(tags=["public"])

nodes_online_gauge = Gauge("toknx_nodes_online", "Count of online ToknX nodes")
jobs_running_gauge = Gauge("toknx_jobs_running", "Count of running ToknX jobs")
tokens_total_gauge = Gauge("toknx_tokens_generated_total", "Total generated output tokens")
tokens_per_second_gauge = Gauge("toknx_tokens_per_second", "Observed network output throughput")


@router.get("/healthz")
async def healthcheck():
    return {"status": "ok"}


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_db_session)):
    nodes_online = (
        await session.execute(select(func.count()).select_from(Node).where(Node.status == "online"))
    ).scalar_one()
    jobs_running = (
        await session.execute(select(func.count()).select_from(Job).where(Job.status == "running"))
    ).scalar_one()
    tokens_total = (
        await session.execute(select(func.coalesce(func.sum(Job.output_tokens), 0)).select_from(Job))
    ).scalar_one()
    window = datetime.now(timezone.utc) - timedelta(minutes=5)
    recent_jobs = (
        await session.execute(
            select(Job).where(Job.completed_at.is_not(None), Job.completed_at >= window)
        )
    ).scalars()
    total_recent_tokens = 0
    total_recent_seconds = 0.0
    for job in recent_jobs:
        if job.started_at and job.completed_at:
            total_recent_tokens += job.output_tokens
            total_recent_seconds += max((job.completed_at - job.started_at).total_seconds(), 1.0)
    tokens_per_second = round(total_recent_tokens / total_recent_seconds, 2) if total_recent_seconds else 0.0
    nodes_online_gauge.set(nodes_online)
    jobs_running_gauge.set(jobs_running)
    tokens_total_gauge.set(tokens_total)
    tokens_per_second_gauge.set(tokens_per_second)
    return {
        "nodes_online": nodes_online,
        "jobs_running": jobs_running,
        "tokens_total": tokens_total,
        "tokens_per_second": tokens_per_second,
    }


@router.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_db_session)):
    await stats(session)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/leaderboard")
async def leaderboard(session: AsyncSession = Depends(get_db_session)):
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        await session.execute(
            select(
                Account.github_username,
                func.coalesce(func.sum(CreditTransaction.amount), 0).label("credits_earned"),
            )
            .join(Account, Account.id == CreditTransaction.account_id)
            .where(
                CreditTransaction.tx_type == "job_earned",
                CreditTransaction.created_at >= week_ago,
            )
            .group_by(Account.github_username)
            .order_by(func.sum(CreditTransaction.amount).desc())
            .limit(10)
        )
    ).all()
    return {
        "leaders": [
            {
                "github_username": row.github_username,
                "credits_earned": int(row.credits_earned),
            }
            for row in rows
        ]
    }


@router.get("/events/stream")
async def event_stream(event_bus: EventBus = Depends(get_event_bus)):
    queue = event_bus.subscribe()

    async def generate():
        try:
            while True:
                message = await queue.get()
                payload = {
                    "type": message.event,
                    "created_at": message.created_at,
                    **message.payload,
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/v1/models")
async def live_models(session: AsyncSession = Depends(get_db_session)):
    models = await list_live_models(session)
    nodes = (await session.execute(select(Node).where(Node.status == "online"))).scalars().all()
    counts: dict[str, int] = {}
    for node in nodes:
        for model_id in node.committed_models:
            counts[model_id] = counts.get(model_id, 0) + 1
    return {
        "models": [
            {
                **model,
                "node_count": counts.get(model["hf_id"], 0),
            }
            for model in models
            if counts.get(model["hf_id"], 0) > 0
        ]
    }
