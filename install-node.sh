#!/usr/bin/env bash

set -euo pipefail

TOKNX_INSTALL_ARCHIVE_URL="${TOKNX_INSTALL_ARCHIVE_URL:-https://github.com/toknx/toknx/archive/refs/heads/main.tar.gz}"
TOKNX_TMP_DIR="${TOKNX_TMP_DIR:-}"
TOKNX_PYTHON_VERSION="${TOKNX_PYTHON_VERSION:-3.12}"
TOKNX_MLX_LM_PACKAGE_SPEC="${TOKNX_MLX_LM_PACKAGE_SPEC:-mlx-lm==0.31.1}"

log() {
  printf '==> %s\n' "$1"
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

validate_mlx_lm_runtime() {
  if ! command -v mlx_lm.server >/dev/null 2>&1; then
    fail "mlx_lm.server was not installed"
  fi

  local help_output
  if ! help_output="$(PAGER=cat mlx_lm.server --help 2>&1)"; then
    cat >&2 <<EOF
error: mlx-lm installed, but the runtime is not usable.

mlx_lm.server --help failed with:
${help_output}
EOF
    exit 1
  fi
}

require_metal_toolchain() {
  local probe_output

  if probe_output="$(xcrun metal -v 2>&1)"; then
    return
  fi

  if [[ "$probe_output" == *"missing Metal Toolchain"* ]]; then
    cat >&2 <<'EOF'
error: mlx-lm requires the Apple Metal Toolchain, but it is not installed.

Install it with:
  xcodebuild -downloadComponent MetalToolchain

Then rerun:
  ./install-node.sh
EOF
    exit 1
  fi

  fail "unable to validate the Apple Metal Toolchain: ${probe_output}"
}

detect_source_dir() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "${script_dir}/apps/node-cli/pyproject.toml" ]]; then
    printf '%s\n' "$script_dir"
    return
  fi
  printf '%s\n' ""
}

download_source_dir() {
  local tmp_root archive_path extracted_dir
  if [[ -n "$TOKNX_TMP_DIR" ]]; then
    tmp_root="$TOKNX_TMP_DIR"
    mkdir -p "$tmp_root"
  else
    tmp_root="$(mktemp -d)"
  fi
  archive_path="${tmp_root}/toknx.tar.gz"
  extracted_dir="${tmp_root}/src"
  mkdir -p "$extracted_dir"

  log "Downloading ToknX source archive"
  curl -fsSL "$TOKNX_INSTALL_ARCHIVE_URL" -o "$archive_path"
  tar -xzf "$archive_path" -C "$extracted_dir"

  find "$extracted_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1
}

main() {
  require_cmd curl
  require_cmd tar
  require_cmd uv

  if [[ "$(uname -s)" != "Darwin" ]]; then
    log "Non-macOS host detected. ToknX nodes are intended for Apple Silicon Macs."
  fi

  local source_dir tool_bin_dir local_source_dir=0
  source_dir="$(detect_source_dir)"
  if [[ -z "$source_dir" ]]; then
    source_dir="$(download_source_dir)"
  else
    local_source_dir=1
  fi

  [[ -f "${source_dir}/apps/node-cli/pyproject.toml" ]] || fail "node CLI source not found"

  log "Installing Python ${TOKNX_PYTHON_VERSION} with uv"
  uv python install "$TOKNX_PYTHON_VERSION" >/dev/null

  log "Installing ToknX CLI"
  if [[ "$local_source_dir" == "1" ]]; then
    uv tool install \
      --python "$TOKNX_PYTHON_VERSION" \
      --editable \
      --force \
      "${source_dir}/apps/node-cli" >/dev/null
  else
    uv tool install \
      --python "$TOKNX_PYTHON_VERSION" \
      --force \
      "${source_dir}/apps/node-cli" >/dev/null
  fi

  require_metal_toolchain
  log "Installing mlx-lm"
  uv tool install \
    --python "$TOKNX_PYTHON_VERSION" \
    --force \
    "$TOKNX_MLX_LM_PACKAGE_SPEC" >/dev/null
  validate_mlx_lm_runtime

  tool_bin_dir="$(uv tool dir --bin)"

  log "ToknX CLI installed"
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
