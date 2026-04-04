#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${TOKNX_BASE_URL:-http://localhost/api}"
MODEL_ID="${TOKNX_MODEL_ID:-mlx-community/Qwen2.5-Coder-7B-Instruct-4bit}"
RUN_ID="${TOKNX_SMOKE_RUN_ID:-smoke-$(date +%s)}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd docker
require_cmd python3

compose() {
  docker compose -f docker-compose.yml "$@"
}

json_get() {
  local payload="$1"
  local expr="$2"
  python3 - "$payload" "$expr" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expr = sys.argv[2].split(".")
value = payload
for part in expr:
    if part.isdigit():
        value = value[int(part)]
    else:
        value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value))
else:
    print(value)
PY
}

echo "==> Checking API health"
health_payload="$(curl -fsS "${BASE_URL}/healthz")"
echo "$health_payload"

echo "==> Creating dev account ${RUN_ID}"
auth_payload="$(curl -fsS "${BASE_URL}/auth/github/callback?code=dev:${RUN_ID}")"
api_key="$(json_get "$auth_payload" "api_key")"
node_token="$(json_get "$auth_payload" "node_token")"
github_username="$(json_get "$auth_payload" "github_username")"
echo "account=@${github_username}"

echo "==> Registering mock node"
register_payload="$(curl -fsS "${BASE_URL}/nodes/register" \
  -H "Authorization: Bearer ${node_token}" \
  -H "Content-Type: application/json" \
  --data "{\"committed_models\":[\"${MODEL_ID}\"],\"hardware_spec\":{\"chip\":\"Smoke Test\",\"ram_gb\":64},\"capability_mode\":\"solo\"}")"
node_id="$(json_get "$register_payload" "node_id")"
tunnel_token="$(json_get "$register_payload" "tunnel_token")"
echo "node_id=${node_id}"

cleanup() {
  echo "==> Cleaning up node ${node_id}"
  curl -fsS -X POST "${BASE_URL}/nodes/${node_id}/deregister" \
    -H "Authorization: Bearer ${node_token}" >/dev/null
}

trap cleanup EXIT

echo "==> Starting temporary mock tunnel"
compose exec -T coordinator python -c "import asyncio, json, websockets; token='${tunnel_token}'; node_id='${node_id}';
async def main():
    async with websockets.connect(f'ws://localhost:8000/nodes/tunnel?token={token}', max_size=None) as ws:
        while True:
            message=json.loads(await ws.recv())
            if message.get('type') == 'ping':
                await ws.send(json.dumps({'type': 'pong', 'node_id': node_id}))
            elif message.get('type') == 'inference':
                job_id = message['job_id']
                await ws.send(json.dumps({'type': 'accepted', 'job_id': job_id}))
                chunks = ['toknX ', 'smoke ', 'test.']
                for index, chunk in enumerate(chunks, start=1):
                    await ws.send(json.dumps({'type': 'token', 'job_id': job_id, 'chunk': chunk, 'output_tokens': index}))
                    await asyncio.sleep(0.05)
                await ws.send(json.dumps({'type': 'completed', 'job_id': job_id, 'output_tokens': 3}))
                await asyncio.sleep(0.1)
                return
asyncio.run(main())" >/tmp/toknx-smoke-tunnel.log 2>&1 &
tunnel_pid=$!

sleep 1

echo "==> Sending completion request"
completion_payload="$(curl -fsS "${BASE_URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${api_key}" \
  -H "Content-Type: application/json" \
  --data "{\"model\":\"${MODEL_ID}\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"Say hello from toknX smoke test.\"}]}")"
assistant_text="$(json_get "$completion_payload" "choices.0.message.content")"
echo "$completion_payload"

if [[ "$assistant_text" != "toknX smoke test." ]]; then
  echo "unexpected assistant response: ${assistant_text}" >&2
  exit 1
fi

wait "$tunnel_pid"

echo "==> Checking stats"
stats_payload="$(curl -fsS "${BASE_URL}/stats")"
tokens_total="$(json_get "$stats_payload" "tokens_total")"
echo "$stats_payload"

if [[ "$tokens_total" -lt 3 ]]; then
  echo "expected tokens_total >= 3, got ${tokens_total}" >&2
  exit 1
fi

echo "==> Checking balance and transactions"
balance_payload="$(curl -fsS "${BASE_URL}/account/balance" -H "Authorization: Bearer ${api_key}")"
echo "$balance_payload"
python3 - "$balance_payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
types = {tx["type"] for tx in payload["transactions"]}
required = {"signup_bonus", "stake_lock", "job_spent", "job_earned"}
missing = sorted(required - types)
if missing:
    raise SystemExit(f"missing expected transaction types: {', '.join(missing)}")
PY

echo "==> Smoke test passed"
