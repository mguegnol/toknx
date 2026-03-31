# Hexo — Implementation Plan

A compute co-op for LLM inference. Contribute idle hardware, earn credits, spend credits on code generation.

---

## Architecture decisions

**Inference backend: exo (Apple MLX)**
exo handles inference, model downloads, and exposes an OpenAI-compatible API on `localhost:52415`. Apple Silicon only — no CUDA, no NVIDIA, no Windows. Framed as a feature: Apple Silicon's unified memory architecture is uniquely suited to large model inference. CUDA added in v2.

**WAN sharding: Headscale mesh + exo MLX Ring (shard-capable nodes only)**
Shard-capable nodes join a coordinator-owned Headscale network on startup — silently, with no account required on the contributor side. Solo nodes do not install or use Tailscale. Headscale is a self-hosted open-source Tailscale control server: unlimited devices, zero per-device cost, runs in Docker alongside the coordinator. Shard nodes use the standard Tailscale client — same command, same stable `100.x.x.x` IPs, same NAT traversal. A reusable ephemeral auth key is issued by the coordinator on registration. Once on the network, every shard node can reach every other shard node directly over TCP. Shard activation tensors flow node-to-node via exo MLX Ring over this direct connection. Coordinator is out of the activation tensor path entirely.

WAN sharding is gated behind a `--shard` capability flag. Solo contributors work without Tailscale.

**WAN latency mitigation**
exo's pipeline parallelism requires one network round-trip per pipeline stage per generated token. Activation tensors are small (~8–32 KB per token depending on model hidden dim), so bandwidth is not the bottleneck — RTT is. At 50ms WAN RTT with 2 nodes, that's ~50ms added latency per token. Mitigations:
- **Cap shard groups at 2 nodes** (1 WAN hop per token). 3+ node groups only formed when nodes are in the same region (RTT < 5ms).
- **Latency-aware placement**: PlacementEngine measures pairwise RTT between shard-capable nodes via Tailscale ping. Prefer node pairs with RTT < 30ms. Reject pairs with RTT > 80ms.
- **Speculative/lookahead decoding (v2)**: generate 3–5 candidate tokens per round-trip instead of 1. Amortizes WAN latency by 3–5×. Active research area (PipeDec, FlowSpec). Not available in exo today — v2 milestone.
- **Honest latency disclosure**: consumer API returns estimated tok/s for shard jobs. Consumers choose whether to accept slower shard inference or wait for a solo node.

**WAN connectivity: two channels**
- **Control channel**: persistent WebSocket from node to coordinator (job dispatch, verify tasks, token stream, credits). Node-initiated — always works. Used by all nodes.
- **Shard data channel**: direct TCP between shard peers via Tailscale (activation tensors). No relay, no NAT issues, no hole punching. Shard-capable nodes only.

**Verification: contributor nodes, not coordinator**
Perplexity scoring requires the same model that generated the output. The coordinator routes verify jobs to a second contributor node that already has the right model loaded. Coordinator requires no GPU — standard VPS.

**Credits: off-chain, PostgreSQL, closed-loop**
Fixed exchange rate (1 credit = 1 output token at a given model tier). No speculation, no secondary market, no fiat on-ramp, no cash-out. Pure compute exchange: contribute inference cycles → earn credits → spend credits on inference. Self-contained system for tech-savvy participants interested in the experiment.

---

## Architecture diagram

```
                    ┌──────────────────────────────────────────┐
                    │              COORDINATOR                   │
                    │              (you host)                    │
                    │                                            │
Consumer ──────────►│  OpenAI-compatible proxy API              │
                    │  Auth + credit metering                    │
                    │  Node registry + capability flags          │
                    │  Job router (solo or shard group)          │
                    │  Shard PlacementEngine                     │
                    │  Credit ledger (PostgreSQL)                │
                    │  Verify job router                         │
                    │  Statistical anomaly checker               │
                    │  WebSocket tunnel manager                  │
                    │  Headscale admin (auth key issuer)         │
                    │  Public dashboard                          │
                    └───────────────┬────────────────────────────┘
                                    │ control: WS tunnel
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                       ▼
         [Node A]              [Node B]               [Node C]
         Mac Studio            Mac Mini M4            Mac Mini M4
         70B solo              shard-capable          shard-capable
         WS tunnel             WS tunnel              WS tunnel
         (no Tailscale)        Headscale              Headscale
                                    │  data: direct TCP via Tailscale
                                    │  (exo MLX Ring, no relay)
                                    └──────────────────────┘
                               shard group: 32B across B+C
                               layers 0-23 on B, 24-47 on C
```

**Solo job flow**:
1. Consumer `POST /v1/chat/completions`
2. Coordinator selects solo node, sends `inference` job via WS tunnel
3. Node forwards to `localhost:52415`, streams token chunks back up tunnel
4. Coordinator relays SSE to consumer, applies credit split

**Shard group job flow**:
1. Consumer `POST /v1/chat/completions` for a large model
2. Coordinator PlacementEngine selects N shard-capable nodes, assigns layer ranges and Tailscale IPs
3. Coordinator sends `shard` job to each node via WS tunnel: `{job_id, layer_start, layer_end, peers: [{tailscale_ip, port}]}`
4. Nodes connect directly via Tailscale IPs, start exo in shard mode with assigned layers and peer addresses
5. exo MLX Ring runs pipeline inference over direct TCP — no coordinator relay
6. Final node streams output back to coordinator via WS tunnel
7. Coordinator relays SSE to consumer, splits credits proportional to layers held

---

## Node capability modes

| Mode | Flag | Requirements | Tailscale required | Job types |
|---|---|---|---|---|
| Solo | (default) | Any Apple Silicon Mac | No | `inference`, `verify` |
| Shard-capable | `--shard` | Any Apple Silicon Mac, stable connection | Yes (auto-installed) | `inference`, `verify`, `shard` |

