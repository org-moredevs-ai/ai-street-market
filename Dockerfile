# AI Street Market — Multi-stage Dockerfile
# Targets: market (season runner), ws-bridge (WebSocket relay)

# ============================================================
# Base stage — shared Python environment
# ============================================================
FROM python:3.12-slim AS base

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./
COPY libs/ libs/

# Install production dependencies only
RUN pip install --no-cache-dir -e .

# Copy application code
COPY services/ services/
COPY scripts/ scripts/
COPY policies/ policies/

# Ensure scripts are executable
RUN chmod +x scripts/entrypoint-market.sh scripts/entrypoint-bridge.sh

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# ============================================================
# Market service — season runner + all market agents
# ============================================================
FROM base AS market

# Snapshot directory (Railway volume mounted at /data/snapshots)
RUN mkdir -p /data/snapshots

ENTRYPOINT ["scripts/entrypoint-market.sh"]

# ============================================================
# WebSocket bridge — NATS to WebSocket relay
# ============================================================
FROM base AS ws-bridge

EXPOSE 9090

ENTRYPOINT ["scripts/entrypoint-bridge.sh"]
