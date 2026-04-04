#!/usr/bin/env bash

set -euo pipefail

REPO_RAW_BASE_URL="${TOKNX_INSTALL_RAW_BASE_URL:-https://raw.githubusercontent.com/mguegnol/toknx/main}"
PYTHON_VERSION="3.12"
MLX_LM_PACKAGE="mlx-lm==0.31.1"

log() {
  printf '==> %s\n' "$1" >&2
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

require_metal_toolchain() {
  local output

  if output="$(xcrun metal -v 2>&1)"; then
    return
  fi

  if [[ "$output" == *"missing Metal Toolchain"* ]]; then
    cat >&2 <<'EOF'
error: mlx-lm requires the Apple Metal Toolchain.

Install it with:
  xcodebuild -downloadComponent MetalToolchain

Then rerun the installer.
EOF
    exit 1
  fi

  fail "unable to validate the Apple Metal Toolchain: ${output}"
}

validate_mlx_lm_runtime() {
  command -v mlx_lm.server >/dev/null 2>&1 || fail "mlx_lm.server was not installed"

  local output
  if ! output="$(PAGER=cat mlx_lm.server --help 2>&1)"; then
    cat >&2 <<EOF
error: mlx-lm installed, but the runtime is not usable.

mlx_lm.server --help failed with:
${output}
EOF
    exit 1
  fi
}

download_node_cli() {
  local tmp_dir destination relative_path
  tmp_dir="$(mktemp -d)"
  mkdir -p "${tmp_dir}/apps/node-cli/src/toknx_node"

  while IFS= read -r relative_path; do
    destination="${tmp_dir}/${relative_path}"
    mkdir -p "$(dirname "$destination")"
    curl -fsSL "${REPO_RAW_BASE_URL}/${relative_path}" -o "$destination" \
      || fail "failed to download ${relative_path}"
  done <<'EOF'
apps/node-cli/pyproject.toml
apps/node-cli/src/toknx_node/__init__.py
apps/node-cli/src/toknx_node/auth_flow.py
apps/node-cli/src/toknx_node/cli.py
apps/node-cli/src/toknx_node/client.py
apps/node-cli/src/toknx_node/config.py
apps/node-cli/src/toknx_node/runner.py
EOF

  [[ -f "${tmp_dir}/apps/node-cli/pyproject.toml" ]] || fail "node CLI source not found"

  printf '%s\n' "$tmp_dir"
}

main() {
  require_cmd curl
  require_cmd uv

  if [[ "$(uname -s)" != "Darwin" ]]; then
    log "Non-macOS host detected. toknX nodes are intended for Apple Silicon Macs."
  fi

  local tmp_dir tool_bin_dir
  tmp_dir="$(download_node_cli)"
  trap "rm -rf '$tmp_dir'" EXIT

  log "Installing Python ${PYTHON_VERSION} with uv"
  uv python install "$PYTHON_VERSION" >/dev/null

  log "Installing toknX CLI"
  uv tool install \
    --python "$PYTHON_VERSION" \
    --force \
    "${tmp_dir}/apps/node-cli" >/dev/null

  require_metal_toolchain

  log "Installing mlx-lm"
  uv tool install \
    --python "$PYTHON_VERSION" \
    --force \
    "$MLX_LM_PACKAGE" >/dev/null

  validate_mlx_lm_runtime

  tool_bin_dir="$(uv tool dir --bin)"

  log "toknX CLI installed"
  printf 'tool bin dir: %s\n' "$tool_bin_dir"

  if ! command -v toknx >/dev/null 2>&1 || ! command -v mlx_lm.server >/dev/null 2>&1; then
    cat <<EOF

Add uv's tool bin directory to your PATH if needed:
  export PATH="${tool_bin_dir}:\$PATH"
EOF
  fi

  cat <<'EOF'

Next steps:
  1. toknx login
  2. toknx start --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit
EOF
}

main "$@"
