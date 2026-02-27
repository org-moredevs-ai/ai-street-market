#!/bin/bash
# WebSocket bridge entrypoint — translates env vars to CLI args.
set -euo pipefail

ARGS=""

ARGS="${ARGS} --nats-url ${NATS_URL:-nats://localhost:4222}"
ARGS="${ARGS} --ws-host ${WS_HOST:-0.0.0.0}"
ARGS="${ARGS} --ws-port ${WS_PORT:-9090}"

exec python scripts/run_bridge.py ${ARGS}
