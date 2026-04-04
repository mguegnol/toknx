from functools import lru_cache

from pydantic import AnyHttpUrl, AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOKNX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "toknX Coordinator"
    database_url: str = "sqlite+aiosqlite:///./toknx.db"
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: AnyHttpUrl = "http://localhost:8000"
    node_tunnel_public_base_url: AnyUrl | None = None
    dashboard_origin: AnyHttpUrl = "http://localhost:5173"

    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_url: AnyHttpUrl = "http://localhost:8000/auth/github/callback"
    turnstile_secret_key: str = ""
    jwt_secret: str = Field(default="change-me", min_length=8)
    auth_dev_bypass: bool = False

    coordinator_signup_bonus: int = 1_000
    node_stake_credits: int = 500
    queue_timeout_seconds: int = 30
    model_queue_cap: int = 100
    account_inflight_limit: int = 5
    node_keepalive_seconds: int = 30
    node_offline_after_seconds: int = 90
    fee_percent: int = 10


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
