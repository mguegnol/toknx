import pytest

from toknx_node import runner


def test_build_model_ports_assigns_incremental_ports():
    ports = runner._build_model_ports(
        [
            "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
            "mlx-community/Qwen2.5-Coder-3B-Instruct-4bit",
        ],
        52415,
    )

    assert ports == {
        "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit": 52415,
        "mlx-community/Qwen2.5-Coder-3B-Instruct-4bit": 52416,
    }


@pytest.mark.anyio
async def test_mlx_lm_inference_backend_delegates_to_matching_port(monkeypatch):
    captured: dict = {}

    async def fake_run_mlx_lm_job(send_message, *, job_id: str, request_payload: dict, port: int) -> None:
        captured["send_message"] = send_message
        captured["job_id"] = job_id
        captured["request_payload"] = request_payload
        captured["port"] = port

    async def send_message(payload: dict) -> None:
        return None

    monkeypatch.setattr(runner, "_run_mlx_lm_job", fake_run_mlx_lm_job)

    backend = runner.MlxLmInferenceBackend(
        model_ports={"mlx-community/Qwen2.5-Coder-7B-Instruct-4bit": 4242}
    )
    request_payload = {"model": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"}

    await backend.run_job(send_message, job_id="job-123", request_payload=request_payload)

    assert captured == {
        "send_message": send_message,
        "job_id": "job-123",
        "request_payload": request_payload,
        "port": 4242,
    }


@pytest.mark.anyio
async def test_mlx_lm_inference_backend_rejects_unknown_model():
    events: list[dict] = []

    async def send_message(payload: dict) -> None:
        events.append(payload)

    backend = runner.MlxLmInferenceBackend(model_ports={})

    await backend.run_job(
        send_message,
        job_id="job-123",
        request_payload={"model": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"},
    )

    assert events == [
        {
            "type": "failed",
            "job_id": "job-123",
            "error": "model not loaded: mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
        }
    ]
