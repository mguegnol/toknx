# ToknX Production Checklist

This checklist is for turning ToknX from a local development stack into a real hosted deployment.

It is written against the current codebase, where:

- the production `toknx` CLI is hardcoded to `https://coordinator.toknx.dev`
- the local Docker Compose stack is development-only
- GitHub OAuth is the production login path

## 1. Core Production Decisions

Before deploying anything, confirm these production decisions:

- operator CLI base URL: `https://coordinator.toknx.dev`
- public dashboard URL: `https://toknx.dev`
- WebSocket tunnel host: same coordinator host, unless split intentionally
- primary database: PostgreSQL
- cache / transient infra: Redis
- TLS termination: required
- GitHub OAuth app owner and callback URL: fixed and registered

## 2. DNS And TLS

Provision DNS records for:

- `toknx.dev`
- `coordinator.toknx.dev`

Confirm TLS certificates are valid for both hosts.

Required checks:

- `https://toknx.dev` loads over HTTPS
- `https://coordinator.toknx.dev/healthz` returns `200`
- WebSocket upgrades are allowed on `wss://coordinator.toknx.dev/nodes/tunnel`

## 3. Coordinator Environment

Set these environment variables for the coordinator deployment:

```env
TOKNX_APP_ENV=production
TOKNX_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/toknx
TOKNX_REDIS_URL=redis://HOST:6379/0
TOKNX_PUBLIC_BASE_URL=https://coordinator.toknx.dev
TOKNX_NODE_TUNNEL_PUBLIC_BASE_URL=wss://coordinator.toknx.dev
TOKNX_DASHBOARD_ORIGIN=https://toknx.dev
TOKNX_GITHUB_CLIENT_ID=...
TOKNX_GITHUB_CLIENT_SECRET=...
TOKNX_GITHUB_REDIRECT_URL=https://coordinator.toknx.dev/auth/github/callback
TOKNX_JWT_SECRET=replace-with-a-long-random-secret
TOKNX_AUTH_DEV_BYPASS=false
```

Recommended production overrides:

```env
TOKNX_QUEUE_TIMEOUT_SECONDS=30
TOKNX_MODEL_QUEUE_CAP=100
TOKNX_ACCOUNT_INFLIGHT_LIMIT=5
TOKNX_NODE_KEEPALIVE_SECONDS=30
TOKNX_NODE_OFFLINE_AFTER_SECONDS=90
```

Do not use the defaults from `.env.example` for production.

## 4. GitHub OAuth

Create or configure the GitHub OAuth app with:

- homepage URL: `https://toknx.dev`
- authorization callback URL: `https://coordinator.toknx.dev/auth/github/callback`

Verify the full login flow:

1. `toknx login` opens the browser.
2. GitHub consent completes successfully.
3. The callback returns an API key and node token.
4. The CLI stores credentials locally.

If GitHub OAuth is not configured, production login will fail in the coordinator auth routes.

## 5. Dashboard Deployment

Deploy the dashboard separately from the coordinator and set:

```env
TOKNX_PUBLIC_API_BASE=https://coordinator.toknx.dev
VITE_TOKNX_API_BASE=https://coordinator.toknx.dev
```

Verify the dashboard can load:

- `/stats`
- `/v1/models`
- `/leaderboard`

without falling back to empty data because of cross-origin or wrong-base-url issues.

## 6. Installer Hosting

The operator README points to:

```text
https://toknx.dev/install-node.sh
```

Before announcing production availability:

- publish `install-node.sh` at that URL
- make sure it is the current script from the repo
- confirm it downloads successfully with `curl -fsSL`
- confirm a clean machine can install both `toknx` and `exo`

## 7. Database Readiness

Current state of the repo:

- the coordinator initializes schema with `create_all()`
- there is no migration framework in place yet

That is acceptable for an initial internal deployment, but not a durable production story.

Before public launch, add:

- a migration tool such as Alembic
- an explicit schema migration process in deployment
- backup and restore procedures for PostgreSQL

Minimum database checks:

- coordinator starts against an empty production database
- coordinator restarts cleanly against an existing database
- account creation works
- node registration works
- credit settlement works

## 8. Redis Readiness

Redis is required for production operations and queue behavior.

Verify:

- the coordinator can connect on startup
- job dispatch works under load
- reconnect behavior is acceptable after Redis restarts

## 9. WebSocket And Reverse Proxy

The node tunnel depends on stable WebSocket forwarding.

Your proxy / ingress must:

- allow WebSocket upgrade headers
- avoid short idle timeouts
- preserve TLS correctly for `wss://coordinator.toknx.dev`

Verify with a real node:

1. `toknx login`
2. `toknx start --model ...`
3. node registers successfully
4. tunnel stays connected
5. `toknx status` reflects a live account and runtime state

## 10. Node Operator Verification

Run a full clean-machine operator test:

1. uninstall existing `toknx` and `exo`
2. delete local ToknX state
3. install from `https://toknx.dev/install-node.sh`
4. run `toknx login`
5. run `toknx start --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit`
6. confirm the model appears on the network
7. stop the node with `Ctrl+C`
8. confirm deregistration succeeds

This test should be performed on a machine that was not prepared manually ahead of time.

## 11. API Verification

From a real production account, verify:

- `GET /healthz`
- `GET /stats`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /nodes/register`
- `POST /nodes/{node_id}/deregister`

Also verify:

- `429` behavior for in-flight limits
- `429` behavior for model queue caps
- `503` behavior when no nodes are available
- `Retry-After` header on unavailable-node responses

## 12. Security Gaps To Close

These areas still need explicit production decisions or implementation:

- Cloudflare Turnstile is not currently enforced in the request path
- there is no explicit rate-limiting layer beyond queue and in-flight controls
- `TOKNX_AUTH_DEV_BYPASS` must remain disabled in production
- JWT secret rotation is not defined
- secrets management is not documented

Before public launch, define:

- where secrets live
- who can rotate them
- how compromised credentials are revoked
- how operator abuse and account farming are limited

## 13. Observability

At minimum, production should expose:

- health checks
- request logs
- node connect / disconnect logs
- job success / failure metrics
- queue depth signals
- database connectivity alerts
- Redis connectivity alerts

The repo already includes Prometheus / Grafana assets for local development. Production should have equivalent monitoring, even if the deployment topology changes.

## 14. Release Checklist

Before calling the system production-ready, all of the following should be true:

- DNS is live
- TLS is valid
- coordinator env vars are set correctly
- GitHub OAuth is configured
- dashboard is deployed against the production coordinator
- installer is hosted at `https://toknx.dev/install-node.sh`
- PostgreSQL is persistent and backed up
- Redis is reachable and monitored
- WebSocket tunnel works through the production proxy
- a clean-machine node install has succeeded
- a real end-to-end completion has succeeded
- dev bypass is disabled
- no localhost URLs are present in production configuration

## 15. Nice-To-Have Before Public Launch

- schema migrations
- automated production smoke test
- explicit rollback procedure
- node/operator onboarding page
- install analytics or at least installer access logs
- better abuse prevention on signup and API usage
