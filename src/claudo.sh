#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  claudo — Claude Code via DigitalOcean Gradient AI                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# TEMPLATE FILE — edit this file and run 'make build' to regenerate bin/claudo.
# Do NOT edit bin/claudo directly; it is assembled from src/ by scripts/build.sh.
#
# WHAT THIS SCRIPT DOES
# ─────────────────────
# claudo lets you run Claude Code (Anthropic's CLI tool) against DigitalOcean's
# Gradient AI inference endpoint instead of Anthropic's own API. It works by
# spinning up a local LiteLLM proxy server that translates between Claude Code's
# native Anthropic API format and DO's OpenAI-compatible API format, then
# launching Claude Code pointed at that local proxy.
#
# WHY IT EXISTS
# ─────────────
# Claude Code expects to talk to the Anthropic API (api.anthropic.com), but
# DigitalOcean's Gradient AI service exposes Claude models via an OpenAI-
# compatible endpoint. LiteLLM bridges this gap by accepting Anthropic-format
# requests from Claude Code and forwarding them as OpenAI-format requests to DO.
#
# ARCHITECTURE
# ────────────
#                  ┌────────────┐         ┌────────────┐         ┌────────────┐
#                  │ Claude Code│  ──▶    │  LiteLLM   │  ──▶    │  DO Grad.  │
#                  │   (CLI)    │ Anthropic│   Proxy    │ OpenAI  │  AI API    │
#                  │            │  format  │ (localhost)│ format  │            │
#                  └────────────┘         └────────────┘         └────────────┘
#                       ▲                   Port 4100+             inference.
#                       │                   127.0.0.1             do-ai.run/v1
#                  ANTHROPIC_BASE_URL
#                  pointed at proxy
#
# WHAT HAPPENS ON EACH RUN
# ────────────────────────
#   1. Loads config (DO API key) from ~/.config/claudo/config.env
#   2. Discovers available Claude models from the DO /v1/models endpoint
#      (cached for 24h in ~/.config/claudo/models_cache.json)
#   3. Generates a LiteLLM config YAML that maps Claude Code model names
#      (e.g. "claude-sonnet-4-5") to DO model IDs (e.g. "anthropic-claude-4.5-sonnet")
#   4. Finds an available port in the 4100-4200 range
#   5. Starts a LiteLLM proxy server on that port (backgrounded)
#   6. Waits for the proxy health check to pass (up to 30s)
#   7. Sets ANTHROPIC_BASE_URL to point at the local proxy
#   8. Launches `claude` with all user-provided arguments
#   9. On exit, cleanly shuts down the proxy (SIGTERM → SIGKILL)
#
# MODEL NAME MAPPING
# ──────────────────
# DO model IDs look like "anthropic-claude-4.5-sonnet" but Claude Code requests
# models like "claude-sonnet-4-5" or "claude-4-5-sonnet". The script dynamically
# generates all plausible name permutations for each DO model and creates
# fallback aliases so that any model Claude Code might request gets routed to
# the best available match in that family (sonnet/opus/haiku).
#
# PYTHON WRAPPER PATCHES
# ──────────────────────
# The script generates a Python wrapper (litellm_wrapper.py) that monkey-patches
# three known LiteLLM issues before starting the proxy:
#   - uvicorn's uvloop dependency (broken on Python 3.14+) → forces asyncio
#   - Anthropic pass-through adapter forwarding unsupported params like
#     "context_management" → strips them before forwarding to DO
#   - OpenAI Responses API routing for thinking/extended thinking params →
#     skipped for DO models (DO doesn't support the Responses API)
#
# MULTI-INSTANCE SUPPORT
# ──────────────────────
# Multiple claudo sessions can run concurrently. Each gets its own port and
# PID file in ~/.config/claudo/instances/. Stale PID files from crashed
# sessions are automatically cleaned up.
#
# DEPENDENCIES
# ────────────
#   - bash (4.0+)
#   - python3 (for LiteLLM and config generation)
#   - node (for Claude Code CLI)
#   - claude (npm install -g @anthropic-ai/claude-code)
#   - litellm[proxy] (auto-installed into a venv on first run)
#   - curl (for API calls and health checks)
#
# FILES AND DIRECTORIES
# ─────────────────────
#   ~/.config/claudo/
#   ├── config.env              API key (chmod 600)
#   ├── models_cache.json       Cached /v1/models response (24h TTL)
#   ├── litellm_config.yaml     Auto-generated LiteLLM proxy config
#   ├── litellm_wrapper.py      Python wrapper with monkey-patches
#   ├── auth.py                 Claude Code auth bootstrap helper
#   ├── venv/                   Python venv with LiteLLM installed
#   ├── instances/
#   │   └── proxy-{port}.pid    PID files for running proxy instances
#   └── logs/
#       └── proxy-{port}.log    Stdout/stderr from proxy processes
#
# COMMANDS
# ────────
#   claudo                      Start interactive Claude session via DO
#   claudo <claude args>        Pass arguments through to claude CLI
#   claudo setup                Configure API key, install deps, discover models
#   claudo status               Show running proxy instances with uptime
#   claudo stop-all             Kill all running proxy instances
#   claudo models               Show DO model → Claude Code model name mappings
#   claudo version              Print version
#   claudo help                 Print usage help
#
# ENVIRONMENT VARIABLES (set automatically for Claude Code)
# ─────────────────────
#   ANTHROPIC_BASE_URL          http://127.0.0.1:{port} (local proxy)
#   ANTHROPIC_AUTH_TOKEN        Proxy master key (for LiteLLM auth)
#   DO_GRADIENT_API_KEY         User's DigitalOcean Gradient AI API key
#
# INSTALLATION
# ────────────
#   Place this script in ~/.local/bin/ (which must be in your $PATH):
#     mkdir -p ~/.local/bin
#     cp claudo ~/.local/bin/claudo
#     chmod +x ~/.local/bin/claudo
#
# FIRST-TIME SETUP
# ────────────────
#   1. Get a DO Gradient AI API key from DigitalOcean
#   2. Run: claudo setup
#   3. Paste your API key when prompted
#   4. Run: claudo
#
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

