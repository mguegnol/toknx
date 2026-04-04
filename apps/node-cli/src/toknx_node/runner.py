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
from typing import Awaitable, Callable, Protocol

import httpx
import websockets

from toknx_node.client import ToknXClient
from toknx_node.config import (
    RuntimeState,
    StoredConfig,
    clear_runtime,
    get_api_base_url,
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
    inference_port_base: int = 52415


@dataclass
class MlxLmInferenceBackend:
    model_ports: dict[str, int]

    async def run_job(self, send_message: SendMessage, *, job_id: str, request_payload: dict) -> None:
        model_id = str(request_payload.get("model") or "")
        port = self.model_ports.get(model_id)
        if port is None:
            await send_message({"type": "failed", "job_id": job_id, "error": f"model not loaded: {model_id}"})
            return
        await _run_mlx_lm_job(
            send_message,
            job_id=job_id,
            request_payload=request_payload,
            port=port,
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


def _build_model_ports(models: list[str], port_base: int) -> dict[str, int]:
    return {model_id: port_base + index for index, model_id in enumerate(models)}


def _find_mlx_lm_server_binary() -> str | None:
    for candidate in ("mlx_lm.server", "mlx_lm_server"):
        binary = shutil.which(candidate)
        if binary is not None:
            return binary
    return None


async def _send_node_message(websocket, send_lock: asyncio.Lock, payload: dict) -> None:
    async with send_lock:
        await websocket.send(json.dumps(payload))


async def _wait_for_mlx_lm_api(
    model_id: str,
    port: int,
    process: subprocess.Popen,
    timeout_seconds: float = 30.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_running_loop().time() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"mlx-lm server for {model_id} exited before becoming ready (exit code {process.returncode})"
                )
            try:
                response = await client.get(f"http://127.0.0.1:{port}/v1/models")
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError(f"mlx-lm API for {model_id} did not become ready on port {port}")


async def _run_mlx_lm_job(send_message, *, job_id: str, request_payload: dict, port: int) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{port}/v1/chat/completions",
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
    api_base_url = get_api_base_url()
    client = ToknXClient(
        api_base_url=api_base_url,
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

    server_processes: dict[str, subprocess.Popen] = {}
    try:
        mlx_lm_server = _find_mlx_lm_server_binary()
        if mlx_lm_server is None:
            raise RuntimeError("mlx-lm is not installed")

        model_ports = _build_model_ports(options.models, options.inference_port_base)
        for model_id, port in model_ports.items():
            process = subprocess.Popen(  # noqa: S603
                [mlx_lm_server, "--model", model_id, "--port", str(port)],
                text=True,
            )
            server_processes[model_id] = process
        for model_id, process in server_processes.items():
            await _wait_for_mlx_lm_api(model_id, model_ports[model_id], process)
        if backend is None:
            backend = MlxLmInferenceBackend(model_ports=model_ports)

        shutdown = asyncio.Event()

        def _stop(*_: object) -> None:
            shutdown.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, _stop)

        ws_url = registration["tunnel_url"]
        backoff = 1

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
        for process in server_processes.values():
            if process.poll() is None:
                process.terminate()
        with suppress(Exception):
            client.deregister_node(registration["node_id"])
        clear_runtime()
