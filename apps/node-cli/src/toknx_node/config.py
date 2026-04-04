import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from platformdirs import user_config_dir


PRODUCTION_API_BASE_URL = "https://api.toknx.co"
API_BASE_URL_ENV_VAR = "TOKNX_API_BASE_URL"

CONFIG_DIR = Path(user_config_dir("toknx", "toknx"))
CONFIG_PATH = CONFIG_DIR / "config.json"
RUNTIME_PATH = CONFIG_DIR / "runtime.json"
DAEMON_PATH = CONFIG_DIR / "daemon.json"


@dataclass
class StoredConfig:
    github_username: str = ""
    api_key: str = ""
    node_token: str = ""


@dataclass
class RuntimeState:
    node_id: str = ""
    models: Optional[List[str]] = None
    started_at: str = ""


@dataclass
class DaemonState:
    pid: int = 0
    log_path: str = ""
    models: Optional[List[str]] = None
    started_at: str = ""


def load_config() -> StoredConfig:
    if not CONFIG_PATH.exists():
        return StoredConfig()
    return StoredConfig(**json.loads(CONFIG_PATH.read_text()))


def save_config(config: StoredConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2))


def load_runtime() -> RuntimeState:
    if not RUNTIME_PATH.exists():
        return RuntimeState()
    return RuntimeState(**json.loads(RUNTIME_PATH.read_text()))


def save_runtime(runtime: RuntimeState) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.write_text(json.dumps(asdict(runtime), indent=2))


def load_daemon() -> DaemonState:
    if not DAEMON_PATH.exists():
        return DaemonState()
    return DaemonState(**json.loads(DAEMON_PATH.read_text()))


def save_daemon(daemon: DaemonState) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DAEMON_PATH.write_text(json.dumps(asdict(daemon), indent=2))


def clear_runtime() -> None:
    if RUNTIME_PATH.exists():
        RUNTIME_PATH.unlink()


def clear_daemon() -> None:
    if DAEMON_PATH.exists():
        DAEMON_PATH.unlink()


def get_api_base_url() -> str:
    return os.getenv(API_BASE_URL_ENV_VAR, PRODUCTION_API_BASE_URL)