readonly VERSION="1.0.0"
readonly CONFIG_DIR="${HOME}/.config/claudo"
readonly CONFIG_FILE="${CONFIG_DIR}/config.env"
readonly MODELS_CACHE="${CONFIG_DIR}/models_cache.json"
readonly LITELLM_CONFIG="${CONFIG_DIR}/litellm_config.yaml"
readonly VENV_DIR="${CONFIG_DIR}/venv"
readonly LITELLM_WRAPPER="${CONFIG_DIR}/litellm_wrapper.py"
readonly AUTH_SCRIPT="${CONFIG_DIR}/auth.py"
readonly INSTANCES_DIR="${CONFIG_DIR}/instances"
readonly LOGS_DIR="${CONFIG_DIR}/logs"
readonly PORT_MIN=4100
readonly PORT_MAX=4200
readonly HEALTH_TIMEOUT=30
readonly DO_API_BASE="https://inference.do-ai.run"
readonly PROXY_MASTER_KEY="sk-claudo-$(openssl rand -hex 16)"

# Guard against double-cleanup
_CLEANUP_DONE=0
_PROXY_PID=""
_PROXY_PORT=""

# ── Helpers ──────────────────────────────────────────────────────────────────

die()  { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }
info() { printf '\033[34m▸\033[0m %s\n' "$1"; }
warn() { printf '\033[33m▸\033[0m %s\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }

ensure_dirs() {
  mkdir -p "${CONFIG_DIR}" "${INSTANCES_DIR}" "${LOGS_DIR}"
}

# Write the Python wrapper that patches LiteLLM for DO Gradient AI compatibility
write_litellm_wrapper() {
  cat > "${LITELLM_WRAPPER}" <<'PYEOF'
@@EMBED: src/python/wrapper.py@@
PYEOF
}

# Write the auth bootstrap helper script
write_auth_script() {
  cat > "${AUTH_SCRIPT}" <<'PYEOF'
@@EMBED: src/python/auth.py@@
PYEOF
}

# Returns the path to the litellm binary (venv or system)
resolve_litellm() {
  if [[ -x "${VENV_DIR}/bin/python" ]] && [[ -f "${LITELLM_WRAPPER}" ]]; then
    echo "wrapper"
    return 0
  elif [[ -x "${VENV_DIR}/bin/litellm" ]]; then
    echo "${VENV_DIR}/bin/litellm"
    return 0
  elif command -v litellm >/dev/null 2>&1; then
    command -v litellm
    return 0
  fi
  return 1
}

# ── Config ───────────────────────────────────────────────────────────────────

load_config() {
  if [[ -f "${CONFIG_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${CONFIG_FILE}"
  fi
}

save_config() {
  printf '# claudo configuration — generated %s\nDO_GRADIENT_API_KEY=%q\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${DO_GRADIENT_API_KEY:-}" > "${CONFIG_FILE}"
  chmod 600 "${CONFIG_FILE}"
}

# ── Dependency Checks ────────────────────────────────────────────────────────

check_deps() {
  local missing=0

  if ! command -v node >/dev/null 2>&1; then
    warn "Node.js not found. Install via: brew install node  (or https://nodejs.org)"
    missing=1
  fi

  if ! command -v claude >/dev/null 2>&1; then
    warn "Claude Code CLI not found. Install via: npm install -g @anthropic-ai/claude-code"
    missing=1
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    warn "Python 3 not found. Install via: brew install python3"
    missing=1
  fi

  if ! resolve_litellm >/dev/null 2>&1; then
    info "LiteLLM not found. Installing into venv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}" || die "Failed to create virtual environment"
    "${VENV_DIR}/bin/pip" install --quiet 'litellm[proxy]' || die "Failed to install LiteLLM"
    write_litellm_wrapper
    write_auth_script
    ok "LiteLLM installed in ${VENV_DIR}"
  fi

  if [[ $missing -eq 1 ]]; then
    die "Missing dependencies. Install them and try again."
  fi
}

# ── Claude Code Auth Bootstrap ───────────────────────────────────────────────

bootstrap_claude_auth() {
  local claude_dir="${HOME}/.claude"
  local claude_json="${claude_dir}/.claude.json"

  # Check if Claude Code auth is already configured
  if [[ -f "${claude_json}" ]]; then
    local has_setup
    has_setup=$(python3 "${AUTH_SCRIPT}" check "${claude_json}" 2>/dev/null || echo "no")
    if [[ "${has_setup}" == "yes" ]]; then
      return 0
    fi
  fi

  info "Bootstrapping Claude Code auth for API key usage..."
  mkdir -p "${claude_dir}"

  if [[ -f "${claude_json}" ]]; then
    python3 "${AUTH_SCRIPT}" update "${claude_json}" 2>/dev/null || warn "Could not update Claude Code config"
  else
    python3 "${AUTH_SCRIPT}" create "${claude_json}" 2>/dev/null || warn "Could not create Claude Code config"
    chmod 600 "${claude_json}"
  fi

  ok "Claude Code configured for API key auth"
}

# ── Setup ────────────────────────────────────────────────────────────────────

cmd_setup() {
  ensure_dirs
  info "claudo setup v${VERSION}"
  echo ""

  # Ask for API key
  local current_key=""
  if [[ -f "${CONFIG_FILE}" ]]; then
    load_config
    current_key="${DO_GRADIENT_API_KEY:-}"
  fi

  if [[ -n "${current_key}" ]]; then
    local masked="${current_key:0:8}...${current_key: -4}"
    printf "Current API key: %s\n" "${masked}"
    printf "Enter new DO Gradient AI API key (or press Enter to keep current): "
  else
    printf "Enter your DigitalOcean Gradient AI API key: "
  fi

  read -r input_key
  if [[ -n "${input_key}" ]]; then
    DO_GRADIENT_API_KEY="${input_key}"
  elif [[ -z "${current_key}" ]]; then
    die "API key is required"
  fi

  save_config
  ok "Config saved to ${CONFIG_FILE}"

  # Check deps
  check_deps

  # Bootstrap Claude Code auth so the login screen never appears
  bootstrap_claude_auth

  # Discover models
  info "Discovering available models..."
  discover_models force
  ok "Setup complete! Run 'claudo' to start a Claude session via DO."
}

# ── Model Discovery ─────────────────────────────────────────────────────────

discover_models() {
  local force="${1:-}"

  # Check cache freshness (24h TTL)
  # Uses find -mmin instead of stat to avoid GNU vs BSD stat incompatibility.
  # In devbox/Nix environments, GNU stat may shadow macOS BSD stat; GNU stat -f
  # means "filesystem status" (not format string), producing multi-line output
  # beginning with "File: ..." which causes bash arithmetic under set -u to fail
  # with "File: unbound variable". find -mmin is POSIX and works everywhere.
  if [[ "${force}" != "force" ]] && \
     find "${MODELS_CACHE}" -mmin -1440 2>/dev/null | grep -q .; then
    return 0
  fi

  load_config
  if [[ -z "${DO_GRADIENT_API_KEY:-}" ]]; then
    die "No API key configured. Run: claudo setup"
  fi

  local response
  response=$(curl -sf --connect-timeout 10 --max-time 30 \
    "${DO_API_BASE}/v1/models" \
    -H "Authorization: Bearer ${DO_GRADIENT_API_KEY}" 2>/dev/null) || die "Failed to fetch models from DO API. Check your API key and network."

  echo "${response}" > "${MODELS_CACHE}"
  generate_litellm_config
}

generate_litellm_config() {
  if [[ ! -f "${MODELS_CACHE}" ]]; then
    die "Models cache not found. Run: claudo setup"
  fi

  load_config

  # Use Python to dynamically generate the full LiteLLM config from /v1/models response.
  # This avoids any hardcoded mapping table — model names are derived algorithmically,
  # and fallback aliases are generated for models Claude Code may request but DO lacks.
  python3 - "${MODELS_CACHE}" "${DO_API_BASE}/v1" "${PROXY_MASTER_KEY}" <<'PYEOF' > "${LITELLM_CONFIG}" || die "Failed to generate LiteLLM config"
@@EMBED: src/python/config_gen.py@@
PYEOF

  ok "Generated LiteLLM config from /v1/models"
}

# ── Port Management ──────────────────────────────────────────────────────────

cleanup_stale_pids() {
  local pidfile
  for pidfile in "${INSTANCES_DIR}"/proxy-*.pid; do
    [[ -f "${pidfile}" ]] || continue
    local content
    content=$(cat "${pidfile}" 2>/dev/null) || continue
    local pid
    pid=$(echo "${content}" | cut -d: -f1)
    if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
      rm -f "${pidfile}"
    fi
  done
}

find_available_port() {
  cleanup_stale_pids
  local port=${PORT_MIN}
  while [[ ${port} -le ${PORT_MAX} ]]; do
    if ! lsof -i "TCP:${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      # Also check no PID file claims this port
      if [[ ! -f "${INSTANCES_DIR}/proxy-${port}.pid" ]]; then
        echo "${port}"
        return 0
      fi
    fi
    port=$((port + 1))
  done
  die "No available ports in range ${PORT_MIN}-${PORT_MAX}. Run: claudo stop-all"
}

rotate_log_if_needed() {
  local log_file="$1"
  local max_kb=$(( ${LOG_ROTATION_SIZE_MB:-10} * 1024 ))
  [[ -f "$log_file" ]] || return 0
  # Cross-platform size check using find (avoids stat BSD/GNU mismatch)
  if [[ -z "$(find "$log_file" -size +"${max_kb}k" 2>/dev/null)" ]]; then
    return 0
  fi
  # Rotate: shift existing backups .4.gz→.5.gz ... .1.gz→.2.gz
  local i
  for i in 4 3 2 1; do
    [[ -f "${log_file}.${i}.gz" ]] && mv "${log_file}.${i}.gz" "${log_file}.$((i+1)).gz"
  done
  gzip -9 < "$log_file" > "${log_file}.1.gz" && : > "$log_file"
}

# ── Proxy Lifecycle ──────────────────────────────────────────────────────────

start_proxy() {
  local port="$1"
  local log_file="${LOGS_DIR}/proxy-${port}.log"

  local litellm_mode
  litellm_mode=$(resolve_litellm) || die "LiteLLM not found. Run: claudo setup"

  if [[ "${litellm_mode}" == "wrapper" ]]; then
    DO_GRADIENT_API_KEY="${DO_GRADIENT_API_KEY}" "${VENV_DIR}/bin/python" \
      "${LITELLM_WRAPPER}" \
      --config "${LITELLM_CONFIG}" \
      --host 127.0.0.1 \
      --port "${port}" \
      > "${log_file}" 2>&1 &
  else
    DO_GRADIENT_API_KEY="${DO_GRADIENT_API_KEY}" "${litellm_mode}" \
      --config "${LITELLM_CONFIG}" \
      --host 127.0.0.1 \
      --port "${port}" \
      > "${log_file}" 2>&1 &
  fi

  _PROXY_PID=$!
  _PROXY_PORT="${port}"

  # Write PID file: pid:port:parent_pid:timestamp
  echo "${_PROXY_PID}:${port}:$$:$(date +%s)" > "${INSTANCES_DIR}/proxy-${port}.pid"
}

wait_for_proxy() {
  local port="$1"
  local elapsed=0
  local url="http://127.0.0.1:${port}/health/readiness"

  info "Waiting for LiteLLM proxy on port ${port}..."
  while [[ ${elapsed} -lt ${HEALTH_TIMEOUT} ]]; do
    if curl -sf "${url}" >/dev/null 2>&1; then
      [[ -t 1 ]] && printf '\n'
      ok "Proxy ready on port ${port}"
      return 0
    fi
    # Check proxy hasn't died
    if [[ -n "${_PROXY_PID}" ]] && ! kill -0 "${_PROXY_PID}" 2>/dev/null; then
      [[ -t 1 ]] && printf '\n'
      warn "Proxy exited unexpectedly. Log output:"
      tail -20 "${LOGS_DIR}/proxy-${port}.log" 2>/dev/null || true
      die "LiteLLM proxy failed to start"
    fi
    sleep 1
    [[ -t 1 ]] && printf '.'
    elapsed=$((elapsed + 1))
  done
  [[ -t 1 ]] && printf '\n'
  die "Proxy health check timed out after ${HEALTH_TIMEOUT}s"
}

cleanup() {
  if [[ ${_CLEANUP_DONE} -eq 1 ]]; then
    return
  fi
  _CLEANUP_DONE=1

  if [[ -n "${_PROXY_PID}" ]]; then
    # SIGTERM first
    kill "${_PROXY_PID}" 2>/dev/null || true
    # Wait up to 3s for clean exit
    local waited=0
    while [[ ${waited} -lt 3 ]] && kill -0 "${_PROXY_PID}" 2>/dev/null; do
      sleep 1
      waited=$((waited + 1))
    done
    # SIGKILL if still alive
    if kill -0 "${_PROXY_PID}" 2>/dev/null; then
      kill -9 "${_PROXY_PID}" 2>/dev/null || true
    fi
  fi

  if [[ -n "${_PROXY_PORT}" ]]; then
    rm -f "${INSTANCES_DIR}/proxy-${_PROXY_PORT}.pid"
  fi
}

# ── Subcommands ──────────────────────────────────────────────────────────────

cmd_status() {
  ensure_dirs
  cleanup_stale_pids
  local found=0
  local pidfile
  for pidfile in "${INSTANCES_DIR}"/proxy-*.pid; do
    [[ -f "${pidfile}" ]] || continue
    local content
    content=$(cat "${pidfile}" 2>/dev/null) || continue
    local pid port parent_pid start_ts
    pid=$(echo "${content}" | cut -d: -f1)
    port=$(echo "${content}" | cut -d: -f2)
    parent_pid=$(echo "${content}" | cut -d: -f3)
    start_ts=$(echo "${content}" | cut -d: -f4)

    local uptime_str="unknown"
    if [[ -n "${start_ts}" ]]; then
      local now
      now=$(date +%s)
      local elapsed=$(( now - start_ts ))
      local mins=$(( elapsed / 60 ))
      local secs=$(( elapsed % 60 ))
      uptime_str="${mins}m${secs}s"
    fi

    printf "  PID %-8s  Port %-6s  Parent %-8s  Uptime %s\n" "${pid}" "${port}" "${parent_pid}" "${uptime_str}"
    found=$((found + 1))
  done

  if [[ ${found} -eq 0 ]]; then
    info "No running claudo instances"
  else
    info "${found} instance(s) running"
  fi
}

cmd_stop_all() {
  ensure_dirs
  local stopped=0
  local pidfile
  for pidfile in "${INSTANCES_DIR}"/proxy-*.pid; do
    [[ -f "${pidfile}" ]] || continue
    local content
    content=$(cat "${pidfile}" 2>/dev/null) || continue
    local pid
    pid=$(echo "${content}" | cut -d: -f1)
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      stopped=$((stopped + 1))
    fi
    rm -f "${pidfile}"
  done

  if [[ ${stopped} -eq 0 ]]; then
    info "No running instances to stop"
  else
    ok "Stopped ${stopped} instance(s)"
  fi
}

cmd_models() {
  ensure_dirs
  load_config

  if [[ ! -f "${MODELS_CACHE}" ]]; then
    info "No cached models. Running discovery..."
    discover_models force
  fi

  # Use Python to display model mappings (same logic as config generation)
  python3 - "${MODELS_CACHE}" <<'PYEOF' || die "Failed to parse models cache"
@@EMBED: src/python/models.py@@
PYEOF

  echo ""
  local cache_time="unknown"
  if [[ -f "${MODELS_CACHE}" ]]; then
    if [[ "$(uname)" == "Darwin" ]]; then
      cache_time=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "${MODELS_CACHE}" 2>/dev/null || echo "unknown")
    else
      cache_time=$(stat -c "%y" "${MODELS_CACHE}" 2>/dev/null | cut -d. -f1 || echo "unknown")
    fi
  fi
  info "Cache last updated: ${cache_time}"
  info "Run 'claudo setup' to refresh"
}

cmd_version() {
  echo "claudo v${VERSION}"
}

cmd_update() {
  if [[ ! -d "${VENV_DIR}" ]]; then
    die "No venv found. Run 'claudo setup' first."
  fi
  info "Upgrading LiteLLM..."
  local pip="${VENV_DIR}/bin/pip"
  # pip install --upgrade installs the latest version into the existing venv
  "${pip}" install --upgrade --quiet 'litellm[proxy]' || die "Upgrade failed"
  local version
  version=$("${VENV_DIR}/bin/python" -c "import litellm; print(litellm.__version__)" 2>/dev/null || echo "unknown")
  write_litellm_wrapper
  write_auth_script
  ok "LiteLLM updated to v${version}"
}

cmd_help() {
  cat <<EOF
claudo v${VERSION} — Claude Code via DigitalOcean Gradient AI

Usage:
  claudo                    Start interactive Claude session via DO
  claudo <claude args>      Pass arguments to claude (e.g. claudo -p "hello")
  claudo setup              Configure API key and discover models
  claudo update             Upgrade LiteLLM to latest version (run 'claudo stop-all' first)
  claudo status             Show running proxy instances
  claudo stop-all           Kill all proxy instances
  claudo models             Show discovered model mappings
  claudo version            Show version
  claudo help               Show this help

Examples:
  claudo setup              First-time setup
  claudo                    Interactive session
  claudo -p "explain this"  One-shot prompt
  claudo --model claude-sonnet-4-5-20250929 -p "hello"
EOF
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
  ensure_dirs

  # Handle subcommands
  case "${1:-}" in
    setup)     cmd_setup; return ;;
    update)    cmd_update; return ;;
    status)    cmd_status; return ;;
    stop-all)  cmd_stop_all; return ;;
    models)    cmd_models; return ;;
    version)   cmd_version; return ;;
    help|--help|-h)  cmd_help; return ;;
  esac

  # Main flow: start proxy and launch claude
  load_config

  if [[ -z "${DO_GRADIENT_API_KEY:-}" ]]; then
    info "First-time setup required"
    cmd_setup
    # Re-load after setup
    load_config
  fi

  check_deps

  # Discover/refresh models
  discover_models

  # Regenerate LiteLLM config each session (embeds per-session master key)
  generate_litellm_config

  # Always regenerate wrapper and auth script to ensure patches are up-to-date
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    write_litellm_wrapper
    write_auth_script
  fi

  # Find an available port
  local port
  port=$(find_available_port)

  # Register cleanup trap
  trap cleanup EXIT INT TERM HUP

  # Start proxy
  start_proxy "${port}"
  wait_for_proxy "${port}"

  # Launch Claude Code pointed at our proxy
  info "Launching Claude Code via DO Gradient AI (port ${port})..."
  export ANTHROPIC_BASE_URL="http://127.0.0.1:${port}"
  export ANTHROPIC_AUTH_TOKEN="${PROXY_MASTER_KEY}"
  export DO_GRADIENT_API_KEY

  # Pass all arguments through to claude, or run interactively
  claude "$@"
}

main "$@"
