from pathlib import Path

from typer.testing import CliRunner

from toknx_node import cli
from toknx_node.config import DaemonState, PRODUCTION_API_BASE_URL, RuntimeState, StoredConfig


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
    assert "Logged in as @alice" in result.stdout
    assert "API key: toknx_api_test" in result.stdout
    assert saved["config"] == StoredConfig(
        github_username="alice",
        api_key="toknx_api_test",
        node_token="toknx_node_test",
    )


def test_login_allows_env_override_for_local_coordinator(monkeypatch):
    captured: dict = {}

    def fake_login_via_browser(api_base_url: str, *, state: str) -> dict:
        captured["api_base_url"] = api_base_url
        return {
            "state": state,
            "github_username": "alice",
            "api_key": "toknx_api_test",
            "node_token": "toknx_node_test",
        }

    monkeypatch.setenv("TOKNX_API_BASE_URL", "http://localhost/api")
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda _length: "state-123")
    monkeypatch.setattr(cli, "login_via_browser", fake_login_via_browser)
    monkeypatch.setattr(cli, "save_config", lambda config: config)

    result = runner.invoke(cli.app, ["login"])

    assert result.exit_code == 0
    assert captured["api_base_url"] == "http://localhost/api"
    assert "API key: toknx_api_test" in result.stdout


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


def test_start_launches_background_daemon(monkeypatch, tmp_path):
    log_path = tmp_path / "node.log"
    captured: dict = {}

    class FakeProcess:
        pid = 321

        @staticmethod
        def poll():
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    saved: dict = {}
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: StoredConfig(github_username="alice", api_key="toknx_api_test", node_token="toknx_node_test"),
    )
    monkeypatch.setattr(cli, "_load_live_daemon", lambda _config=None: DaemonState())
    monkeypatch.setattr(cli, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cli, "DAEMON_LOG_PATH", log_path)
    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(cli, "save_daemon", lambda daemon: saved.setdefault("daemon", daemon))

    result = runner.invoke(
        cli.app,
        [
            "start",
            "--model",
            "mlx-community/Llama-3.2-1B-Instruct-4bit",
        ],
    )

    assert result.exit_code == 0
    assert "started in background" in result.stdout
    assert saved["daemon"].pid == 321
    assert saved["daemon"].models == ["mlx-community/Llama-3.2-1B-Instruct-4bit"]
    assert saved["daemon"].log_path == str(log_path)
    assert captured["args"] == [
        cli.sys.executable,
        "-m",
        "toknx_node.cli",
        "run-daemon",
        "--model",
        "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "--capability-mode",
        "solo",
        "--inference-port-base",
        "52415",
    ]
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdin"] is cli.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is cli.subprocess.STDOUT
    assert Path(captured["kwargs"]["stdout"].name) == log_path


def test_start_rejects_when_background_daemon_exists(monkeypatch):
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: StoredConfig(github_username="alice", api_key="toknx_api_test", node_token="toknx_node_test"),
    )
    monkeypatch.setattr(cli, "_load_live_daemon", lambda _config=None: DaemonState(pid=123, log_path="/tmp/node.log"))

    result = runner.invoke(
        cli.app,
        ["start", "--model", "mlx-community/Llama-3.2-1B-Instruct-4bit"],
    )

    assert result.exit_code == 1
    assert "already running in background" in result.stdout


def test_status_reports_running_background_process(monkeypatch):
    class FakeClient:
        def __init__(self, api_base_url: str, api_key: str, node_token: str):
            self.api_base_url = api_base_url
            self.api_key = api_key
            self.node_token = node_token

        @staticmethod
        def get_balance():
            return {"balance": 42}

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: StoredConfig(github_username="alice", api_key="toknx_api_test", node_token="toknx_node_test"),
    )
    monkeypatch.setattr(
        cli,
        "load_runtime",
        lambda: RuntimeState(
            node_id="node-123",
            models=["mlx-community/Llama-3.2-1B-Instruct-4bit"],
            started_at="2026-04-02T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(
        cli,
        "_load_live_daemon",
        lambda _config=None: DaemonState(pid=321, log_path="/tmp/node.log"),
    )
    monkeypatch.setattr(cli, "ToknXClient", FakeClient)

    result = runner.invoke(cli.app, ["status"])

    assert result.exit_code == 0
    assert "Process: running (pid 321)" in result.stdout
    assert "Logs: /tmp/node.log" in result.stdout
    assert "Node: node-123" in result.stdout


def test_stop_terminates_background_daemon_and_deregisters(monkeypatch):
    captured: dict = {"cleared": []}

    class FakeClient:
        def __init__(self, api_base_url: str, api_key: str, node_token: str):
            captured["api_base_url"] = api_base_url
            captured["api_key"] = api_key
            captured["node_token"] = node_token

        def deregister_node(self, node_id: str):
            captured["node_id"] = node_id

    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: StoredConfig(github_username="alice", api_key="toknx_api_test", node_token="toknx_node_test"),
    )
    monkeypatch.setattr(cli, "_load_live_daemon", lambda _config=None: DaemonState(pid=321, log_path="/tmp/node.log"))
    monkeypatch.setattr(cli, "_stop_local_daemon", lambda daemon: daemon.pid == 321)
    monkeypatch.setattr(
        cli,
        "load_runtime",
        lambda: RuntimeState(node_id="node-123", models=["mlx-community/Llama-3.2-1B-Instruct-4bit"]),
    )
    monkeypatch.setattr(cli, "ToknXClient", FakeClient)
    monkeypatch.setattr(cli, "clear_daemon", lambda: captured["cleared"].append("daemon"))
    monkeypatch.setattr(cli, "clear_runtime", lambda: captured["cleared"].append("runtime"))

    result = runner.invoke(cli.app, ["stop"])

    assert result.exit_code == 0
    assert "Stopped background node process 321" in result.stdout
    assert "Deregistered node node-123" in result.stdout
    assert captured["node_id"] == "node-123"
    assert captured["cleared"] == ["daemon", "runtime"]
