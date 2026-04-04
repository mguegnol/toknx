from toknx_node import config


def test_get_api_base_url_defaults_to_production(monkeypatch):
    monkeypatch.delenv("TOKNX_API_BASE_URL", raising=False)

    assert config.get_api_base_url() == config.PRODUCTION_API_BASE_URL


def test_get_api_base_url_uses_env_override(monkeypatch):
    monkeypatch.setenv("TOKNX_API_BASE_URL", "http://localhost/api")

    assert config.get_api_base_url() == "http://localhost/api"
