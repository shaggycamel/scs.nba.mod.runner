#!/bin/bash
# Run the model repos scheduled in util.update_schedule.
#
# Usage: ./cron.sh weekly
#        ./cron.sh weekly,intraday
#
# The schedule table decides which repos run; this wrapper only supplies the
# cadence, environment and a lock so cron ticks cannot overlap.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
export SCS_HUB_CREDENTIALS="${SCS_HUB_CREDENTIALS:-$HOME/.config/scs_hub_credentials.ini}"

echo "Running $(date '+%Y-%m-%d %H:%M:%S %Z')"

if ! command -v flock >/dev/null 2>&1; then
    echo "flock not found; install util-linux (or run the Python module directly)."
    exit 1
fi

LOCK_FILE="${LOCK_FILE:-${TMPDIR:-/tmp}/scs.nba.mod.runner.lock}"
exec 9>"$LOCK_FILE"
if ! flock -w 3600 9; then
    echo "Another model run is still in progress; skipping this tick."
    exit 1
fi

exec uv run --frozen --no-dev python __main__.py "$@"
