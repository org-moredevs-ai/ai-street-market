#!/bin/bash
# Market service entrypoint — translates env vars to CLI args.
set -euo pipefail

# One-time snapshot cleanup (set CLEAR_SNAPSHOTS=1 to wipe stale state)
if [ "${CLEAR_SNAPSHOTS:-}" = "1" ]; then
    echo "Clearing stale snapshots..."
    rm -f "${SNAPSHOT_DIR:-/data/snapshots}"/snapshot-*.json
fi

ARGS=""

ARGS="${ARGS} --nats-url ${NATS_URL:-nats://localhost:4222}"
ARGS="${ARGS} --season ${SEASON_FILE:-season-1.yaml}"
ARGS="${ARGS} --snapshot-dir ${SNAPSHOT_DIR:-/data/snapshots}"
ARGS="${ARGS} --snapshot-interval ${SNAPSHOT_INTERVAL:-50}"
ARGS="${ARGS} --no-bridge"

if [ -n "${TICK_OVERRIDE:-}" ]; then
    ARGS="${ARGS} --tick-override ${TICK_OVERRIDE}"
fi

exec python scripts/run_season.py ${ARGS}
