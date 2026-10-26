#!/usr/bin/env bash
# Draw the charts for a finished comparison, from any directory:
#   cli/viz.sh cli/results/prose-<date>
# A relative path is tried against the current directory first, then against cli/.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$HERE/../server" python "$HERE/visualize.py" "$@"
