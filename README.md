# TOKNX

toknX is a distributed inference network for Apple Silicon.

- Run a Mac as a node
- Serve `mlx-lm` models
- Earn credits
- Spend those credits through an OpenAI-compatible API

Production URLs:

- Dashboard: `https://toknx.co`
- API: `https://api.toknx.co`

## How It Works

1. Install the CLI
2. Log in with GitHub
3. toknX gives you an API key and a node token
4. Start a node from your Mac with one or more models
5. toknX routes inference jobs to online nodes
6. Credits move from the consumer to the node operator

## Requirements

- Apple Silicon Mac
- Xcode and the Apple Metal Toolchain
- `uv`

Install the Metal Toolchain if needed:

```bash
xcodebuild -downloadComponent MetalToolchain
```

## Install the CLI

Recommended:

```bash
curl -fsSL https://toknx.co/install-node.sh | bash
```

If `toknx` is not on your `PATH` after install:

```bash
export PATH="$(uv tool dir --bin):$PATH"
```

## Login

Run:

```bash
toknx login
```

This opens your browser, completes GitHub OAuth, and prints your API key once.

New accounts currently receive `1000` free credits.

The CLI stores your credentials locally and uses them for:

- API requests with your `api_key`
- node registration with your `node_token`

Check your current account and node state with:

```bash
toknx status
```

## Start A Node

Start a node with one model:

```bash
toknx start --model mlx-community/Llama-3.2-1B-Instruct-4bit
```

Start a node with multiple models:

```bash
toknx start --model mlx-community/Llama-3.2-1B-Instruct-4bit,mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
```

What `toknx start` does:

1. Registers your node with toknX
2. Locks the node stake from your account balance
3. Starts local `mlx-lm` servers
4. Reuses the Hugging Face model cache when available
5. Connects your node to the coordinator
6. Runs in the background

Useful commands:

```bash
toknx status
toknx stop
```

## Contributing Compute

Running a node is the main way to contribute to toknX.

Notes:

- only Apple Silicon nodes are supported
- node registration checks whether declared models fit in available RAM
- starting a node locks `500` credits as stake
- the stake is refunded when you stop the node cleanly

## Pricing Model


For a job:

```text
cost = output_tokens * credits_per_1k_tokens / 1000
```

Coordinator fee:

- toknX keeps `10%`
- the serving node earns `90%`


## Credit Per Model Size

toknX estimates model RAM from parameter count and quantization, then assigns a pricing tier.

| Estimated RAM | Tier | Credits / 1K output tokens |
| --- | --- | --- |
| `< 8 GB` | `S` | `1` |
| `< 16 GB` | `M` | `2` |
| `< 32 GB` | `L` | `4` |
| `< 64 GB` | `XL` | `8` |
| `>= 64 GB` | `XXL` | `16` |

Examples:

- `mlx-community/Llama-3.2-1B-Instruct-4bit` is in the `S` tier
- larger 7B and 14B models usually land in higher tiers depending on quantization

List currently available live models:

```bash
curl https://api.toknx.co/v1/models
```

## Use The API Key

After `toknx login`, use the printed API key with the OpenAI-compatible API.

Example:

```bash
export TOKNX_API_KEY=toknx_api_...
```

Check your balance:

```bash
curl https://api.toknx.co/account/balance \
  -H "Authorization: Bearer $TOKNX_API_KEY"
```

Send a completion request:

```bash
curl https://api.toknx.co/v1/chat/completions \
  -H "Authorization: Bearer $TOKNX_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{
    "model": "mlx-community/Llama-3.2-1B-Instruct-4bit",
    "stream": false,
    "messages": [
      { "role": "user", "content": "Reply with exactly: hello" }
    ]
  }'
```

## Local Override For Testing

The production CLI uses `https://api.toknx.co` by default.

To point the CLI at a local or staging coordinator:

```bash
TOKNX_API_BASE_URL=http://localhost/api toknx login
TOKNX_API_BASE_URL=http://localhost/api toknx start --model mlx-community/Llama-3.2-1B-Instruct-4bit
```

## In Progress

Planned next features:

- add support for llama.cpp and GGUF models
- WAN model sharding for models that do not fit on a single node
- verification and stake slashing for untrusted or faulty nodes
- dynamic model load and unload on nodes, without full restart


## For Maintainers

This repository also contains:

- `apps/coordinator`: FastAPI coordinator
- `apps/node-cli`: toknX CLI
- `apps/dashboard`: SvelteKit dashboard
