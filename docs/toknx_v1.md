# toknX v1 — Implementation Plan

A compute co-op for LLM inference. Contribute idle Apple Silicon hardware, earn credits, spend credits on code generation. Solo inference only — no sharding, no verification, no dashboard. Prove the marketplace works first.

Full architecture plan: [toknX.md](toknX.md)

---

## Scope

### What v1 is
- Solo-node inference marketplace with credit metering
- Any MLX model from Hugging Face
- Closed-loop credit system: contribute compute → earn credits → spend on inference
- Trusted early community (5–10 nodes, mostly yours)

### What v1 is NOT (deferred to v2+)
| Feature | Why deferred |
|---|---|
| WAN shard groups (Headscale, Tailscale, PlacementEngine) | Unvalidated premise — requires benchmark first |
| Perplexity-based verification + stake/slash | Not needed when you control most nodes |
| `toknx add-model` / `toknx remove-model` (hot reload) | Unclear exo hot-reload support. Restart-to-change is acceptable |
| Job table partitioning + pg_cron retention | Won't hit volume for months. Add at ~10M rows |
| Credit reconciliation cron | Manual reconciliation is fine with 10 nodes |
| API key rotation | Re-auth via GitHub OAuth if compromised |
| Supply-side bonus (1.5× multiplier) | You *are* the supply at launch |
| Per-node public profiles + map | v2 — once there are enough nodes to make it interesting |
| Multiple Grafana dashboards | One operations dashboard is enough |
| Queue visibility endpoint (`GET /v1/queue`) | Consumers get 503 + Retry-After. Quality-of-life, not critical |

---

## Architecture (v1)

```
                    ┌──────────────────────────────────────┐
                    │            COORDINATOR                 │
                    │            (you host)                  │
                    │                                        │
Consumer ──────────►│  OpenAI-compatible proxy API          │
                    │  GitHub OAuth + credit metering        │
                    │  Node registry                         │
                    │  Job queue (Redis, per-model)          │
                    │  Credit ledger (PostgreSQL)            │
                    │  Statistical anomaly checker           │
                    │  WebSocket tunnel manager              │
                    └───────────────┬────────────────────────┘
                                    │ control: WS tunnel
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                       ▼
         [Node A]              [Node B]               [Node C]
         Mac Studio            Mac Mini M4            Mac Mini M4
         70B solo              7B + 32B solo          7B solo
         WS tunnel             WS tunnel              WS tunnel
```

**Job flow**:
1. Consumer `POST /v1/chat/completions` with model specified
2. Job pushed to `queue:{hf_id}` Redis sorted set → consumer holds SSE connection
3. Coordinator pops job, selects online solo node with matching model
4. Node forwards to `localhost:52415`, streams token chunks back via WS tunnel
5. Coordinator relays SSE to consumer, counts tokens, applies credit split

---

## Model system

### Open model registry
Contributors serve any MLX-compatible model from Hugging Face. Coordinator auto-discovers model metadata from HF API on first encounter.

### Pricing tiers (by model RAM footprint)

| Tier | Model RAM | Consumer price (credits / 1K tokens) | Contributor reward (credits / 1K tokens) |
|---|---|---|---|
| S | < 8 GB | 1 | 0.90 |
| M | 8–16 GB | 2 | 1.80 |
| L | 16–32 GB | 4 | 3.60 |
| XL | 32–64 GB | 8 | 7.20 |
| XXL | > 64 GB | 16 | 14.40 |

v1 credit split is simplified — no verification tax:

| Recipient | Per 100 credits |
|---|---|
| Coordinator | 10 (5 during launch period) |
| Contributor | 90 (95 during launch period) |

Launch period (first 30 days): coordinator takes 5% instead of 10%.


### Multiple models per node
A node can serve multiple models simultaneously if RAM allows. Declared at startup via `toknx start --model <hf_id>[,<hf_id>...]`. Changing models requires restart in v1. Coordinator rejects registration if `sum(model.estimated_ram_gb) > node.hardware_spec.ram_gb`.

---

## Credit system (closed-loop, no fiat)

