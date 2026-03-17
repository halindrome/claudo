"""
Display a human-readable table of DO model → Claude Code model name mappings.

Usage: python3 models.py <models_cache.json>
"""
import json, re, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

do_models = sorted(m["id"] for m in data.get("data", []) if "claude" in m["id"].lower())

def primary_cc_name(do_id):
    base = re.sub(r'^anthropic-', '', do_id)
    return base.replace('.', '-')

print()
print(f"{'DO Gradient Model':<40}  →  {'Claude Code Model'}")
print(f"{'─' * 40}     {'─' * 34}")
for do_id in do_models:
    cc = primary_cc_name(do_id)
    print(f"{do_id:<40}  →  {cc}")