Solo nodes connect to the coordinator via WebSocket only — no Tailscale install, no VPN permissions, no admin dialogs. Shard-capable nodes additionally join the Headscale network on startup for direct peer-to-peer tensor transfer.

---

## Headscale integration

**What Headscale is**
Headscale is a self-hosted, open-source implementation of the Tailscale control server. Nodes use the standard Tailscale client unchanged. Unlimited devices, zero per-device cost. Runs as a Docker container alongside the coordinator.

**Auth key management**
- Coordinator generates reusable ephemeral auth keys via the Headscale API on demand
- Keys are per-registration: coordinator calls Headscale API, gets a fresh key, returns it to the registering node
- Ephemeral: nodes automatically removed from the network 30–60 minutes after going offline — no stale entries
- No Tailscale account, no Headscale account required on the contributor side

**On shard-capable node startup**
```bash
# CLI runs silently (only for --shard nodes):
tailscale up --login-server=https://headscale.hexo.dev \
             --auth-key=<coordinator-issued-key> \
             --hostname=hexo-<node_id>
```
Solo nodes skip this step entirely — no Tailscale install, no permissions dialogs. Shard-capable nodes get a stable `100.x.x.x` IP immediately.

**Headscale IP in registry**
On registration, node reports its Headscale-assigned IP to the coordinator. Stored in `nodes.tailscale_ip`. Coordinator uses this to build peer lists for shard job dispatch.

**DERP relay fallback**
For nodes that cannot establish direct UDP connections, Tailscale's public DERP servers are used as relay fallback — no self-hosting required. Self-hosted DERP is a v2 ops option for full independence from Tailscale infrastructure.

**Scale and cost**
- Headscale: unlimited devices, self-hosted, no per-device cost
- Only cost: the VPS running the coordinator + Headscale (already paid)
- Migration path: replace with QUIC direct P2P in v2 to remove the Tailscale client dependency from contributors entirely

---

## Model system

### Open model registry
Contributors can serve **any MLX-compatible model** from Hugging Face. No curated catalog — the network supports whatever models participants choose to run. Coordinator maintains a live registry of all models currently served across the network.

### Pricing tiers (by model RAM footprint)

| Tier | Model RAM | Consumer price (credits / 1K tokens) | Contributor reward (credits / 1K tokens) | Examples |
|---|---|---|---|---|
| S | < 8 GB | 1 | 0.84 | Qwen2.5-Coder-3B-4bit, Phi-3-mini-4bit |
| M | 8–16 GB | 2 | 1.68 | Qwen2.5-Coder-7B-4bit, Llama-3.1-8B-4bit |
| L | 16–32 GB | 4 | 3.35 | Qwen2.5-Coder-32B-4bit, DeepSeek-Coder-V2-Lite-4bit |
| XL | 32–64 GB | 8 | 6.70 | Llama-3.1-70B-4bit, DeepSeek-Coder-V2-4bit |
| XXL | > 64 GB | 16 | 13.41 | Llama-3.1-405B-4bit (shard only) |

Tier is determined automatically from model metadata (parameter count + quantization → estimated RAM). Contributor reward follows the standard credit split (83.8% of consumer price on unverified, less on verified). Larger models = more RAM committed = higher reward per token.

### Model registration and discovery
- On startup, node declares one or more models via `hexo start --model <hf_id>[,<hf_id>...]`
- Coordinator resolves each HF id → model metadata (parameter count, quantization, estimated RAM) → assigns pricing tier
- Unknown models accepted if valid MLX format. Coordinator fetches metadata from HF API on first encounter and caches it
- `GET /v1/models` returns all models currently served by at least one online node, with tier, price, and node count

### Multiple models per node
A node can serve multiple models simultaneously if RAM allows. A Mac Studio with 192GB can hold a 7B + 32B + 70B at the same time. The constraint is RAM, not policy — if it fits, serve it. Model list stored in `nodes.committed_models jsonb`.

### Model addition without restart
Nodes can add models at runtime without going offline:
```bash
hexo add-model mlx-community/Qwen2.5-Coder-32B-Instruct-4bit
```
- Node downloads model in the background while continuing to serve existing models
- Node status stays `online` for existing models; new model marked `downloading` in node state
- On download complete, exo loads the model → node reports updated model list to coordinator
- Coordinator starts routing jobs for the new model immediately
- Model removal: `hexo remove-model <hf_id>` — stops accepting new jobs for that model, waits for in-flight jobs to drain, unloads

### Quantization contract
All models must use **4-bit quantization** (the standard `mlx-community` quantization). This is enforced:
- Node CLI validates quantization format on model load
- Coordinator rejects model registrations that don't match the `*-4bit` naming convention or fail metadata validation
- Critical for verification: perplexity scoring requires identical quantization between producer and verifier nodes (see Verification design)

### Coordinator-initiated model switching (v2)
- Coordinator can request a node to load/unload models dynamically based on demand signals
- Download queue with ETA reporting to coordinator
- Enables demand-responsive supply: coordinator signals "need more 32B capacity" → idle 7B nodes with sufficient RAM auto-switch

---

## Credit system

### Credit lifecycle (closed-loop, no fiat)

```
  ┌─── GitHub signup ──→ Free credits (10K–100K by trust tier)
  │
  │    ┌────────────────────────────────────────────┐
  │    │              CREDIT POOL                    │
  │    │                                             │
  ├──→ │  Consumer spends credits on inference  ──────┤
  │    │                  │                          │
  │    │     credit split │                          │
  │    │        ┌─────────┴──────────┐               │
  │    │        ▼                    ▼               │
  │    │  Contributor earns    Coordinator earns     │
  │    │  (83.8% avg)         (10%)                  │
  │    │        │                    │               │
  │    │        ▼                    ▼               │
  │    │  Spend as consumer   Recycled into          │
  │    │  (loop restarts)     free tier pool         │
  │    │                                             │
  │    └─────────────────────────────────────────────┘
  │
  └─── Contribute compute ──→ Earn credits ──→ Spend on inference
```

