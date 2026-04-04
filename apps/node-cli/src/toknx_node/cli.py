import asyncio
import secrets

import typer

from toknx_node.auth_flow import login_via_browser
from toknx_node.client import ToknXClient
from toknx_node.config import (
    StoredConfig,
    clear_runtime,
    get_api_base_url,
    load_config,
    load_runtime,
    save_config,
)
from toknx_node.runner import StartOptions, run_node

app = typer.Typer(no_args_is_help=True)


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
    models = [item.strip() for item in model.split(",") if item.strip()]
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


@app.command()
def status() -> None:
    api_base_url = get_api_base_url()
    config = load_config()
    runtime = load_runtime()
    typer.echo(f"Account: @{config.github_username or 'not logged in'}")
    if config.api_key and config.node_token:
        client = ToknXClient(api_base_url, config.api_key, config.node_token)
        try:
            balance = client.get_balance()
            typer.echo(f"Credits: {balance['balance']}")
        except Exception as exc:
            typer.echo(f"Credits: unavailable ({exc})")
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
    runtime = load_runtime()
    if runtime.node_id and config.node_token:
        client = ToknXClient(api_base_url, config.api_key, config.node_token)
        try:
            client.deregister_node(runtime.node_id)
            typer.echo(f"Deregistered node {runtime.node_id}")
        except Exception as exc:
            typer.echo(f"Failed to deregister node: {exc}")
    clear_runtime()


if __name__ == "__main__":
    app()
