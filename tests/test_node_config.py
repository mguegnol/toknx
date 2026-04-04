from toknx_node import config


def test_get_api_base_url_defaults_to_production(monkeypatch):
    monkeypatch.delenv("TOKNX_API_BASE_URL", raising=False)

    assert config.get_api_base_url() == config.PRODUCTION_API_BASE_URL


def test_get_api_base_url_uses_env_override(monkeypatch):
    monkeypatch.setenv("TOKNX_API_BASE_URL", "http://localhost/api")

    assert config.get_api_base_url() == "http://localhost/api"


def test_daemon_state_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "DAEMON_PATH", tmp_path / "daemon.json")

    config.save_daemon(
        config.DaemonState(
            pid=321,
            log_path="/tmp/node.log",
            models=["mlx-community/Llama-3.2-1B-Instruct-4bit"],
            started_at="2026-04-02T00:00:00+00:00",
        )
    )

    assert config.load_daemon() == config.DaemonState(
        pid=321,
        log_path="/tmp/node.log",
        models=["mlx-community/Llama-3.2-1B-Instruct-4bit"],
        started_at="2026-04-02T00:00:00+00:00",
    )