```
  GitHub signup ──→ 20K free credits
       │
       ├──→ Consume inference (spend credits)
       │         │
       │         └──→ Contributor earns 90% ──→ Spend as consumer (loop)
       │              Coordinator earns 10% ──→ Recycled into free tier pool
       │
       └──→ Contribute compute ──→ Earn credits ──→ Spend on inference
```

- **No money in, no money out**. Pure compute exchange.
- **Free credits on signup**: enough to evaluate the API and fund a node stake
- **Coordinator's 10% cut**: recycled into free tier pool. Not revenue — fuel for the flywheel

### Free credits
Every account gets **20K credits** on signup. 20K credits at tier M = 10M tokens. Enough to evaluate the API and fund a node stake, but forces the contribute-to-earn loop quickly.

### Node stake
500 credits required on registration, deducted from account balance. Refunded on voluntary deregister. In v1, no automated slash.

---

## Identity and authentication

### Unified GitHub identity
One GitHub OAuth → one toknX account → one API key + one node token → one credit balance. Same account consumes and contributes.

**Signup flow**:
1. User visits `toknx.co` → GitHub OAuth → account created
2. Cloudflare Turnstile (invisible, free) blocks bots
3. 20K free credits minted
4. User receives API key (consuming) and node token (contributing)

### Anti-Sybil
- GitHub-only signup (no email)
- Max 5 nodes per account
- 500-credit stake per node

---

## Job queue and backpressure

- **Per-model Redis sorted sets**: `queue:{hf_id}` — FIFO by submission timestamp
- **30s timeout**: no node available → `503 Service Unavailable` with `Retry-After: 10`
- **Per-account concurrency limit**: 5 in-flight jobs
- **Global queue cap**: 100 pending jobs per model → `429 Too Many Requests`
- **Rate limiting**: 30 req/min on `POST /v1/chat/completions`, 120 req/min on reads, enforced via Redis sliding window


---

## Phases

### Phase 1 — Coordinator
**Goal**: Auth, credit ledger, job queue, solo job proxy, basic monitoring.

**Infrastructure**
- [ ] Scaffold FastAPI + PostgreSQL + Redis
- [ ] Docker Compose: Traefik + coordinator + dashboard + Redis + Postgres + Prometheus + Grafana
- [ ] TLS: Traefik with auto Let's Encrypt (handles HTTPS + WSS). Routes configured via Docker labels per service

**Database**
- [ ] Schema: `accounts`, `nodes`, `model_registry`, `jobs`, `credits`, `credit_transactions`, `stakes`
- [ ] GIN index on `nodes.committed_models`, partial index on `nodes.status = 'online'`

**Auth**
- [ ] GitHub OAuth flow → account + API key + node token + 20K free credits
- [ ] Cloudflare Turnstile on OAuth page
- [ ] Rate limiting: Redis sliding window (30 req/min completions, 120 req/min reads, 10 req/min auth per IP, 5 req/hour node registration per account)

**Node management**
- [ ] `POST /nodes/register` → validate account < max_nodes, validate MLX models, validate `sum(model.estimated_ram_gb) <= node.ram_gb`, resolve HF metadata → assign pricing tier → JWT node token
- [ ] Model registry: fetch metadata from HF API on first encounter, cache in `model_registry`
- [ ] `GET /v1/models`: all models served by online nodes, with tier, price, node count
- [ ] WebSocket tunnel: `WS /nodes/tunnel` — authenticate with JWT from registration, hold connection, register in Redis
- [ ] Ping/pong keepalive every 30s: mark offline after 3 missed pings (90s)

**Job routing**
- [ ] `POST /v1/chat/completions` → create job → push to `queue:{hf_id}` → hold SSE connection
- [ ] Pop next job from matching queue when node available → dispatch via WS tunnel
- [ ] Job multiplexing: `job_id` per job, demultiplex concurrent jobs per tunnel
- [ ] 30s timeout → `503`; concurrency limit → reject; queue cap → `429`
- [ ] Node failure mid-job → re-enqueue job once (max 1 retry). If retry also fails → `502` to consumer, not charged

