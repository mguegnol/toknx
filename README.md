# ToknX

ToknX is a decentralized LLM inference network for Apple Silicon devices.

In plain terms:

1. People run Mac hardware as ToknX nodes.
2. The network routes inference jobs to those nodes.
3. Node operators earn credits and can spend those credits through an OpenAI-compatible API.

This repository contains both sides of that system:

- the coordinator that accepts API requests, tracks credits, and routes jobs
- the node CLI that operators use to join the network
- the dashboard and local infrastructure used to run the whole project in development

This README is split into two parts:

1. **Run a node and take part in the network**: for contributors and node operators
2. **Run the whole project locally**: for maintainers working on ToknX itself

## Part 1: Run a Node and Take Part in the Network

This section is for someone who wants to contribute a machine to ToknX.

If you are brand new to the project, the important idea is simple: you install the `toknx` CLI, log in through the hosted ToknX coordinator, and start serving one or more models from your machine.

The production CLI is intentionally strict:

- it always talks to `https://coordinator.toknx.dev`
- it is for real node operation only
- it does not include local-development or mock-inference modes

### What you need

- an Apple Silicon Mac
- `uv` installed and available on your `PATH`
- a web browser for login
- Xcode plus the Apple Metal Toolchain so ToknX can launch `exo` and run real local inference

### 1. Install the node CLI

Recommended install flow:

```bash
curl -fsSL https://toknx.dev/install-node.sh | bash
```

What the installer does:

- installs Python `3.12` with `uv` for the ToknX CLI
- installs the `toknx` CLI with `uv tool install`
- installs `exo` using Python `3.13`

If you are installing from this repository instead of a hosted script:

```bash
./install-node.sh
```

If you prefer a manual install:

```bash
uv python install 3.12
uv tool install --python 3.12 ./apps/node-cli
```

If the installer tells you the Metal Toolchain is missing, install it with:

```bash
xcodebuild -downloadComponent MetalToolchain
```

If `toknx` is not found after installation, add the `uv` tool bin directory to your `PATH`:

```bash
export PATH="$(uv tool dir --bin):$PATH"
```

### 2. Log in

Run:

```bash
toknx login
```

What happens:

- your browser opens the ToknX login flow
- the coordinator returns an API key and a node token
- the CLI stores those credentials in your user config directory

### 3. Start your node

Start a real node:

```bash
toknx start \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

You can advertise more than one model by passing a comma-separated list:

```bash
toknx start \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit,mlx-community/Qwen2.5-Coder-3B-Instruct-4bit
```

What ToknX does on startup:

1. detects your hardware
2. registers the node with the coordinator
3. starts `exo` locally
4. locks the node stake from your account balance
5. opens a persistent WebSocket tunnel back to the coordinator
6. serves inference requests until you stop the process

### 4. Check that the node is online

From the CLI:

```bash
toknx status
```

You should see your account, credits, and local runtime state once the node is connected.

### 5. Stop the node cleanly

Press `Ctrl+C` in the running process, or use:

```bash
toknx stop
```

Stopping cleanly deregisters the node and clears the local runtime state.

### Useful commands

```bash
toknx status
toknx stop
```

### Operator notes

- Real inference nodes currently target Apple Silicon.
- The production `toknx` CLI has no mock or local-development mode.
- Node registration validates RAM against the models you declare.
- Registering a node locks stake from the same account balance used for API consumption.

## Part 2: Run the Whole Project Locally

This section is for maintainers working on ToknX itself.

The recommended path is Docker Compose. It starts the coordinator, dashboard, database, observability tools, and the reverse proxy with the local URLs used throughout the maintainer workflow.

Important boundary:

- the production `toknx` CLI does not target `localhost`
- local auth bypass and fake-node behavior are maintainer-only tools
- local end-to-end verification lives in `tests/`, not in the shipped node CLI
- `docker-compose.yml` is the realistic local stack, and `docker-compose.dev.yml` is the maintainer override for dev-bypass workflows

### What starts locally

`docker compose up` brings up:

- `traefik` on `http://localhost`
- `coordinator` behind `http://localhost/api`
- `dashboard` behind `http://localhost/`
- `postgres`
- `redis`
- `prometheus`
- `grafana`