- **No money in**: no Stripe, no payment endpoint, no fiat on-ramp
- **No money out**: no cash-out, no redemption, no secondary market
- **Closed loop**: credits are earned by contributing compute and spent by consuming inference. The system is self-sustaining
- **Coordinator's 10% cut**: recycled into the free tier pool, funding new user onboarding. Not revenue — fuel for the flywheel
- **Bootstrapping**: free credits on signup (tier-based) give every participant enough to start consuming immediately. Contributing compute earns more credits to keep going

### Stake bootstrapping
Nodes must stake 500 credits to register. Source options:
1. **Free signup credits**: every account gets 10K–100K credits on GitHub OAuth signup. Stake 500, keep the rest for consuming
2. **Earned credits**: a user who already consumed their free tier can contribute a node, stake from earned balance

No chicken-and-egg: the free tier funds the initial stake.

## Credit split

Consumer pays 100 credits. Split per job:

| Recipient | Unverified job (80%) | Verified job (20%) | Expected per job |
|---|---|---|---|
| Coordinator | 10 | 10 | **10.0** |
| Contributor(s) | 85 | 79 | **83.8** |
| Verifier | 0 | 6 | **1.2** |

For shard group jobs, contributor share is split proportional to layers held:
```
node_credit = contributor_share × (node_layers / total_layers)
```

- Verification cost comes out of contributor share — consumer price is always fixed
- Verifier earns 6 credits ≈ 7.6% of contributor payout (forward pass ≈ 1/15th of generation, on 20% of jobs)
- Coordinator at 10% is well below marketplace incumbents (Vast.ai, RunPod: 20–25%)

**Launch period (first 30 days)**: coordinator takes 5%; 5% shifts to contributors to compensate cold-start risk.

| Recipient | Expected per job (launch) |
|---|---|
| Coordinator | 5.0 |
| Contributor(s) | 93.8 |
| Verifier | 1.2 |

**Implementation**: splits stored as config constants. Launch→steady-state is a single config change with no schema migration.

### Stake specification

| Parameter | Value | Rationale |
|---|---|---|
| Stake required on registration | 500 credits | ~500 output tokens worth of work; low enough to onboard, high enough to hurt |
| First flag penalty | −100 credits from stake | Warning shot — node keeps operating |
| Second flag penalty | −200 credits from stake | Escalation — node put on probation (verify rate → 100%) |
| Third flag penalty | remaining stake slashed + permanent ban | Three strikes = gone |
| Stake refund on voluntary deregister | 100% of remaining stake after 7-day cooldown | No penalty for honest exit |
| Re-registration after ban | blocked by keypair + Tailscale device ID | Prevents trivial Sybil re-registration |

**Anti-Sybil economics**: a cheater who gets caught on flag 1 + 2 loses 300 credits before ban. Average earnings before 2 flags ≈ 10 verified jobs × 83.8 credits = 838 credits, minus 500 stake = 338 net. But with 20% verify rate, detection within ~10 jobs is expected. Net profit is marginal and drops to negative once re-registration cost (new device attestation, new GitHub account) is factored in. At scale (reputation > 50 threshold), fresh nodes face 100% verify rate until trusted.

### Supply/demand balancing (without variable pricing)

Fixed pricing is a deliberate design choice — contributors earn a predictable rate, consumers pay a predictable price. No speculation, no race-to-bottom dynamics. Balancing mechanisms instead:

- **Queue depth visibility**: `GET /v1/queue` returns current queue depth and estimated wait per model tier. Consumers and integrations (Continue.dev, Aider) can display wait times.
- **Supply-side bonus**: when queue depth exceeds 10 pending jobs for a model tier for >5 minutes, active contributors on that tier earn a 1.5× credit multiplier (from coordinator margin, not consumer price). Bonus deactivates when queue clears. Config-driven, no schema change.
- **Consumer admission control**: when no nodes are available for a model tier, `POST /v1/chat/completions` returns `503 Service Unavailable` with `Retry-After` header and queue position. No silent queueing — consumer decides whether to wait or retry.
- **Contributor dashboard signal**: public dashboard shows per-model-tier demand (jobs/hour) and supply (online nodes). Contributors self-select profitable tiers.

---

## Job queue and backpressure

### Queue design
- **Per-model Redis sorted sets**: `queue:{hf_id}` — jobs sorted by submission timestamp. Routing requires exact model match (a consumer requesting Qwen2.5-Coder-7B cannot be served by Llama-3.1-8B even though both are tier M)
- Consumer `POST /v1/chat/completions` → job created in `pending` state → pushed to model-tier queue → consumer holds open SSE connection
- Node becomes available → coordinator pops next job from matching queue → dispatches via WS tunnel
- If no node available within **30s timeout**: return `503 Service Unavailable` with `Retry-After: 10` and queue position

### Backpressure
- **Per-consumer concurrency limit**: max 5 concurrent in-flight jobs per API key (configurable per tier)
- **Global queue cap**: max 100 pending jobs per model tier. Beyond this, new requests get `429 Too Many Requests`
- **Priority**: FIFO within a model tier. No paid priority lanes in v1 — fairness first

### Queue visibility
```
GET /v1/queue
→ { "qwen2.5-7b": { "pending": 3, "est_wait_s": 12 },
    "qwen2.5-32b": { "pending": 0, "est_wait_s": 0 },
    "deepseek-v2": { "pending": 8, "est_wait_s": 45 } }
```

