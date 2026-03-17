#!/bin/bash
# statusline-cmm.sh — Wrapper: runs user's global statusline, appends CMM stats
#
# Reads the user's global statusLine.command from global settings.json,
# runs it, and appends CMM call stats with a pipe separator.
# Falls back to CMM-only output when no global statusline is configured.

# --- Discover user's existing global statusline command ---
# Check settings.local.json first (higher precedence), then settings.json
GLOBAL_CMD=""
for config_dir in "${CLAUDE_CONFIG_DIR:-}" "$HOME/.config/claude-code" "$HOME/.claude"; do
  [ -z "$config_dir" ] && continue
  for settings_file in "${config_dir}/settings.local.json" "${config_dir}/settings.json"; do
    [ -f "$settings_file" ] || continue
    GLOBAL_CMD=$(python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        cmd = json.load(f).get('statusLine', {}).get('command', '')
        print(cmd)
except Exception:
    pass
" "$settings_file" 2>/dev/null)
    [ -n "$GLOBAL_CMD" ] && break 2
  done
done

# --- CMM stats ---
CMM_OUTPUT=""
CACHE="$HOME/.cache/codebase-memory-mcp/_call-counts.json"
if [ -f "$CACHE" ]; then
  TOTAL=$(jq -r '.total_calls // 0' "$CACHE" 2>/dev/null || echo 0)
  SEARCH=$(jq -r '.by_tool["mcp__codebase-memory-mcp__search_graph"] // 0' "$CACHE" 2>/dev/null || echo 0)
  SNIPPET=$(jq -r '.by_tool["mcp__codebase-memory-mcp__get_code_snippet"] // 0' "$CACHE" 2>/dev/null || echo 0)
  TRACE=$(jq -r '.by_tool["mcp__codebase-memory-mcp__trace_call_path"] // 0' "$CACHE" 2>/dev/null || echo 0)
  CMM_OUTPUT="CMM:${TOTAL} (sg:${SEARCH} cs:${SNIPPET} tr:${TRACE})"
else
  CMM_OUTPUT="CMM:0"
fi

# --- Combine: run global statusline, append CMM stats ---
# Skip if the global command is itself a CMM statusline (avoids double output with --all)
case "$GLOBAL_CMD" in
  *statusline-cmm.sh*) GLOBAL_CMD="" ;;
esac
if [ -n "$GLOBAL_CMD" ]; then
  EXISTING=$(bash -c "$GLOBAL_CMD" 2>/dev/null)
  if [ -n "$EXISTING" ]; then
    echo "${EXISTING} | ${CMM_OUTPUT}"
  else
    echo "$CMM_OUTPUT"
  fi
else
  echo "$CMM_OUTPUT"
fi
