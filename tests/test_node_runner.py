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


@pytest.mark.anyio
async def test_run_mlx_lm_job_requests_stream_usage(monkeypatch):
    captured: dict = {}
    events: list[dict] = []

    class FakeResponse:
        @staticmethod
        def raise_for_status() -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}'
            yield 'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":1,"total_tokens":8}}'
            yield "data: [DONE]"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, url: str, *, json: dict):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            return FakeStreamContext()

    async def send_message(payload: dict) -> None:
        events.append(payload)

    monkeypatch.setattr(runner.httpx, "AsyncClient", FakeAsyncClient)

    await runner._run_mlx_lm_job(
        send_message,
        job_id="job-123",
        request_payload={
            "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
            "messages": [{"role": "user", "content": "hi"}],
        },
        port=52415,
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:52415/v1/chat/completions"
    assert captured["json"] == {
        "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert events == [
        {
            "type": "token",
            "job_id": "job-123",
            "chunk": "hello",
            "output_tokens": 1,
        },
        {
            "type": "completed",
            "job_id": "job-123",
            "output_tokens": 1,
            "prompt_tokens": 7,
        },
    ]
