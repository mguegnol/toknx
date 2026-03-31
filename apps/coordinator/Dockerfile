FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src

RUN pip install --no-cache-dir .

CMD ["uvicorn", "toknx_coordinator.main:app", "--host", "0.0.0.0", "--port", "8000"]