---

## WAN sharding design

### Why Headscale instead of relay or hole punch
- Coordinator relay: coordinator carries all activation tensor bandwidth — expensive at scale
- TCP hole punch: unreliable across home NAT, high failure rate
- Headscale + Tailscale client: battle-tested NAT traversal (DERP relay + direct UDP), stable IPs, zero config on the contributor side, no account required, unlimited devices at no per-device cost

### Shard PlacementEngine (coordinator)
Selects shard groups on incoming large model requests:
1. **Model coverage**: `sum(node.ram_gb) >= model.ram_required`
2. **Max 2 nodes over WAN**: 3+ node groups only when pairwise RTT < 5ms (same region/LAN)
3. **Pairwise latency**: coordinator periodically measures RTT between shard-capable nodes via Tailscale ping. Reject pairs with RTT > 80ms. Prefer pairs with RTT < 30ms
4. **Minimize node count**: fewer hops = lower per-token latency
5. **Reputation**: prefer higher-reputation nodes

Layer assignment: `node_layers = total_layers × (node.ram_gb / group_total_ram)`

Shard groups are dynamic — formed per job, not pre-assigned. Coordinator builds peer list from `nodes.tailscale_ip` for each group member.

### Latency budget
| Shard config | Expected per-token overhead | Acceptable? |
|---|---|---|
| 2 nodes, RTT < 30ms | ~30ms/token | Yes — ~20 tok/s effective |
| 2 nodes, RTT 30–80ms | ~80ms/token | Marginal — ~10 tok/s, disclosed to consumer |
| 3+ nodes over WAN | 100ms+/token | No — rejected by PlacementEngine |
| 3+ nodes, same LAN | <5ms/token | Yes — near-native speed |

### Shard group health
If any node drops mid-job:
- Job fails immediately (pipeline is sequential)
- No credits paid to any node
- Consumer receives error, not charged
- Dropped node marked offline, excluded from shard groups until reconnect

---

## Verification design

### Statistical pre-filter (coordinator, zero compute)
Before routing to a verifier, coordinator flags obvious anomalies:
- Tokens/second ratio exceeds model-tier ceiling (too fast = suspicious)
- Repeated identical outputs from same node across different prompts
- Output length outliers vs prompt complexity

Flagged jobs go directly to reputation penalty review, skipping the verifier queue.

### Perplexity scoring (contributor node)
On 20% of completed jobs, coordinator selects a second node running **the exact same model** (same HF id, same quantization):
```json
{"type": "verify", "job_id": "...", "prompt": "...", "output": "...", "model": "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"}
```
Verifier sends prompt + output as forced assistant continuation to local exo with `logprobs=true`, computes mean log-probability of output tokens. Low score = garbage or off-model output.

**Quantization identity guarantee**: verification requires exact HF id match, not just model family or tier match. A job produced by `Qwen2.5-Coder-7B-Instruct-4bit` can only be verified by another node running `Qwen2.5-Coder-7B-Instruct-4bit`. Different quantizations (4-bit vs 8-bit) or different model variants produce divergent log-probabilities and would cause false flags. The 4-bit quantization contract (see Model system) ensures all nodes for a given model produce identical weights, so perplexity scores are directly comparable.

**Threshold calibration**: during Phase 4 testing, run verification against known-good outputs from own nodes to establish baseline perplexity distributions per model. Flag threshold set at 3+ standard deviations below the model's mean log-probability. Threshold stored per model in coordinator config, updated as more verification data accumulates.

If no eligible second node with the exact same model is online: job queued for deferred verification.

### Verifier eligibility
All nodes eligible at launch (reputation ≥ 0, opted in by default). Once network exceeds 50 active nodes, floor rises to reputation > 50 (config threshold — no schema change).

### Reputation
- Reputation starts at 0, increments per verified-clean job, decrements per flag
- Nodes with reputation > 100: spot-check rate drops from 20% to 5%
- Stake and slash details: see Stake specification under Credit system

---

## Identity and authentication

### Unified GitHub identity
All participants — consumers and contributors — authenticate via GitHub OAuth. A single Hexo account can both consume and contribute. There is one identity, one credit balance.

**Signup flow**:
1. User visits `hexo.dev` → GitHub OAuth → Hexo account created
2. Cloudflare Turnstile (invisible, free) blocks bots on the OAuth page
3. GitHub API queried for account age, public repos, contribution activity → trust tier assigned:
   - `new`: account < 90 days old or < 3 public repos → 10K free credits
   - `standard`: account ≥ 90 days, ≥ 3 repos → 100K free credits
   - `trusted`: account ≥ 1 year, ≥ 10 repos, contributions in last 90 days → 100K free credits + higher concurrency limit
4. User receives an API key (for consuming) and a node token (for contributing) — both tied to the same account

**Why unified identity**: in a closed-loop credit system with no fiat, every consumer is a potential contributor and vice versa. A developer who burns through their free credits needs to contribute compute to earn more. Separate identities would create friction and fragment credit balances.

**Why GitHub-only**: the target audience is tech-savvy developers interested in this experiment. Every target user has a GitHub account. Adding email signup widens the abuse surface for zero incremental reach.

### Node identity
- Node keypair generated on first `hexo register` (requires prior GitHub OAuth signup)
- `hexo register` authenticates against the user's Hexo account (API key or OAuth token)
- Coordinator issues a JWT node token tied to the account
- All node→coordinator calls authenticated with this token
- For shard-capable nodes: Tailscale device ID stored as secondary identity anchor — prevents re-registration after ban on same hardware

### Anti-Sybil for nodes
A GitHub account can register **up to 5 nodes** (config). Prevents one person from creating unlimited accounts to farm stake refunds or dodge bans. Additional nodes require `trusted` tier.

