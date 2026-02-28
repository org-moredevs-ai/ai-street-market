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
    *)
        echo "ERROR: Unknown SERVICE_ROLE='${SERVICE_ROLE}'"
        echo "Valid values: market, ws-bridge"
        exit 1
        ;;
esac
