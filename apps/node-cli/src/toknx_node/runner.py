import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Protocol

import httpx
import websockets

from toknx_node.client import ToknXClient
from toknx_node.config import (
    PRODUCTION_API_BASE_URL,
    RuntimeState,
    StoredConfig,
    clear_runtime,
    save_runtime,
)


SendMessage = Callable[[dict], Awaitable[None]]


class InferenceBackend(Protocol):
    async def run_job(self, send_message: SendMessage, *, job_id: str, request_payload: dict) -> None:
        ...


@dataclass
class StartOptions:
    models: list[str]
    capability_mode: str = "solo"
    exo_port: int = 52415


@dataclass
class ExoInferenceBackend:
    exo_port: int

    async def run_job(self, send_message: SendMessage, *, job_id: str, request_payload: dict) -> None:
        await _run_exo_job(
            send_message,
            job_id=job_id,
            request_payload=request_payload,
            exo_port=self.exo_port,
        )


def discover_hardware() -> dict:
    page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    physical_pages = os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else 0
    ram_gb = int((page_size * physical_pages) / (1024**3)) if physical_pages else 16
    return {
        "chip": platform.processor() or platform.machine(),
        "ram_gb": max(ram_gb, 16),
        "platform": platform.platform(),
    }


def _find_exo_resources() -> str | None:
    cached_checkouts = Path.home() / ".cache" / "uv" / "git-v0" / "checkouts"
    if not cached_checkouts.exists():
        return None

    for resource_dir in cached_checkouts.glob("*/*/resources"):
        if (resource_dir / "inference_model_cards").is_dir():
            return str(resource_dir.resolve())
    return None


def _ensure_exo_dashboard_stub() -> str:
    dashboard_dir = Path.home() / ".toknx" / "exo-dashboard-stub"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    index_path = dashboard_dir / "index.html"
    if not index_path.exists():
        index_path.write_text(
            """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>exo dashboard stub</title>
  </head>
  <body>
    <p>exo dashboard stub</p>
  </body>
</html>
""",
            encoding="utf-8",
        )
    return str(dashboard_dir.resolve())


def _build_exo_env() -> dict[str, str]:
    env = os.environ.copy()
    (Path.home() / ".exo" / "models").mkdir(parents=True, exist_ok=True)
    if "EXO_RESOURCES_DIR" not in env:
        resource_dir = _find_exo_resources()
        if resource_dir is not None:
            env["EXO_RESOURCES_DIR"] = resource_dir
    if "EXO_DASHBOARD_DIR" not in env:
        env["EXO_DASHBOARD_DIR"] = _ensure_exo_dashboard_stub()
    return env


async def _send_node_message(websocket, send_lock: asyncio.Lock, payload: dict) -> None:
    async with send_lock:
        await websocket.send(json.dumps(payload))


