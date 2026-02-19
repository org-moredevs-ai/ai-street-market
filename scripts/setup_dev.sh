#!/usr/bin/env bash
set -euo pipefail

echo "=== AI Street Market — Dev Setup ==="
echo

# Check Python version
PYTHON_VERSION=$(python3 --version 2>/dev/null | cut -d' ' -f2)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]); then
    echo "ERROR: Python 3.12+ required (found $PYTHON_VERSION)"
    exit 1
fi
echo "[OK] Python $PYTHON_VERSION"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "WARNING: Docker not found. You'll need it for NATS."
else
    echo "[OK] Docker found"
fi

# Create .env if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[OK] Created .env from .env.example"
else
    echo "[OK] .env already exists"
fi

# Set up venv
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e ".[dev]" -q

echo
echo "=== Setup complete! ==="
echo
echo "Next steps:"
echo "  make infra-up       # Start NATS"
echo "  make test           # Run tests"
echo "  make proof-of-life  # Run demo"
