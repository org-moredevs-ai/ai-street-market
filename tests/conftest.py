"""Shared test fixtures."""

import os

import pytest
from streetmarket import MarketBusClient


@pytest.fixture
def nats_url() -> str:
    return os.environ.get("NATS_URL", "nats://localhost:4222")


@pytest.fixture
async def bus_client(nats_url: str) -> MarketBusClient:
    """Provide a connected MarketBusClient, cleaned up after use."""
    client = MarketBusClient(nats_url)
    await client.connect()
    yield client  # type: ignore[misc]
    await client.close()
