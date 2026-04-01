from typer.testing import CliRunner

from toknx_node import cli
from toknx_node.config import PRODUCTION_API_BASE_URL, StoredConfig


runner = CliRunner()


def test_login_uses_fixed_production_coordinator(monkeypatch):
    captured: dict = {}

    def fake_login_via_browser(api_base_url: str, *, state: str) -> dict:
        captured["api_base_url"] = api_base_url
        captured["state"] = state
        return {
            "state": state,
            "github_username": "alice",
            "api_key": "toknx_api_test",
            "node_token": "toknx_node_test",
        }

    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda _length: "state-123")
    monkeypatch.setattr(cli, "login_via_browser", fake_login_via_browser)

    saved: dict = {}
    monkeypatch.setattr(cli, "save_config", lambda config: saved.setdefault("config", config))

    result = runner.invoke(cli.app, ["login"])

    assert result.exit_code == 0
    assert captured == {
        "api_base_url": PRODUCTION_API_BASE_URL,
        "state": "state-123",
    }
    assert saved["config"] == StoredConfig(
        github_username="alice",
        api_key="toknx_api_test",
        node_token="toknx_node_test",
    )


def test_login_rejects_removed_local_flags():
    result = runner.invoke(cli.app, ["login", "--api-base-url", "http://localhost/api"])

    assert result.exit_code != 0
    assert "No such option" in result.stdout


def test_start_rejects_removed_mock_flag():
    result = runner.invoke(
        cli.app,
        ["start", "--model", "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", "--mock-inference"],
    )

    assert result.exit_code != 0
    assert "No such option" in result.stdout


def test_start_rejects_removed_launch_exo_flag():
    result = runner.invoke(
        cli.app,
        ["start", "--model", "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", "--launch-exo"],
    )

    assert result.exit_code != 0
    assert "No such option" in result.stdout