async def _wait_for_exo_api(exo_port: int, exo_process: subprocess.Popen, timeout_seconds: float = 30.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_running_loop().time() < deadline:
            if exo_process.poll() is not None:
                raise RuntimeError(f"exo exited before becoming ready (exit code {exo_process.returncode})")
            try:
                response = await client.get(f"http://127.0.0.1:{exo_port}/v1/models")
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError(f"exo API did not become ready on port {exo_port}")


def _extract_instance_id(instance_payload: dict) -> str:
    for payload in instance_payload.values():
        if isinstance(payload, dict) and "instanceId" in payload:
            return str(payload["instanceId"])
    raise RuntimeError("exo instance preview did not include an instanceId")


async def _ensure_exo_instance(model_id: str, exo_port: int) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        preview_response = await client.get(
            f"http://127.0.0.1:{exo_port}/instance/previews",
            params={"model_id": model_id},
        )
        preview_response.raise_for_status()
        previews = preview_response.json().get("previews", [])
        selected = next(
            (
                preview
                for preview in previews
                if preview.get("error") is None and preview.get("instance") is not None
            ),
            None,
        )
        if selected is None:
            raise RuntimeError(f"exo could not find a valid placement for model {model_id}")

        instance_payload = selected["instance"]
        instance_id = _extract_instance_id(instance_payload)

        create_response = await client.post(
            f"http://127.0.0.1:{exo_port}/instance",
            json={"instance": instance_payload},
        )
        create_response.raise_for_status()

        deadline = asyncio.get_running_loop().time() + 30.0
        while asyncio.get_running_loop().time() < deadline:
            instance_response = await client.get(f"http://127.0.0.1:{exo_port}/instance/{instance_id}")
            if instance_response.is_success:
                return
            await asyncio.sleep(0.5)
    raise RuntimeError(f"exo instance for model {model_id} did not become ready")


async def _run_exo_job(send_message, *, job_id: str, request_payload: dict, exo_port: int) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{exo_port}/v1/chat/completions",
                json=request_payload | {"stream": True},
            ) as response:
                response.raise_for_status()
                output_tokens = 0
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        await send_message({"type": "completed", "job_id": job_id, "output_tokens": output_tokens})
                        return
                    event = json.loads(payload)
                    delta = event.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        output_tokens += 1
                        await send_message(
                            {
                                "type": "token",
                                "job_id": job_id,
                                "chunk": delta,
                                "output_tokens": output_tokens,
                            }
                        )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text
            with suppress(Exception):
                payload = exc.response.json()
                detail = payload.get("detail") or payload.get("error") or detail
            await send_message({"type": "failed", "job_id": job_id, "error": detail})
        except Exception as exc:
            await send_message({"type": "failed", "job_id": job_id, "error": str(exc)})


async def run_node(
    config: StoredConfig,
    options: StartOptions,
    *,
    backend: InferenceBackend | None = None,
) -> None:
    client = ToknXClient(
        api_base_url=PRODUCTION_API_BASE_URL,
        api_key=config.api_key,
        node_token=config.node_token,
    )
    registration = client.register_node(
        committed_models=options.models,
        hardware_spec=discover_hardware(),
        capability_mode=options.capability_mode,
    )
    save_runtime(
        RuntimeState(
            node_id=registration["node_id"],
            models=options.models,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    exo_binary = shutil.which("exo")
    if exo_binary is None:
        raise RuntimeError("exo is not installed")

    exo_process = subprocess.Popen(  # noqa: S603
        [exo_binary, "--api-port", str(options.exo_port)],
        env=_build_exo_env(),
        text=True,
    )
    await _wait_for_exo_api(options.exo_port, exo_process)
    for model_id in options.models:
        await _ensure_exo_instance(model_id, options.exo_port)
    if backend is None:
        backend = ExoInferenceBackend(exo_port=options.exo_port)

    shutdown = asyncio.Event()

    def _stop(*_: object) -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)

    ws_url = registration["tunnel_url"]
    backoff = 1

    try:
        while not shutdown.is_set():
            active_jobs: set[asyncio.Task] = set()
            try:
                async with websockets.connect(ws_url, max_size=None) as websocket:
                    backoff = 1
                    send_lock = asyncio.Lock()

                    async def send_message(payload: dict) -> None:
                        await _send_node_message(websocket, send_lock, payload)

                    async def handle_inference(job_id: str, request_payload: dict) -> None:
                        await send_message({"type": "accepted", "job_id": job_id})
                        await backend.run_job(send_message, job_id=job_id, request_payload=request_payload)

                    while not shutdown.is_set():
                        raw_message = await websocket.recv()
                        message = json.loads(raw_message)
                        message_type = message.get("type")
                        if message_type == "ping":
                            await send_message({"type": "pong", "node_id": registration["node_id"]})
                        elif message_type == "inference":
                            job_id = message.get("job_id")
                            request_payload = message.get("request")
                            if not job_id or request_payload is None:
                                continue
                            task = asyncio.create_task(handle_inference(job_id, request_payload))
                            active_jobs.add(task)
                            task.add_done_callback(active_jobs.discard)
            except Exception:
                for task in list(active_jobs):
                    task.cancel()
                if active_jobs:
                    await asyncio.gather(*active_jobs, return_exceptions=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        if exo_process is not None:
            exo_process.terminate()
        with suppress(Exception):
            client.deregister_node(registration["node_id"])
        clear_runtime()
