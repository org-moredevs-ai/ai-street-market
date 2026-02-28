# AI Street Market — Dockerfile
# Single image — SERVICE_ROLE env var selects market or ws-bridge at runtime.
# Railway doesn't support --target, and startCommand doesn't inherit Docker PATH,
# so we use a unified entrypoint that routes based on SERVICE_ROLE.

FROM python:3.12-slim

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
RUN chmod +x scripts/entrypoint.sh scripts/entrypoint-market.sh scripts/entrypoint-bridge.sh

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# Snapshot directory (Railway volume mounted at /data/snapshots)
RUN mkdir -p /data/snapshots

EXPOSE 9090

# SERVICE_ROLE defaults to "market"; set to "ws-bridge" for the bridge service
ENV SERVICE_ROLE=market

ENTRYPOINT ["scripts/entrypoint.sh"]
