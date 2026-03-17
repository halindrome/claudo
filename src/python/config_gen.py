"""
Generate a LiteLLM proxy config YAML from a DO /v1/models response cache.

Usage: python3 config_gen.py <models_cache.json> <api_base> <master_key>

Reads the cached model list, generates all plausible Claude Code model name
aliases for each DO model, and writes a LiteLLM model_list YAML to stdout.
"""
import json, re, sys

API_BASE = sys.argv[2]
MASTER_KEY = sys.argv[3]

with open(sys.argv[1]) as f:
    data = json.load(f)

do_models = sorted(m["id"] for m in data.get("data", []) if "claude" in m["id"].lower())

if not do_models:
    print("No Claude models found", file=sys.stderr)
    sys.exit(1)

def do_to_cc_names(do_id):
    """Generate all plausible Claude Code model names for a DO model ID.
    Returns (primary_name, [alias_names]) where primary is the best guess
    and aliases cover other patterns Claude Code might use."""
    # Strip 'anthropic-' prefix: 'anthropic-claude-4.5-sonnet' -> 'claude-4.5-sonnet'
    base = re.sub(r'^anthropic-', '', do_id)
    # Replace dots with dashes: 'claude-4.5-sonnet' -> 'claude-4-5-sonnet'
    normalized = base.replace('.', '-')

    names = set()
    names.add(normalized)

    # Extract family (sonnet/opus/haiku) and version parts
    # Patterns: claude-{ver}-{family}, claude-{family}-{ver}, claude-{ver}-{family}
    family_match = re.search(r'(sonnet|opus|haiku)', normalized)
    version_match = re.findall(r'(\d+(?:-\d+)?)', normalized)

    if family_match and version_match:
        family = family_match.group(1)
        # Build version string from all numeric parts
        ver_parts = '-'.join(version_match)

        # Generate both orderings: claude-{family}-{ver} and claude-{ver}-{family}
        names.add(f"claude-{family}-{ver_parts}")
        names.add(f"claude-{ver_parts}-{family}")

    # The primary name is the normalized form
    primary = normalized
    aliases = sorted(names - {primary})
    return primary, aliases

# Collect all entries: (cc_model_name, do_model_id)
entries = []
mapped_cc_names = set()
primary_names = set()  # Names from actual DO models (not fallbacks)

for do_id in do_models:
    primary, aliases = do_to_cc_names(do_id)
    entries.append((primary, do_id))
    mapped_cc_names.add(primary)
    primary_names.add(primary)
    for alias in aliases:
        if alias not in mapped_cc_names:
            entries.append((alias, do_id))
            mapped_cc_names.add(alias)
            primary_names.add(alias)

# Fallback aliases: if Claude Code requests a model we don't have,
# route it to the best available model in the same family.
# Gather best model per family (highest version number).
family_best = {}  # family -> (version_tuple, do_model_id)
for do_id in do_models:
    base = re.sub(r'^anthropic-', '', do_id)
    for family in ('sonnet', 'opus', 'haiku'):
        if family in base:
            nums = [int(x) for x in re.findall(r'(\d+)', base)]
            ver_tuple = tuple(nums) if nums else (0,)
            if family not in family_best or ver_tuple > family_best[family][0]:
                family_best[family] = (ver_tuple, do_id)
            break

# Known Claude Code model names that may not have exact DO matches.
# Generate common patterns: claude-{family}-{major}-{minor}
for family, (ver_tuple, best_do) in family_best.items():
    # Generate unversioned catchall: claude-{family} (not typically used, but safe)
    # More importantly: generate versioned names Claude Code might request
    # e.g., claude-sonnet-4-6, claude-haiku-4-6, claude-opus-4-6
    # We check if they're already mapped; if not, add as fallback to best available.
    for major in range(3, 6):
        for minor in range(0, 10):
            candidate = f"claude-{family}-{major}-{minor}"
            if candidate not in mapped_cc_names:
                entries.append((candidate, best_do))
                mapped_cc_names.add(candidate)

# Add date-suffixed entries for primary model names.
# Claude Code requests models like "claude-haiku-4-5-20251001" (with date suffix)
# but DO model IDs don't include dates. Add entries for all known Anthropic release
# dates so dated model names route to the correct DO model.
KNOWN_DATES = ["20240229", "20241022", "20250219", "20250514", "20250929", "20251001"]
for base_name in list(primary_names):
    # Find the DO model ID for this base name
    do_id_for_base = None
    for cc_name, do_id in entries:
        if cc_name == base_name:
            do_id_for_base = do_id
            break
    if do_id_for_base is None:
        continue
    for date in KNOWN_DATES:
        dated = f"{base_name}-{date}"
        if dated not in mapped_cc_names:
            entries.append((dated, do_id_for_base))
            mapped_cc_names.add(dated)
KNOWN_SIZES = ["[1m]"]
for base_name in list(primary_names):
    # Find the DO model ID for this base name
    do_id_for_base = None
    for cc_name, do_id in entries:
        if cc_name == base_name:
            do_id_for_base = do_id
            break
    if do_id_for_base is None:
        continue
    for size in KNOWN_SIZES:
        sized = f"{base_name}{size}"
        if sized not in mapped_cc_names:
            entries.append((sized, do_id_for_base))
            mapped_cc_names.add(sized)

# Write YAML
lines = ["# Auto-generated by claudo — do not edit manually", "model_list:"]
seen = set()
for cc_name, do_id in entries:
    if cc_name in seen:
        continue
    seen.add(cc_name)
    lines.append(f"  - model_name: {cc_name}")
    lines.append(f"    litellm_params:")
    lines.append(f"      model: openai/{do_id}")
    lines.append(f"      api_key: os.environ/DO_GRADIENT_API_KEY")
    lines.append(f"      api_base: {API_BASE}")
    lines.append(f"      drop_params: true")
    lines.append(f"      request_timeout: 600")

lines.append("")
lines.append("general_settings:")
lines.append("  drop_params: true")
lines.append(f"  master_key: {MASTER_KEY}")
lines.append("")
lines.append("litellm_settings:")
lines.append("  drop_params: true")
lines.append("  request_timeout: 600")

print("\n".join(lines))
count = len(seen)
print(f"Generated {count} model entries", file=sys.stderr)
