import asyncio
import os
import secrets
import signal
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import typer

from toknx_node.auth_flow import login_via_browser
from toknx_node.client import ToknXClient
from toknx_node.config import (
    CONFIG_DIR,
    DaemonState,
    StoredConfig,
    clear_daemon,
    clear_runtime,
    get_api_base_url,
    load_daemon,
    load_config,
    load_runtime,
    save_daemon,
    save_config,
)
from toknx_node.runner import StartOptions, run_node

app = typer.Typer(no_args_is_help=True)

DAEMON_LOG_PATH = CONFIG_DIR / "node.log"


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _tail_log(log_path: Path, lines: int = 20) -> str:
    if not log_path.exists():
        return ""
    content = log_path.read_text(errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _clear_registered_runtime(config: StoredConfig) -> None:
    runtime = load_runtime()
    if not runtime.node_id or not config.node_token:
        clear_runtime()
        return

    client = ToknXClient(get_api_base_url(), config.api_key, config.node_token)
    with suppress(Exception):
        client.deregister_node(runtime.node_id)
    clear_runtime()


def _load_live_daemon(config: StoredConfig | None = None) -> DaemonState:
    daemon = load_daemon()
    if daemon.pid and _is_process_running(daemon.pid):
        return daemon
    if daemon.pid:
        clear_daemon()
        if config is not None:
            _clear_registered_runtime(config)
    return DaemonState()


def _daemon_command(model: str, capability_mode: str, inference_port_base: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "toknx_node.cli",
        "run-daemon",
        "--model",
        model,
        "--capability-mode",
        capability_mode,
        "--inference-port-base",
        str(inference_port_base),
    ]


def _wait_for_exit(pid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _is_process_running(pid):
            return True
        time.sleep(0.1)
    return not _is_process_running(pid)


def _stop_local_daemon(daemon: DaemonState) -> bool:
    if not daemon.pid or not _is_process_running(daemon.pid):
        return True

    os.killpg(daemon.pid, signal.SIGTERM)
    if _wait_for_exit(daemon.pid, timeout_seconds=10):
        return True

    os.killpg(daemon.pid, signal.SIGKILL)
    return _wait_for_exit(daemon.pid, timeout_seconds=2)


@app.command()
def login() -> None:
    api_base_url = get_api_base_url()
    state = secrets.token_urlsafe(16)
    result = login_via_browser(api_base_url, state=state)
    if result.get("state") != state:
        raise typer.BadParameter("oauth state mismatch")
    config = StoredConfig(
        github_username=result["github_username"],
        api_key=result["api_key"],
        node_token=result["node_token"],
    )
    save_config(config)
    typer.echo(f"Logged in as @{config.github_username}")
    typer.echo(f"API key: {config.api_key}")


@app.command()
def start(
    model: str = typer.Option(..., help="Comma-separated Hugging Face model ids."),
    capability_mode: str = typer.Option("solo", help="Node capability mode."),
    inference_port_base: int = typer.Option(
        52415,
        "--inference-port-base",
        help="Base localhost port for mlx-lm servers.",
    ),
) -> None:
    config = load_config()
    if not config.api_key or not config.node_token:
        raise typer.BadParameter("run `toknx login` first")
    daemon = _load_live_daemon(config)
    if daemon.pid:
        typer.echo(f"ToknX node already running in background (pid {daemon.pid}).")
        raise typer.Exit(code=1)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with DAEMON_LOG_PATH.open("w") as log_file:
        process = subprocess.Popen(  # noqa: S603
            _daemon_command(model, capability_mode, inference_port_base),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=False,
        )

    models = [item.strip() for item in model.split(",") if item.strip()]
    save_daemon(
        DaemonState(
            pid=process.pid,
            log_path=str(DAEMON_LOG_PATH),
            models=models,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    time.sleep(1.0)
    if process.poll() is not None:
        clear_daemon()
        typer.echo(f"ToknX node failed to start. See log: {DAEMON_LOG_PATH}", err=True)
        log_tail = _tail_log(DAEMON_LOG_PATH)
        if log_tail:
            typer.echo(log_tail, err=True)
        raise typer.Exit(code=1)

    typer.echo(f"ToknX node started in background (pid {process.pid}).")
    typer.echo(f"Logs: {DAEMON_LOG_PATH}")


@app.command("run-daemon", hidden=True)
def run_daemon(
    model: str = typer.Option(..., help="Comma-separated Hugging Face model ids."),
    capability_mode: str = typer.Option("solo", help="Node capability mode."),
    inference_port_base: int = typer.Option(
        52415,
        "--inference-port-base",
        help="Base localhost port for mlx-lm servers.",
    ),
) -> None:
    config = load_config()
    if not config.api_key or not config.node_token:
        raise typer.BadParameter("run `toknx login` first")
    models = [item.strip() for item in model.split(",") if item.strip()]
    try:
        asyncio.run(
            run_node(
                config,
                StartOptions(
                    models=models,
                    capability_mode=capability_mode,
                    inference_port_base=inference_port_base,
                ),
            )
        )
    finally:
        clear_daemon()


@app.command()
def status() -> None:
    api_base_url = get_api_base_url()
    config = load_config()
    runtime = load_runtime()
    daemon = _load_live_daemon()
    typer.echo(f"Account: @{config.github_username or 'not logged in'}")
    if config.api_key and config.node_token:
        client = ToknXClient(api_base_url, config.api_key, config.node_token)
        try:
            balance = client.get_balance()
            typer.echo(f"Credits: {balance['balance']}")
        except Exception as exc:
            typer.echo(f"Credits: unavailable ({exc})")
    if daemon.pid:
        typer.echo(f"Process: running (pid {daemon.pid})")
        typer.echo(f"Logs: {daemon.log_path}")
    else:
        typer.echo("Process: offline")
    if runtime.node_id:
        typer.echo(f"Node: {runtime.node_id}")
        typer.echo(f"Models: {', '.join(runtime.models or [])}")
        typer.echo(f"Started: {runtime.started_at}")
    else:
        typer.echo("Node: offline")


@app.command()
def stop() -> None:
    api_base_url = get_api_base_url()
    config = load_config()
    daemon = _load_live_daemon()
    if daemon.pid:
        if _stop_local_daemon(daemon):
            typer.echo(f"Stopped background node process {daemon.pid}")
        else:
            typer.echo(f"Failed to stop background node process {daemon.pid}", err=True)
            raise typer.Exit(code=1)
    else:
        typer.echo("No background node process found.")

    runtime = load_runtime()
    if runtime.node_id and config.node_token:
        client = ToknXClient(api_base_url, config.api_key, config.node_token)
        try:
            client.deregister_node(runtime.node_id)
            typer.echo(f"Deregistered node {runtime.node_id}")
        except Exception as exc:
            typer.echo(f"Failed to deregister node: {exc}")

    clear_daemon()
    clear_runtime()


if __name__ == "__main__":
    app()
