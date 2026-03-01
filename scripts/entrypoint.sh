#!/bin/bash
# Unified entrypoint — routes to the correct service based on SERVICE_ROLE env var.
# This avoids Railway's startCommand which doesn't inherit Docker PATH.
set -euo pipefail

case "${SERVICE_ROLE:-market}" in
    market)
        exec scripts/entrypoint-market.sh
        ;;
    ws-bridge)
        exec scripts/entrypoint-bridge.sh
        ;;
    agent-manager)
        exec python scripts/run_agent_manager.py
        ;;
    agent-runner)
        exec python scripts/run_agent_runner.py
        ;;
    *)
        echo "ERROR: Unknown SERVICE_ROLE='${SERVICE_ROLE}'"
        echo "Valid values: market, ws-bridge, agent-manager, agent-runner"
        exit 1
        ;;
esac