**Credits**
- [ ] Token counting: parse `output_tokens` from completion → tier-based credit split → update `jobs`, `credits`, `credit_transactions`
- [ ] `GET /account/balance`: credit balance + recent transactions
- [ ] `POST /account/stake`: lock 500 credits for node registration

**Monitoring**
- [ ] Prometheus metrics: `toknx_nodes_online`, `toknx_jobs_total`, `toknx_job_duration_seconds`, `toknx_queue_depth`, `toknx_tokens_generated_total`, `toknx_ws_connections`, `toknx_credits_flow`
- [ ] Single Grafana dashboard: node count, job throughput, queue depth, error rate, credit flow
- [ ] Slack webhook alerts: no nodes online (2m), job failure rate > 10% (5m), queue depth > 50 (5m)

### Phase 2 — Node CLI
**Goal**: Contributor runs one command, mlx-lm starts, tunnel opens, node earns credits.

- [ ] Scaffold Python CLI package
- [ ] `toknx login`: authenticate against toknX account (GitHub OAuth via browser redirect → local callback)
- [ ] `toknx start --model <hf_id>[,<hf_id>...]`:
  - Check mlx-lm installed (guide to install if not)
  - Validate all models are valid MLX format
  - Download committed models via mlx-lm
  - Start mlx-lm as subprocess
  - Status `starting` until all models loaded → `online`
- [ ] `POST /nodes/register` with committed models, hardware specs (RAM, chip), capability mode → JWT
- [ ] Open persistent WS to `wss://api.toknx.co/nodes/tunnel`
- [ ] Handle `inference` jobs: forward to `localhost:52415/v1/chat/completions`, stream SSE chunks back via WS
- [ ] Send completion message with `output_tokens` count
- [ ] Auto-reconnect: exponential backoff (1s → 2s → 4s → max 60s)
- [ ] `toknx status`: credits earned, active jobs, committed models, tunnel state, uptime
- [ ] `toknx stop`: graceful shutdown — drain in-flight jobs, deregister, close tunnel, stop mlx-lm

### Phase 3 — Dashboard + Launch
**Goal**: Network is live, dashboard looks alive, ready to share.

- [ ] Deploy 5–10 Mac Mini / Mac Studio nodes (solo, covering popular models across tiers S/M/L)
- [ ] Activate launch credit split: coordinator takes 5% for first 30 days
- [ ] Signup free credits: 20K per account
- [ ] Scaffold SvelteKit app for dashboard (see Public dashboard section)
- [ ] SSE connection to `/events/stream` for live activity feed
- [ ] Poll `/stats`, `/v1/models`, `/leaderboard` for dashboard widgets
- [ ] GitHub signup CTA + "contribute a node" link to docs
- [ ] Dockerize dashboard, add Traefik labels for `toknx.co` catch-all route
- [ ] Run own nodes for 24h before sharing — verify dashboard looks alive with real traffic
- [ ] Docs page: "How to connect Continue.dev / Aider / Cursor to toknX" + "How to contribute a node"
- [ ] HN post: "I built a compute co-op for Apple Silicon — contribute idle Mac compute, earn LLM tokens"

---

## Public dashboard