### Requirements

- Docker with `docker compose`
- `curl`
- `uv` if you want to run backend tests or the coordinator directly from the checkout
- `npm` if you want to run the dashboard outside Docker for faster frontend iteration

### 1. Start the stack

For the realistic local stack, with real OAuth routed through Traefik:

```bash
docker compose up --build -d
```

For maintainer-only shortcuts such as dev auth bypass and the smoke test:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

Confirm the coordinator is healthy:

```bash
curl http://localhost/api/healthz
```

Expected response:

```json
{"status":"ok"}
```

Useful local URLs:

- dashboard: `http://localhost`
- API base: `http://localhost/api`
- Traefik dashboard: `http://localhost:8080`
- Grafana: `http://localhost:3001`
- Prometheus: `http://localhost:9090`

### 2. Authenticate locally

If you started the base stack only, make sure `TOKNX_GITHUB_CLIENT_ID` and `TOKNX_GITHUB_CLIENT_SECRET` are available to Docker Compose, then test the real OAuth flow through Traefik:

```bash
open 'http://localhost/api/auth/github?redirect_uri=http://127.0.0.1:8787/callback&state=test-state'
```

If you started the dev override stack, local development bypasses real GitHub OAuth. Create an account with:

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

Keep the returned values:

- `api_key` is for calling the inference API
- `node_token` is used when registering a node

### 3. Exercise the API

List live models:

```bash
curl http://localhost/api/v1/models
```

Check the account balance:

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

### 4. Run the smoke test

The smoke test covers:

- API health
- dev signup
- node registration
- fake node tunnel wiring
- completion request
- stats update
- balance and transaction checks
- node deregistration

Run it with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
tests/smoke_test.sh
```

Optional environment variables:

```bash
TOKNX_BASE_URL=http://localhost/api
TOKNX_MODEL_ID=mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
TOKNX_SMOKE_RUN_ID=custom-run-id
tests/smoke_test.sh
```

The fake node used by the smoke test is maintainer-only test code. It is not part of the production `toknx` CLI.

### 5. Inner-loop development without rebuilding containers

If you are actively editing code, you may want to run services directly from the repo.

If you want a starting point for local environment variables, copy:

```bash
cp .env.example .env
```

This is optional for the default Docker Compose flow above, but useful when you want to run the coordinator directly from the checkout and tweak settings locally.

Install backend dependencies:

```bash
uv sync --group dev
```

Install dashboard dependencies:

```bash
npm --prefix apps/dashboard install
```

Run the coordinator directly:

```bash
TOKNX_AUTH_DEV_BYPASS=true \
TOKNX_JWT_SECRET=development-secret \
uv run --package toknx-coordinator toknx-coordinator
```

Run the dashboard directly in another terminal:

```bash
TOKNX_PUBLIC_API_BASE=http://127.0.0.1:8000 \
VITE_TOKNX_API_BASE=http://127.0.0.1:8000 \
npm --prefix apps/dashboard run dev
```

Notes for this mode:

- the coordinator defaults to SQLite when you run it directly
- without Traefik, the API base is `http://127.0.0.1:8000`, not `http://localhost/api`
- the production `toknx` CLI is not used against a natively started local coordinator

### 6. Stop or reset the local stack

Stop containers:

```bash
docker compose down
```

Stop and remove local volumes for a clean reset:

```bash
docker compose down -v
```

## Repository Layout

- `apps/coordinator`: FastAPI coordinator for auth, credits, nodes, jobs, SSE, and WebSocket tunnels
- `apps/node-cli`: Python CLI for login and node lifecycle
- `apps/dashboard`: SvelteKit dashboard
- `infra`: Traefik, Prometheus, and Grafana config for local development
- `tests/smoke_test.sh`: end-to-end smoke test against a running stack
