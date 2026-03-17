#!/usr/bin/env bash
# Build bin/claudo from src/claudo.sh by replacing @@EMBED: path@@ markers
# with the contents of the referenced files.
#
# Usage: bash scripts/build.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="${REPO_ROOT}/src/claudo.sh"
OUTPUT="${REPO_ROOT}/bin/claudo"

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "error: template not found: ${TEMPLATE}" >&2
  exit 1
fi

python3 - "${REPO_ROOT}" "${TEMPLATE}" "${OUTPUT}" <<'EOF'
import re
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
template_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])

template = template_path.read_text()

def replace_embed(match):
    embed_path = repo_root / match.group(1).strip()
    if not embed_path.exists():
        raise FileNotFoundError(f"Embed target not found: {embed_path}")
    content = embed_path.read_text()
    # Strip trailing newline so heredoc terminates cleanly
    return content.rstrip('\n')

result = re.sub(r'@@EMBED:\s*(.+?)@@', replace_embed, template)

# Replace template header comment with generated-file warning
result = result.replace(
    "# TEMPLATE FILE — edit this file and run 'make build' to regenerate bin/claudo.\n"
    "# Do NOT edit bin/claudo directly; it is assembled from src/ by scripts/build.sh.\n",
    "# GENERATED FILE — do not edit directly.\n"
    "# Edit src/claudo.sh and src/python/*.py, then run 'make build' to regenerate.\n",
)

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(result)
output_path.chmod(0o755)
print(f"Built {output_path}")
EOF
