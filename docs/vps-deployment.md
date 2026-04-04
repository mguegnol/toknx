# VPS Deployment Guide

This guide deploys ToknX to a single VPS with Docker Compose.

It assumes:

- the VPS already has Docker and Docker Compose installed
- your DNS can point `api.yourdomain.com` and `toknx.yourdomain.com` to the VPS
- you want ToknX to coexist with other services on the machine without exposing Postgres or Redis publicly

## 1. Audit and Remediate the Existing VPS

Before deploying ToknX, fix the host issues found in the audit:

1. Rotate every secret stored in plaintext on the VPS.
   The existing `/home/deploy/infra/.env` contains live-looking provider credentials and should be treated as compromised.
2. Remove catch-all HTTP routing from the existing Traefik stack.
   Anything like `PathPrefix(`/`)` on port 80 will conflict with ToknX.
3. Enforce HTTPS for public services.
   Public apps should terminate on `websecure`, not plain `web`.
4. Stop using `latest` tags for production images where possible.
5. Add swap on the VPS.

Example 4 GB swapfile:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Copy the Repo to the VPS

```bash
git clone git@github.com:mguegnol/toknx.git
cd toknx
git checkout main
```

## 3. Create the Production Env File

```bash
cp .env.production.example .env.production
```

Then edit `.env.production`:

```env
TOKNX_API_DOMAIN=api.yourdomain.com
TOKNX_DASHBOARD_DOMAIN=toknx.yourdomain.com
TOKNX_ACME_EMAIL=admin@yourdomain.com
TOKNX_POSTGRES_DB=toknx
TOKNX_POSTGRES_USER=toknx
TOKNX_POSTGRES_PASSWORD=STRONG_DB_PASSWORD

TOKNX_PUBLIC_BASE_URL=https://api.yourdomain.com
TOKNX_NODE_TUNNEL_PUBLIC_BASE_URL=wss://api.yourdomain.com
TOKNX_DATABASE_URL=postgresql+asyncpg://toknx:STRONG_DB_PASSWORD@postgres:5432/toknx
TOKNX_REDIS_URL=redis://redis:6379/0
TOKNX_GITHUB_CLIENT_ID=...
TOKNX_GITHUB_CLIENT_SECRET=...
TOKNX_GITHUB_REDIRECT_URL=https://api.yourdomain.com/auth/github/callback
TOKNX_JWT_SECRET=LONG_RANDOM_SECRET
TOKNX_AUTH_DEV_BYPASS=false
TOKNX_COORDINATOR_SIGNUP_BONUS=20000
TOKNX_NODE_STAKE_CREDITS=500
TOKNX_QUEUE_TIMEOUT_SECONDS=30
TOKNX_MODEL_QUEUE_CAP=100
TOKNX_ACCOUNT_INFLIGHT_LIMIT=5
TOKNX_NODE_KEEPALIVE_SECONDS=30
TOKNX_NODE_OFFLINE_AFTER_SECONDS=90
TOKNX_FEE_PERCENT=10
TOKNX_DASHBOARD_ORIGIN=https://toknx.yourdomain.com
TOKNX_PUBLIC_API_BASE=http://coordinator:8000
VITE_TOKNX_API_BASE=https://api.yourdomain.com
```

## 4. Configure DNS

Create `A` records pointing at the VPS:

- `api.yourdomain.com`
- `toknx.yourdomain.com`

## 5. Configure GitHub OAuth

In the GitHub OAuth app, set:

- Homepage URL: `https://toknx.yourdomain.com`
- Callback URL: `https://api.yourdomain.com/auth/github/callback`

These must match `TOKNX_DASHBOARD_ORIGIN` and `TOKNX_GITHUB_REDIRECT_URL`.

## 6. Pick the Proxy Topology

There are two valid production layouts in this repo:

1. `docker-compose.prod.yml`
   Use this on a clean VPS where ToknX owns ports `80` and `443`.
2. `docker-compose.shared-traefik.yml`
   Use this when the VPS already has a shared Traefik instance. This is the safer choice for the audited host because it already runs Traefik.

### Option A: ToknX Owns Traefik on the VPS

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.prod.yml \
  up --build -d
```

### Option B: Reuse an Existing Traefik Instance

First create or identify the shared Docker network that Traefik already uses:

```bash
docker network create shared-proxy
```

Then make sure the existing Traefik container is attached to that network.

Now start ToknX without its own Traefik service:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.shared-traefik.yml \
  up --build -d
```

The production stack does three important things:

- routes by hostname instead of local path prefixes
- uses strict host-based routing so it can coexist with other apps
- removes public exposure of Postgres and Redis

## 7. Verify the Deployment

Check container state:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.shared-traefik.yml \
  ps
```

Watch logs:

```bash
docker compose \
  --env-file .env.production \
  -f docker-compose.shared-traefik.yml \
  logs -f coordinator dashboard
```

Check the public endpoints:

- `https://toknx.yourdomain.com`
- `https://api.yourdomain.com/healthz`

## 8. Security Baseline

Keep only these public ports open:

- `22`
- `80`
- `443`

Do not expose:

- `5432`
- `6379`
- `9090`
- `3001`

## 9. Upgrades

```bash
git pull
docker compose \
  --env-file .env.production \
  -f docker-compose.shared-traefik.yml \
  up --build -d
```

## 10. Backups

Back up the Postgres volume or run regular `pg_dump` jobs. Do not rely only on the VPS disk.

Example:

```bash
docker exec -t $(docker compose ps -q postgres) pg_dump -U toknx toknx > toknx-$(date +%F).sql
```

## Routing Model

This production layout uses:

- `https://toknx.yourdomain.com` -> dashboard
- `https://api.yourdomain.com` -> coordinator

That avoids path-prefix conflicts with other services already living behind Traefik on the same VPS.