---

## Phases

### Phase 1 — Coordinator foundation
**Goal**: Unified auth, credit ledger, WebSocket tunnel manager, job queue, solo job proxy, monitoring.

- [ ] Scaffold FastAPI + PostgreSQL + Redis
- [ ] Database schema: `accounts`, `nodes`, `model_registry`, `shard_groups`, `shard_members`, `jobs` (partitioned), `verification_jobs`, `credits`, `credit_transactions`, `stakes`
- [ ] Monthly job partition management: pg_cron job to create next month's partition, drop partitions > 12 months
- [ ] Unified auth: GitHub OAuth flow → account + API key + node token + tier-based free credits
- [ ] GitHub reputation scoring: query account age, repos, activity → assign trust tier (`new`/`standard`/`trusted`)
- [ ] Cloudflare Turnstile integration on OAuth flow
- [ ] API key rotation endpoint: `GET /account/keys/rotate`
- [ ] Rate limiting: Redis sliding window (see API surface section)
- [ ] Node auth: `POST /nodes/register` → JWT node token; validate account owns < max_nodes; record capability mode, committed models, Tailscale IP (shard-capable only)
- [ ] Model registry: on node registration, resolve HF model ids → fetch metadata from HF API → assign pricing tier → cache in `model_registry`
- [ ] `GET /v1/models`: live registry of all models served by online nodes
- [ ] WebSocket tunnel: `WS /nodes/tunnel` — authenticate, hold connection, register in Redis by `node_id`
- [ ] Ping/pong keepalive every 30s: mark node offline after 3 missed pings (90s)
- [ ] Job queue: per-model Redis sorted sets; 30s timeout → 503; per-account concurrency limit (5, 10 for trusted); global queue cap (100/model) → 429
- [ ] Queue visibility endpoint: `GET /v1/queue` → pending count + estimated wait per model
- [ ] Solo job proxy: `POST /v1/chat/completions` → enqueue → pop next available solo node with matching model → send `inference` job via WS → relay SSE back
- [ ] Job multiplexing: `job_id` per job; demultiplex concurrent jobs per tunnel
- [ ] Token counting: parse `output_tokens` from completion message → apply tier-based credit split → update `jobs`, `credits`, `credit_transactions`
- [ ] Credit endpoints: `GET /account/balance` (includes recent transactions), `POST /account/stake`
- [ ] Credit reconciliation: pg_cron hourly job — verify `credits.balance` matches latest `credit_transactions.balance_after`; alert + pause dispatch on drift
- [ ] Headscale: deploy as Docker container, configure API access from coordinator
- [ ] Auth key endpoint: on `POST /nodes/register` for shard-capable nodes, coordinator calls Headscale API to generate a fresh ephemeral auth key, returns it in registration response
- [ ] TLS: Let's Encrypt + auto-renewal via Caddy reverse proxy in front of FastAPI (handles `wss://` and HTTPS)
- [ ] Monitoring: Prometheus metrics exporter (see Monitoring section), Grafana dashboards, PagerDuty alerting

### Phase 2 — Node CLI (solo mode)
**Goal**: Contributor runs one command, exo starts, tunnel opens, node is live. No Tailscale for solo mode.

- [ ] Scaffold Python CLI: `hexo start --model <hf_id>[,<hf_id>...] [--shard]`
- [ ] Prerequisite: `hexo login` authenticates against user's Hexo account (GitHub OAuth via browser redirect)
- [ ] On start: check exo installed (guide if not), validate 4-bit quantization for all models, download committed models, start exo as subprocess
- [ ] Node status `starting` until all models downloaded and loaded → `online`
- [ ] Register: `POST /nodes/register` with committed models (any valid MLX HF ids), hardware specs, capability mode → JWT node token
- [ ] If `--shard`: fetch Headscale auth key from registration response, run `tailscale up` silently, report Tailscale IP
- [ ] Open persistent WS to `wss://coordinator.hexo.dev/nodes/tunnel`
- [ ] Handle `inference` jobs: forward to `localhost:52415/v1/chat/completions`, stream chunks back
- [ ] Send completion message with `output_tokens`
- [ ] Runtime model management (no restart required):
  - `hexo add-model <hf_id>`: validate quantization, download in background, load into exo, report updated model list to coordinator
  - `hexo remove-model <hf_id>`: drain in-flight jobs for that model, unload, report updated model list
  - `hexo models`: list currently loaded models with status (loaded / downloading / draining)
- [ ] Auto-reconnect: exponential backoff (1s → 2s → 4s → max 60s)
- [ ] `hexo status`: credits earned, active jobs, mode, committed models, tunnel state, uptime (+ Headscale status if shard-capable)
- [ ] Graceful shutdown: deregister, close tunnel, stop exo (+ `tailscale logout` if shard-capable)

### Phase 3 — WAN shard groups
**Goal**: Shard-capable nodes across the internet jointly serve large models via direct Tailscale TCP. On-demand formation in v1.

- [ ] Coordinator PlacementEngine
  - On large model request with no solo node available: find shard-capable nodes covering model RAM
  - Pairwise RTT measurement between shard-capable nodes via periodic Tailscale ping (stored in Redis)
  - Hard constraint: max 2 nodes over WAN; 3+ only if all pairwise RTT < 5ms
  - Reject node pairs with RTT > 80ms
  - Score: minimize node count → lowest pairwise RTT → highest reputation
  - Assign layer ranges proportional to node RAM
  - Build peer list from `nodes.tailscale_ip`
  - Return estimated tok/s to consumer in SSE stream metadata
