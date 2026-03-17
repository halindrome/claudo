"""
Bootstrap and check Claude Code auth configuration.

Usage:
  python3 auth.py check  <path>   — print 'yes' if already configured, 'no' otherwise
  python3 auth.py update <path>   — update existing .claude.json to mark as configured
  python3 auth.py create <path>   — create minimal .claude.json for API key auth
"""
import json, sys
from datetime import datetime, timezone

cmd = sys.argv[1]
path = sys.argv[2]

if cmd == "check":
    try:
        with open(path) as f:
            d = json.load(f)
        print("yes" if d.get("numStartups", 0) >= 1 else "no")
    except Exception:
        print("no")

elif cmd == "update":
    with open(path) as f:
        d = json.load(f)
    d["numStartups"] = max(d.get("numStartups", 0), 1)
    if "firstStartTime" not in d:
        d["firstStartTime"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        json.dump(d, f, indent=2)

elif cmd == "create":
    d = {
        "numStartups": 1,
        "firstStartTime": datetime.now(timezone.utc).isoformat(),
        "hasCompletedOnboarding": True,
    }
    with open(path, "w") as f:
        json.dump(d, f, indent=2)

else:
    print(f"Unknown command: {cmd}", file=sys.stderr)
    sys.exit(1)
