import os
from pathlib import Path

import pytest

from toknx_node import runner


def test_build_exo_env_uses_absolute_resource_and_dashboard_paths(monkeypatch, tmp_path):
    resources_dir = (tmp_path / "resources").resolve()
    resources_dir.mkdir()

    monkeypatch.setattr(runner.Path, "home", staticmethod(lambda: Path(tmp_path)))
    monkeypatch.setattr(runner, "_find_exo_resources", lambda: str(resources_dir))
    monkeypatch.delenv("EXO_RESOURCES_DIR", raising=False)
    monkeypatch.delenv("EXO_DASHBOARD_DIR", raising=False)

    env = runner._build_exo_env()

    assert env["EXO_RESOURCES_DIR"] == str(resources_dir)
    assert os.path.isabs(env["EXO_DASHBOARD_DIR"])
    assert Path(env["EXO_DASHBOARD_DIR"]).joinpath("index.html").exists()


@pytest.mark.anyio
async def test_exo_inference_backend_delegates_to_exo_runner(monkeypatch):
    captured: dict = {}

    async def fake_run_exo_job(send_message, *, job_id: str, request_payload: dict, exo_port: int) -> None:
        captured["send_message"] = send_message
        captured["job_id"] = job_id
        captured["request_payload"] = request_payload
        captured["exo_port"] = exo_port

    async def send_message(payload: dict) -> None:
        return None

    monkeypatch.setattr(runner, "_run_exo_job", fake_run_exo_job)

    backend = runner.ExoInferenceBackend(exo_port=4242)
    request_payload = {"model": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"}

    await backend.run_job(send_message, job_id="job-123", request_payload=request_payload)

    assert captured == {
        "send_message": send_message,
        "job_id": "job-123",
        "request_payload": request_payload,
        "exo_port": 4242,
    }