Single-page app at `toknx.co`. The page people land on from HN and Twitter. Must make the network feel alive and the project feel real.

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  TOKNX — A compute co-op for Apple Silicon               │
│  Contribute idle Mac hardware. Earn LLM tokens.         │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  5 nodes │  │ 12 jobs  │  │ 847K     │  │ 34.2    │ │
│  │  online   │  │ running  │  │ tokens   │  │ tok/s   │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
│                                                          │
│  Models available now                                    │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Qwen2.5-Coder-7B-4bit    3 nodes   tier M   2 cr  │ │
│  │ Qwen2.5-Coder-32B-4bit   1 node    tier L   4 cr  │ │
│  │ Llama-3.1-8B-8bit        2 nodes   tier M   2 cr  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  Live activity                              ◉ streaming  │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ 14:23:01  job completed  Qwen2.5-7B     342 tokens │ │
│  │ 14:22:58  node online    Mac Mini M4    7B + 32B   │ │
│  │ 14:22:44  job completed  Llama-3.1-8B   128 tokens │ │
│  │ 14:22:31  job started    Qwen2.5-32B    ...        │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  Top contributors (7d)                                   │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ 1. @user1    Mac Studio 192GB   12,340 credits     │ │
│  │ 2. @user2    Mac Mini M4 24GB    8,210 credits     │ │
│  │ 3. @user3    Mac Mini M4 16GB    5,430 credits     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  [Sign up with GitHub]        [Contribute a node →]      │
└─────────────────────────────────────────────────────────┘
```

### Implementation
- **Frontend**: SvelteKit app. SSR for fast initial load (critical for HN/Twitter traffic), then client-side reactivity for live data. Runs as a Node container behind Traefik.
- **Live data**: coordinator pushes events via SSE on `GET /events/stream` (public, no auth). Events: `job_started`, `job_completed`, `node_online`, `node_offline`. SvelteKit reconnects on disconnect.
- **Stats**: polled from `GET /stats` every 10s. Returns `{nodes_online, jobs_running, tokens_total, tokens_per_second}`.
- **Models table**: polled from `GET /v1/models` every 30s.
- **Leaderboard**: polled from `GET /leaderboard` every 60s. Top 10 contributors by credits earned (7d). Shows GitHub username, hardware, credits.
- **Privacy**: no prompt/output content exposed. Activity feed shows model, token count, and timing only.
- **Routing**: Traefik routes API paths (`/v1/*`, `/nodes/*`, `/auth/*`, `/stats`, `/leaderboard`, `/events/*`) to FastAPI. Everything else (`/`) to the SvelteKit container. Configured via Docker labels — no separate proxy config file.

### Coordinator endpoints for dashboard

```
GET    /stats                   {nodes_online, jobs_running, tokens_total, tokens_per_second}
GET    /v1/models               Model registry with node counts
GET    /leaderboard             Top contributors (7d), GitHub username
GET    /events/stream           SSE stream of public network events (no auth)
```

### Phase 1 additions
- [ ] `GET /events/stream`: SSE endpoint, pushes `job_started`, `job_completed`, `node_online`, `node_offline` events (sanitized — no prompt/output content)
- [ ] `GET /leaderboard`: top 10 contributors by credits earned (7d rolling window), GitHub username

### Phase 3 additions
- [ ] Scaffold SvelteKit app, Dockerize, add Traefik labels
- [ ] Connect to SSE stream for live activity feed
- [ ] Poll stats/models/leaderboard endpoints
- [ ] GitHub signup CTA + "contribute a node" link to docs
- [ ] Test with real traffic from own nodes — verify it looks alive before sharing

---

## Tech stack

| Component | Tech |
|---|---|
| Coordinator API | Python 3.12 + FastAPI |
| Job queue / live node state | Redis |
| Credit ledger / nodes / jobs | PostgreSQL |
| Node inference | mlx-lm (Apple MLX) |
| Node CLI | Python 3.12 (wraps mlx-lm) |
| Node↔Coordinator control | WebSocket (node-initiated, persistent) |
| Dashboard | SvelteKit (SSR + client-side reactivity) |
| Auth | GitHub OAuth + Cloudflare Turnstile |
| TLS / reverse proxy | Traefik v3 (auto Let's Encrypt, Docker label routing) |
| Monitoring | Prometheus + Grafana + Slack webhooks |
| Deployment | Docker Compose (Traefik + coordinator + dashboard + Redis + Postgres + Prometheus + Grafana) |

---

## Database schema

```sql
accounts (
  id uuid PRIMARY KEY,
  api_key_hash text UNIQUE,
  node_token_hash text UNIQUE,
  github_id text UNIQUE,
  github_username text,
  max_nodes int DEFAULT 5,
  created_at timestamptz
)

nodes (
  id uuid PRIMARY KEY,
  account_id uuid REFERENCES accounts,
  token_hash text,
  committed_models jsonb,           -- ["mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", ...]
  hardware_spec jsonb,              -- {ram_gb, chip, unified_memory}
  status text,                      -- starting | online | offline
  tunnel_connected bool,
  stake_balance int DEFAULT 0,
  registered_at timestamptz,
  last_ping_at timestamptz
)
CREATE INDEX idx_nodes_committed_models ON nodes USING GIN (committed_models);
CREATE INDEX idx_nodes_status ON nodes (status) WHERE status = 'online';

model_registry (
  hf_id text PRIMARY KEY,
  parameter_count bigint,
  quantization text,                -- 4bit | 8bit | fp16
  estimated_ram_gb float,
  pricing_tier text,                -- S | M | L | XL | XXL
  credits_per_1k_tokens int,
  first_seen_at timestamptz
  -- node_count computed at query time: COUNT(nodes) WHERE status='online' AND committed_models @> hf_id
)

jobs (
  id uuid PRIMARY KEY,
  account_id uuid REFERENCES accounts,
  node_id uuid REFERENCES nodes,
  model text,
  prompt_tokens int,
  output_tokens int,
  credits_consumer int,
  credits_contributor int,
  credits_coordinator int,
  status text,                      -- queued | pending | running | completed | failed | timeout
  created_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz
)
CREATE INDEX idx_jobs_status ON jobs (status, created_at) WHERE status IN ('queued', 'pending', 'running');

credits (
  account_id uuid PRIMARY KEY REFERENCES accounts,
  balance int DEFAULT 0,
  total_earned int DEFAULT 0,
  total_spent int DEFAULT 0
  -- total_staked derived from stakes table: SUM(amount) WHERE status='active'
)

credit_transactions (
  id bigserial PRIMARY KEY,
  account_id uuid REFERENCES accounts,
  amount int,                       -- positive = credit, negative = debit
  tx_type text,                     -- signup_bonus | job_earned | job_spent | stake_lock | stake_refund | coordinator_fee
  job_id uuid REFERENCES jobs,
  node_id uuid REFERENCES nodes,
  balance_after int,
  created_at timestamptz DEFAULT now()
)
CREATE INDEX idx_credit_tx_account ON credit_transactions (account_id, created_at);

stakes (
  id uuid PRIMARY KEY,
  node_id uuid REFERENCES nodes,
  account_id uuid REFERENCES accounts,
  amount int,
  status text,                      -- active | withdrawn
  created_at timestamptz
)
```

---

## API surface

### Auth
```
GET    /auth/github             GitHub OAuth redirect
GET    /auth/github/callback    OAuth callback → API key + node token + 20K free credits
```

### Consumer
```
POST   /v1/chat/completions     OpenAI-compatible (solo only in v1)
GET    /v1/models               Live model registry
GET    /account/balance         Credit balance + recent transactions
```

### Node
```
POST   /nodes/register          Register node under account, get JWT
WS     /nodes/tunnel            Control tunnel
```

### Public
```
GET    /stats                   Network-wide stats (nodes, jobs, tokens generated, tok/s)
GET    /v1/models               Live model registry (also listed under Consumer)
GET    /leaderboard             Top contributors (7d), GitHub username
GET    /events/stream           SSE stream of network events (live activity feed)
```

---

## What triggers v2 work

| Signal | Action |
|---|---|
| Benchmark shows acceptable WAN latency | Build shard groups (Headscale, PlacementEngine, Tailscale integration) |
| Untrusted nodes start joining | Build perplexity verification + full stake/slash |
| Consumer requests model no solo node can serve | Prioritize sharding or recruit large-RAM contributors |
| Job table > 5M rows | Add monthly partitioning + pg_cron retention |
| Credit drift detected in manual checks | Build automated reconciliation cron |
| Abuse/Sybil detected | Trust tiers (GitHub account age/repos → differentiated free credits + concurrency) |
| Users lose API keys | API key rotation endpoint |
| Queue depth consistently > 10 for a tier | Supply-side bonus multiplier |
| Network > 50 nodes | Coordinator HA (active-passive failover) |

---
