import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.api.deps import get_api_account, get_db_session, get_tunnel_manager
from toknx_coordinator.core.config import get_settings
from toknx_coordinator.db.models import Account, CreditBalance, Job, Node
from toknx_coordinator.services.credit_units import credits_to_subcredits
from toknx_coordinator.services.credits import ensure_credit_balance, settle_job
from toknx_coordinator.services.events import EventBus
from toknx_coordinator.services.job_router import TunnelManager
from toknx_coordinator.services.model_registry import resolve_or_create_model

router = APIRouter(prefix="/v1", tags=["consumer"])
settings = get_settings()


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = True
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = None


async def _active_jobs_for_account(session: AsyncSession, account_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.account_id == account_id, Job.status.in_(["queued", "pending", "running"]))
        )
    ).scalar_one()


async def _find_node(
    session: AsyncSession,
    tunnel_manager: TunnelManager,
    model_id: str,
    timeout_seconds: int,
) -> Node | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        node = await tunnel_manager.find_matching_node(session, model_id)
        if node:
            return node
        await asyncio.sleep(0.5)
    return None


@router.post("/chat/completions")
async def create_chat_completion(
    payload: ChatCompletionRequest,
    account: Account = Depends(get_api_account),
    session: AsyncSession = Depends(get_db_session),
    tunnel_manager: TunnelManager = Depends(get_tunnel_manager),
):
    inflight = await _active_jobs_for_account(session, account.id)
    if inflight >= settings.account_inflight_limit:
        raise HTTPException(status_code=429, detail="too many in-flight jobs")

    pending_for_model = (
        await session.execute(
            select(func.count()).select_from(Job).where(Job.model == payload.model, Job.status == "queued")
        )
    ).scalar_one()
    if pending_for_model >= settings.model_queue_cap:
        raise HTTPException(status_code=429, detail="model queue is full")

    balance = await ensure_credit_balance(session, account)
    model = await resolve_or_create_model(session, payload.model)
    if balance.balance < credits_to_subcredits(model.credits_per_1k_tokens):
        raise HTTPException(status_code=402, detail="insufficient credits")
    job = Job(
        account_id=account.id,
        model=payload.model,
        request_payload=payload.model_dump(mode="json", exclude_none=True),
        status="queued",
    )
    session.add(job)
    await session.commit()

    node = await _find_node(session, tunnel_manager, payload.model, settings.queue_timeout_seconds)
    if node is None:
        job.status = "timeout"
        await session.commit()
        return JSONResponse(
            status_code=503,
            content={"detail": "no nodes currently available", "retry_after": 10},
            headers={"Retry-After": "10"},
        )

    job.node_id = node.id
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await session.commit()

    stream = tunnel_manager.open_job_stream(job.id)
    try:
        await tunnel_manager.dispatch(node.id, job)
    except Exception as exc:
        tunnel_manager.close_job_stream(job.id)
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=503, detail="selected node became unavailable") from exc

    async def _finalize(output_tokens: int, prompt_tokens: int = 0) -> None:
        refreshed_job = await session.get(Job, job.id)
        refreshed_node = await session.get(Node, node.id)
        if refreshed_job is None or refreshed_node is None:
            return
        refreshed_job.output_tokens = output_tokens
        if prompt_tokens > 0:
            refreshed_job.prompt_tokens = prompt_tokens
        refreshed_job.completed_at = datetime.now(timezone.utc)
        contributor_account = await session.get(Account, refreshed_node.account_id)
        if contributor_account:
            await ensure_credit_balance(session, contributor_account)
            await settle_job(
                session,
                job=refreshed_job,
                credits_per_1k=model.credits_per_1k_tokens,
                contributor_account_id=contributor_account.id,
            )
        refreshed_job.status = "completed"
        await session.commit()

    async def stream_response():
        output_tokens = 0
        fragments: list[str] = []
        try:
            try:
                while True:
                    message = await asyncio.wait_for(stream.get(), timeout=settings.queue_timeout_seconds)
                    event_type = message["type"]
                    if event_type == "token":
                        chunk = message.get("chunk", "")
                        output_tokens = int(message.get("output_tokens", output_tokens))
                        fragments.append(chunk)
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]})}\n\n"
                    elif event_type == "completed":
                        output_tokens = int(message.get("output_tokens", output_tokens))
                        prompt_tokens = int(message.get("prompt_tokens", 0))
                        await _finalize(output_tokens, prompt_tokens)
                        yield "data: [DONE]\n\n"
                        break
                    elif event_type == "failed":
                        refreshed_job = await session.get(Job, job.id)
                        if refreshed_job:
                            refreshed_job.status = "failed"
                            refreshed_job.completed_at = datetime.now(timezone.utc)
                            await session.commit()
                        yield f"data: {json.dumps({'error': message.get('error', 'job failed')})}\n\n"
                        break
            except TimeoutError:
                refreshed_job = await session.get(Job, job.id)
                if refreshed_job:
                    refreshed_job.status = "failed"
                    refreshed_job.completed_at = datetime.now(timezone.utc)
                    await session.commit()
                yield f"data: {json.dumps({'error': 'job timed out waiting for node output'})}\n\n"
        finally:
            tunnel_manager.close_job_stream(job.id)

    if payload.stream:
        return StreamingResponse(stream_response(), media_type="text/event-stream")

    output_tokens = 0
    prompt_tokens = 0
    fragments: list[str] = []
    try:
        try:
            while True:
                message = await asyncio.wait_for(stream.get(), timeout=settings.queue_timeout_seconds)
                event_type = message["type"]
                if event_type == "token":
                    fragments.append(message.get("chunk", ""))
                    output_tokens = int(message.get("output_tokens", output_tokens))
                elif event_type == "completed":
                    output_tokens = int(message.get("output_tokens", output_tokens))
                    prompt_tokens = int(message.get("prompt_tokens", 0))
                    await _finalize(output_tokens, prompt_tokens)
                    break
                elif event_type == "failed":
                    job.status = "failed"
                    job.completed_at = datetime.now(timezone.utc)
                    await session.commit()
                    raise HTTPException(status_code=502, detail=message.get("error", "job failed"))
        except TimeoutError as exc:
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            raise HTTPException(status_code=504, detail="job timed out waiting for node output") from exc
    finally:
        tunnel_manager.close_job_stream(job.id)

    return {
        "id": job.id,
        "object": "chat.completion",
        "model": payload.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "".join(fragments),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
        },
    }