- [ ] Shard group formation (on-demand, v1)
  - Groups formed per job — no pre-warming. Consumer-facing timeout budget must account for formation overhead:
    - Shard job dispatch: ~100ms (WS message to each node)
    - exo peer connection: ~1–3s (TCP handshake over Tailscale + model shard initialization)
    - Total formation overhead: ~2–5s before first token
  - Consumer SSE stream sends `{"event": "status", "data": "forming shard group..."}` during formation
  - 30s queue timeout includes formation time — if formation fails within 15s, fall back to queue retry with different nodes
- [ ] Shard job dispatch via WS tunnel
  - Send `{"type": "shard", "job_id": "...", "layer_start": N, "layer_end": M, "position": K, "peers": [{tailscale_ip, port}]}` to each node
  - Nodes start exo in shard mode with assigned layers and Tailscale peer addresses
  - exo MLX Ring connects directly over Tailscale TCP — no coordinator relay
- [ ] Final node streams output back to coordinator via WS tunnel as usual
- [ ] Per-node credit split: `node_credit = contributor_share × (node_layers / total_layers)`
- [ ] Shard health: fail job + no credits if any node drops mid-inference
- [ ] Node CLI: handle `shard` job messages; configure exo with layer range + Tailscale peer IPs

### Phase 4 — Verification
**Goal**: Make cheating economically irrational. No coordinator-side model required.

- [ ] Statistical pre-filter (tokens/sec ceiling per model tier, duplicate output detection, length outliers)
- [ ] Verify job in node CLI: handle `{"type": "verify", ...}`
  - Send prompt + output as forced assistant continuation to exo with `logprobs=true`
  - Compute mean log-probability, return score to coordinator
- [ ] Verify job router in coordinator
  - On 20% of completed jobs: select different online node with **exact same HF model id** (not just tier)
  - Send via WS tunnel; enqueue for deferred verification if no matching node available
- [ ] Threshold calibration phase: run 1000+ verification jobs against known-good outputs from own nodes during testing. Establish per-model perplexity baseline (mean + stddev). Flag threshold = mean − 3σ. Store per model in `model_registry`
- [ ] Verifier reward: tier-based (6% of consumer price per verified job, from contributor share)
- [ ] Reputation: increment on verified-clean, decrement on flag
- [ ] Spot-check rate: 20% default → 5% for reputation > 100
- [ ] Stake/slash: 500 credits required on registration (from account balance); flag 1 → −100, flag 2 → −200 + probation (100% verify), flag 3 → remaining slashed + permanent ban
- [ ] Stake refund: 100% of remaining stake on voluntary deregister after 7-day cooldown
- [ ] Re-registration ban enforcement: block by keypair + Tailscale device ID + GitHub account
- [ ] Eligibility floor: reputation > 50 once network > 50 active nodes (config)

### Phase 5 — Dashboard
**Goal**: Public-facing page that makes the network look alive on launch day.

- [ ] Next.js app
- [ ] Live: node count, active jobs, tokens/min (Redis pub/sub → WebSocket)
- [ ] Leaderboard: top contributors by credits earned (all time + 7d)
- [ ] Network stats: total tokens generated, nodes, users, active shard groups
- [ ] Per-node public profile: model, mode, uptime, jobs completed
- [ ] Map of nodes with active shard groups indicated

### Phase 6 — Cold start execution
**Goal**: Network is functional and visibly active on day 1.

- [ ] Run 5–10 Mac Mini / Mac Studio nodes yourself (mix of solo and shard-capable, covering popular models across tiers S/M/L)
- [ ] Activate launch credit split: coordinator takes 5% for first 30 days (config flag)
- [ ] Credit bonus: first 100 registered nodes get 10× credit bonus for 30 days
- [ ] Signup free credits: GitHub OAuth → tier-based (10K new / 100K standard+trusted). Same account used for consuming and contributing
- [ ] Messaging: "Sign up, get free credits to try the API. Contribute your idle Mac to earn more. No payment, no subscription — pure compute exchange."
- [ ] Docs: "How to connect Continue.dev / Aider / Cursor to Hexo"
- [ ] HN launch: "I built a compute co-op for Apple Silicon — contribute idle Mac compute, earn LLM tokens"

---

## Tech stack

