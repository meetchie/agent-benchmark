#!/usr/bin/env bash
# Run the BrowserUse-vs-Rindler comparison from any directory:
#   cli/bench.sh prose --task add-hair-towel
# It uses the server/ uv project (one environment for the whole repo).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env PYTHONUNBUFFERED=1 uv run --project "$HERE/../server" python "$HERE/run.py" "$@"
