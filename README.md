# ToknX

ToknX is a compute co-op for Apple Silicon LLM inference. Contributors run Mac hardware, earn credits, and spend those credits through an OpenAI-compatible API.

This repository contains:

- `apps/coordinator`: FastAPI coordinator for auth, credits, nodes, jobs, SSE, and WebSocket tunnels
- `apps/node-cli`: Python CLI for contributor login and node lifecycle
- `apps/dashboard`: SvelteKit landing page and live dashboard
- `infra`: local Docker Compose, Traefik, Prometheus, and Grafana config
- `tests/smoke_test.sh`: end-to-end smoke test against a running stack

## Requirements

- Docker with `docker compose`
- `uv` on your `PATH` for contributor installation
- `curl`

For real inference nodes:

- Apple Silicon Mac
- Xcode with the Apple Metal Toolchain installed

## Start the stack

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Start the local stack:

```bash
docker compose up --build -d
```

3. Verify it is live:

```bash
curl http://localhost/api/healthz
```

4. Open:

- Dashboard: `http://localhost`
- API base: `http://localhost/api`
- Traefik dashboard: `http://localhost:8080`
- Grafana: `http://localhost:3001`
- Prometheus: `http://localhost:9090`

## Sign up and get credentials

In local development, GitHub OAuth is bypassed with a dev shortcut. This creates an account and returns an API key and node token.

```bash
curl 'http://localhost/api/auth/github/callback?code=dev:alice'
```

Example response:

```json
{
  "github_username": "alice",
  "api_key": "toknx_api_...",
  "node_token": "toknx_node_..."
}
```

Use:

- `api_key` for consuming inference
- `node_token` for registering contributor nodes

Each new account receives `20_000` credits in the current local setup.

## Consume tokens through the API

ToknX exposes an OpenAI-compatible `chat.completions` endpoint.

List currently available models:

```bash
curl http://localhost/api/v1/models
```

Check your credit balance:

```bash
curl http://localhost/api/account/balance \
  -H 'Authorization: Bearer YOUR_API_KEY'
```

Send a completion request:

```bash
curl http://localhost/api/v1/chat/completions \
  -H 'Authorization: Bearer YOUR_API_KEY' \
  -H 'Content-Type: application/json' \
  --data '{
    "model": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit",
    "stream": false,
    "messages": [
      { "role": "user", "content": "Write a haiku about distributed inference." }
    ]
  }'
```

Streaming mode also works by setting `"stream": true`.

## Install the contributor CLI

For contributors, the intended install flow is:

```bash
curl -fsSL https://toknx.dev/install-node.sh | bash
```

In this repository, the installer script is [install-node.sh](/Users/maxence/Documents/toknx/install-node.sh). It:

- installs Python `3.12` through `uv`
- installs Python `3.13` for `exo` through `uv`
- installs the `toknx` CLI with `uv tool install`
- installs `exo` with `uv tool install` by default
- places executables in `uv tool dir --bin`

The installer assumes `uv` is already installed. It does not bootstrap `uv` for you.

For a real `exo` install, make sure the Metal toolchain is available first:

```bash
xcodebuild -downloadComponent MetalToolchain
```

If you are testing from a local checkout instead of a hosted URL:

```bash
./install-node.sh
```

If you want a mock-only install without `exo`:

```bash
TOKNX_SKIP_EXO=1 ./install-node.sh
```

If you prefer a manual install:

```bash
uv python install 3.12
uv tool install --python 3.12 ./apps/node-cli
```

## Run a node with the CLI

Log in:

```bash
toknx login --api-base-url http://localhost/api --username alice
```

This opens a browser to the local dev auth flow and stores credentials in your user config directory.

Minimal contributor flow:

```bash
curl -fsSL https://toknx.dev/install-node.sh | bash
toknx login --api-base-url http://localhost/api --username alice
toknx start --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit --launch-exo
```

Run a mock node without `exo`:

```bash
toknx start \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --mock-inference
```

Run a real node with `exo`:

```bash
toknx start \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --launch-exo
```

If you installed with `TOKNX_SKIP_EXO=1`, use `--mock-inference` instead of `--launch-exo`.

Useful CLI commands:

```bash
toknx status
toknx stop
```

Notes:

- Multiple models can be passed as a comma-separated value to `--model`
- The coordinator enforces RAM budget validation during node registration
- Registering a node locks the configured stake amount from the same account balance
- Deregistering a node refunds the stake and keeps historical job attribution

## Register a node without the CLI

If you want to hit the API directly:

```bash
curl http://localhost/api/nodes/register \
  -H 'Authorization: Bearer YOUR_NODE_TOKEN' \
  -H 'Content-Type: application/json' \
  --data '{
    "committed_models": ["mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"],
    "hardware_spec": { "chip": "M4 Pro", "ram_gb": 64 },
    "capability_mode": "solo"
  }'
```

This returns:

- `node_id`
- `tunnel_token`
- `node_secret`

The node then connects to:

- WebSocket tunnel: `/nodes/tunnel?token=...`

## Public and operational endpoints

- `GET /api/healthz`
- `GET /api/stats`
- `GET /api/v1/models`
- `GET /api/leaderboard`
- `GET /api/events/stream`
- `GET /api/metrics`

## Run the smoke test

The smoke test exercises the live stack end to end:

- API health
- dev signup
- node registration
- mock tunnel
- completion request
- stats update
- balance and transaction checks
- node deregistration

Run it with:

```bash
tests/smoke_test.sh
```

Optional environment variables:

```bash
TOKNX_BASE_URL=http://localhost/api
TOKNX_MODEL_ID=mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
TOKNX_SMOKE_RUN_ID=custom-run-id
tests/smoke_test.sh
```

## Development notes

- Traefik uses a static file provider in local development; routes are defined in [infra/traefik/dynamic.yml](/Users/maxence/Documents/toknx/infra/traefik/dynamic.yml)
- The coordinator uses PostgreSQL in Docker and retries initial DB startup so it can survive container ordering
- Node deregistration is a soft delete: the node is marked `deregistered`, but completed jobs and transactions keep their original `node_id`
- The coordinator dependency set in [apps/coordinator/pyproject.toml](/Users/maxence/Documents/toknx/apps/coordinator/pyproject.toml) is pinned because looser ranges caused non-deterministic container rebuild failures