| Component | Tech |
|---|---|
| Coordinator API | Python 3.12 + FastAPI |
| Job queue / live node state | Redis |
| Credit ledger / nodes / jobs | PostgreSQL |
| Node inference | exo (Apple MLX) |
| Node CLI | Python 3.12 (wraps exo + Tailscale client) |
| Node↔Coordinator control | WebSocket (node-initiated, persistent) |
| Node↔Node shard data | exo MLX Ring over Headscale direct TCP |
| Headscale (mesh control) | Self-hosted, Docker, unlimited devices |
| DERP relay fallback | Tailscale public DERP (no self-hosting required) |
| Dashboard | Next.js 14 |
| Auth | GitHub OAuth + Cloudflare Turnstile (unified for consumers + contributors) |
| TLS / reverse proxy | Caddy (auto Let's Encrypt + renewal, handles HTTPS + WSS) |
| Monitoring | Prometheus + Grafana + PagerDuty |
| Deployment | Docker Compose (Caddy + coordinator + Redis + Postgres + Headscale + Prometheus + Grafana) |

---

## Database schema

```sql
accounts (
  id uuid PRIMARY KEY,
  api_key_hash text UNIQUE,
  node_token_hash text UNIQUE,      -- for node registration auth
  github_id text UNIQUE,            -- GitHub OAuth user id
  github_username text,
  github_account_age_days int,      -- at time of registration
  trust_tier text,                  -- new | standard | trusted
  max_nodes int DEFAULT 5,          -- max nodes this account can register
  created_at timestamptz
)

nodes (
  id uuid PRIMARY KEY,
  account_id uuid REFERENCES accounts,  -- owner account (GitHub identity)
  token_hash text,
  committed_models jsonb,           -- ["mlx-community/Qwen2.5-Coder-7B-Instruct-4bit", ...]
  hardware_spec jsonb,              -- {ram_gb, chip, unified_memory}
  capability_mode text,             -- solo | shard-capable
  tailscale_ip text,                -- 100.x.x.x, NULL for solo nodes
  tailscale_device_id text,         -- secondary identity anchor for ban enforcement
  status text,                      -- starting | online | offline | probation | banned
  tunnel_connected bool,
  reputation_score int DEFAULT 0,
  stake_balance int DEFAULT 0,      -- denormalized from stakes table
  flag_count int DEFAULT 0,         -- running total of confirmed flags
  is_verifier_eligible bool DEFAULT true,
  verifier_jobs_completed int DEFAULT 0,
  registered_at timestamptz,
  last_ping_at timestamptz
)
-- GIN index for model routing queries:
CREATE INDEX idx_nodes_committed_models ON nodes USING GIN (committed_models);
CREATE INDEX idx_nodes_status ON nodes (status) WHERE status = 'online';

-- Model metadata cache (populated from HF API on first encounter)
model_registry (
  hf_id text PRIMARY KEY,           -- e.g. "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
  parameter_count bigint,
  quantization text,                -- 4bit | 8bit | fp16
  estimated_ram_gb float,
  pricing_tier text,                -- S | M | L | XL | XXL
  credits_per_1k_tokens int,        -- consumer price
  first_seen_at timestamptz,
  node_count int DEFAULT 0          -- denormalized: online nodes serving this model
)

shard_groups (
  id uuid PRIMARY KEY,
  model text,
  total_layers int,
  status text,                      -- forming | active | completed | failed
  created_at timestamptz
)

shard_members (
  id uuid PRIMARY KEY,
  shard_group_id uuid REFERENCES shard_groups,
  node_id uuid REFERENCES nodes,
  position int,                     -- order in pipeline (0 = first)
  layer_start int,
  layer_end int,
  credits_earned int                -- set on job completion
)

-- Partitioned by month for retention management
jobs (
  id uuid NOT NULL,
  account_id uuid REFERENCES accounts,   -- consumer
  node_id uuid REFERENCES nodes,          -- null for shard jobs
  shard_group_id uuid REFERENCES shard_groups, -- null for solo jobs
  model text,
  prompt_tokens int,
  output_tokens int,
  credits_consumer int,
  credits_contributor int,          -- total across all nodes
  credits_coordinator int,
  status text,                      -- queued | pending | running | completed | failed | timeout
  queued_at timestamptz NOT NULL,   -- when job entered the queue (partition key)
  started_at timestamptz,
  completed_at timestamptz,
  PRIMARY KEY (id, queued_at)
) PARTITION BY RANGE (queued_at);
-- Create partitions monthly: jobs_2026_01, jobs_2026_02, ...
-- Retention: drop partitions older than 12 months via pg_cron
-- Archive to S3/cold storage before drop if audit trail needed

verification_jobs (
  id uuid PRIMARY KEY,
  inference_job_id uuid,            -- logical FK to jobs (cross-partition)
  inference_job_queued_at timestamptz, -- needed to locate job in partition
  verifier_node_id uuid REFERENCES nodes,
  model_hf_id text,                 -- exact model used for verification
  perplexity_score float,
  perplexity_threshold float,       -- threshold at time of verification
  verdict text,                     -- approved | flagged | pending
  reward_credits int,
  created_at timestamptz
)

credits (
  account_id uuid PRIMARY KEY REFERENCES accounts,  -- one row per account
  balance int DEFAULT 0,
  total_earned int DEFAULT 0,
  total_spent int DEFAULT 0,
  total_staked int DEFAULT 0
)

-- Append-only audit log for credit movements
credit_transactions (
  id bigserial PRIMARY KEY,
  account_id uuid REFERENCES accounts,
  amount int,                       -- positive = credit, negative = debit
  tx_type text,                     -- signup_bonus | job_earned | job_spent | stake_lock
                                    -- stake_refund | stake_slash | verify_reward | coordinator_fee
  job_id uuid,                      -- nullable, links to originating job
  node_id uuid,                     -- nullable, links to originating node
  balance_after int,                -- snapshot for fast reconciliation
  created_at timestamptz DEFAULT now()
)
CREATE INDEX idx_credit_tx_account ON credit_transactions (account_id, created_at);
-- Reconciliation: credits.balance must equal latest credit_transactions.balance_after
-- Drift detection: credits.balance != total_earned - total_spent - total_staked

stakes (
  id uuid PRIMARY KEY,
  node_id uuid REFERENCES nodes,
  account_id uuid REFERENCES accounts,
  amount int,
  status text,                      -- active | slashed | withdrawn
  created_at timestamptz
)
-- credits.total_staked = SUM(amount) WHERE account_id = ? AND status = 'active'
```

---

## API surface

### Auth (unified)
```
GET    /auth/github             GitHub OAuth redirect
GET    /auth/github/callback    OAuth callback → API key + node token + free credits (tier-based)
```

### Consumer
```
POST   /v1/chat/completions     OpenAI-compatible — solo or shard group
GET    /v1/models               Live model registry (all models served by online nodes)
GET    /v1/queue                Queue depth + estimated wait per model
GET    /account/balance         Credit balance + transaction history
GET    /account/keys/rotate     Rotate API key (invalidates old key)
```

### Node
```
POST   /nodes/register          Register node under account, get JWT + Headscale auth key (if shard)
WS     /nodes/tunnel            Control tunnel — all control traffic
```

### Public
```
GET    /stats                   Network-wide stats
GET    /leaderboard             Top contributors
GET    /nodes/{id}              Public node profile
```

### Rate limiting
| Endpoint | Limit | Scope |
|---|---|---|
| `POST /v1/chat/completions` | 30 req/min | per API key |
| `GET /v1/*` (read) | 120 req/min | per API key |
| `GET /auth/github` | 10 req/min | per IP |
| `POST /nodes/register` | 5 req/hour | per account |

Rate limits enforced via Redis sliding window. Returns `429 Too Many Requests` with `Retry-After` header. Trust tier `trusted` gets 2× consumer rate limits.

---

## Monitoring and alerting

### Prometheus metrics (coordinator)
Exported on `/metrics` endpoint:

| Metric | Type | Description |
|---|---|---|
| `hexo_nodes_online` | gauge | Online nodes, labeled by model tier and capability mode |
| `hexo_jobs_total` | counter | Jobs by status (completed, failed, timeout), model tier |
| `hexo_job_duration_seconds` | histogram | End-to-end job latency by model tier and mode (solo/shard) |
| `hexo_queue_depth` | gauge | Pending jobs per model tier |
| `hexo_queue_wait_seconds` | histogram | Time from queued to started |
| `hexo_tokens_generated_total` | counter | Output tokens by model tier |
| `hexo_tokens_per_second` | gauge | Current throughput per model tier |
| `hexo_credits_balance` | gauge | Total credit balance (consumer vs node) |
| `hexo_credits_flow` | counter | Credits moved by type (earned, spent, staked, slashed) |
| `hexo_verification_verdicts` | counter | Verification outcomes (approved, flagged) |
| `hexo_shard_group_failures` | counter | Shard group failures by reason (node_drop, timeout) |
| `hexo_ws_connections` | gauge | Active WebSocket tunnel count |
| `hexo_node_ping_rtt_ms` | histogram | Coordinator→node WS ping RTT |
| `hexo_shard_peer_rtt_ms` | histogram | Pairwise shard node RTT via Tailscale |

### Alerting rules (PagerDuty / Slack)

| Alert | Condition | Severity |
|---|---|---|
| No nodes online | `hexo_nodes_online == 0` for 2m | critical |
| High job failure rate | `rate(hexo_jobs_total{status="failed"}) / rate(hexo_jobs_total) > 0.1` for 5m | warning |
| Queue backed up | `hexo_queue_depth > 50` for any tier for 5m | warning |
| Credit ledger drift | scheduled reconciliation `SUM(credits.balance) != SUM(earned) - SUM(spent)` | critical |
| Coordinator memory/CPU | standard system metrics thresholds | warning/critical |
| Headscale unreachable | health check failure for 1m | critical |
| Verification flag spike | `rate(hexo_verification_verdicts{verdict="flagged"}) > 5/hour` | warning |

### Grafana dashboards
- **Operations**: node count, job throughput, queue depth, error rate, latency percentiles
- **Economics**: credit flow, earnings distribution, stake/slash activity
- **Network health**: WS tunnel stability, shard peer RTT distribution, Headscale status

### Credit ledger reconciliation
Scheduled job (every 1h): verify `SUM(credits.balance)` matches `SUM(total_earned) - SUM(total_spent)` across all accounts. Any drift → alert + auto-pause job dispatch until investigated.

---

## v2 milestones

- **QUIC direct P2P**: replace Headscale + Tailscale client with QUIC-based direct transport to remove the Tailscale client install requirement from contributors; UDP-based, same NAT traversal reliability, zero external dependency
- **CUDA / NVIDIA support**: add llama.cpp RPC or vLLM backend for Linux + RTX nodes
- **Speculative/lookahead decoding for WAN sharding**: generate 3–5 candidate tokens per round-trip instead of 1, amortizing WAN latency by 3–5×. Research: PipeDec, FlowSpec. This is the primary path to making WAN shard groups competitive with solo inference
- **Model switching**: coordinator-initiated dynamic model load/unload on nodes (see Model switching v2 above)
- **Multi-verifier consensus**: upgrade single-verifier to 2-of-3 majority once network has 50+ active nodes
- **Pre-warmed shard groups**: coordinator proactively forms standby shard groups for popular large models. Shard-capable node pairs with low RTT maintain a warm exo peer connection. On incoming job, skip formation overhead (~2-5s → ~100ms). Warm groups expire after 5 minutes of inactivity. Reduces consumer-perceived latency for shard jobs significantly
- **Coordinator high availability**: active-passive failover with shared PostgreSQL and Redis Sentinel. Design:
  - PostgreSQL: managed instance with automated failover (e.g., RDS Multi-AZ or Patroni)
  - Redis: Redis Sentinel (3 nodes) for automatic master promotion
  - Coordinator: 2 instances behind a load balancer. Only one holds active WebSocket tunnels (leader). Standby monitors leader via heartbeat. On leader failure, standby promotes within 10s, nodes reconnect via exponential backoff (already implemented)
  - **Quorum period on failover**: after leader promotion, wait 30s before dispatching shard jobs (require >80% of previously-known nodes to reconnect). Solo jobs resume immediately as individual nodes reconnect — no quorum needed
  - Headscale: stateless from the coordinator's perspective (node re-auth on reconnect uses same auth key mechanism)
  - **Blast radius**: leader failure causes ~10-30s of job interruption. In-flight jobs fail (no credits charged). Nodes auto-reconnect. No data loss (PostgreSQL is the source of truth for credits)

## Explorations

- **On-chain credits**: migrate credit ledger to Solana SPL token + payment channels if the network proves the model works and participants want portability/transparency. Not a revenue play — a trust mechanism
- **Fiat on-ramp/off-ramp**: only if the community requests it. The system is designed to work without money. Adding fiat changes incentives — approach with caution
