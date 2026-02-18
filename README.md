# claudo

Run [Claude Code](https://github.com/anthropics/claude-code) against [DigitalOcean Gradient AI](https://www.digitalocean.com/products/gradient-ai) instead of Anthropic's API.

`claudo` spins up a local [LiteLLM](https://github.com/BerriAI/litellm) proxy that bridges Claude Code's native Anthropic API format to DO's OpenAI-compatible endpoint — so you get the full Claude Code experience billed through your DigitalOcean account.

```
┌────────────┐         ┌────────────┐         ┌────────────┐
│ Claude Code│  ──▶    │  LiteLLM   │  ──▶    │  DO Grad.  │
│   (CLI)    │Anthropic │   Proxy    │ OpenAI  │  AI API    │
│            │ format  │ (localhost) │ format  │            │
└────────────┘         └────────────┘         └────────────┘
```

## Prerequisites

- **Node.js** ≥ 18
- **Python 3** (for LiteLLM)
- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **A DigitalOcean Gradient AI API key** — get one from the [DO control panel](https://cloud.digitalocean.com/gen-ai)

> **Note:** LiteLLM is installed automatically into a local virtualenv (`~/.config/claudo/venv`) on first run. You do not need to install it manually.

## Installation

```bash
npm install -g claudo
```

## Quick start

```bash
# First-time setup — enter your DO Gradient AI API key
claudo setup

# Start an interactive Claude session via DO
claudo
```

## Usage

```
claudo                    Start interactive Claude session via DO
claudo <claude args>      Pass arguments to claude (e.g. claudo -p "hello")
claudo setup              Configure API key and discover models
claudo status             Show running proxy instances
claudo stop-all           Kill all proxy instances
claudo models             Show discovered model mappings
claudo version            Show version
claudo help               Show help
```

### Examples

```bash
# One-shot prompt
claudo -p "explain this codebase"

# Use a specific model
claudo --model claude-sonnet-4-5 -p "hello"

# Check what models are available on DO
claudo models

# See running proxy instances
claudo status
```

## How it works

1. Loads your DO API key from `~/.config/claudo/config.env`
2. Fetches available Claude models from DO's `/v1/models` endpoint (cached 24h)
3. Generates a LiteLLM config that maps Claude Code model names to DO model IDs
4. Starts a LiteLLM proxy on a free port in the `4100–4200` range
5. Sets `ANTHROPIC_BASE_URL` to point at the local proxy
6. Launches `claude` with your arguments
7. Shuts down the proxy cleanly on exit

Multiple `claudo` sessions can run concurrently — each gets its own port.

## Configuration

| File | Purpose |
|------|---------|
| `~/.config/claudo/config.env` | API key (chmod 600) |
| `~/.config/claudo/models_cache.json` | Cached model list (24h TTL) |
| `~/.config/claudo/litellm_config.yaml` | Auto-generated LiteLLM config |
| `~/.config/claudo/venv/` | LiteLLM virtualenv |
| `~/.config/claudo/logs/` | Per-instance proxy logs |

## Troubleshooting

**Proxy fails to start** — check `~/.config/claudo/logs/proxy-<port>.log` for LiteLLM errors.

**Models not found** — run `claudo setup` to refresh the model cache.

**Port range exhausted** — run `claudo stop-all` to clean up stale instances.

**Python errors on 3.14+** — the script patches uvicorn's uvloop dependency automatically; if you hit issues, ensure your venv is up to date by deleting `~/.config/claudo/venv` and re-running `claudo setup`.

## License

MIT
