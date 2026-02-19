"""Integration tests for the Governor Agent. Requires NATS running."""

import asyncio

import pytest
from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Topics,
    create_message,
)

from services.governor.governor import GovernorAgent
from services.governor.state import MAX_ACTIONS_PER_TICK

pytestmark = pytest.mark.integration


@pytest.fixture
async def governor(nats_url: str) -> GovernorAgent:
    """Start a Governor agent, tear it down after the test."""
    gov = GovernorAgent(nats_url)
    await gov.start()
    await asyncio.sleep(0.5)  # Let subscriptions settle
    yield gov  # type: ignore[misc]
    await gov.stop()


@pytest.fixture
async def test_client(nats_url: str) -> MarketBusClient:
    """Separate client for sending test messages and receiving results."""
    client = MarketBusClient(nats_url)
    await client.connect()
    yield client  # type: ignore[misc]
    await client.close()


async def _collect_results(
    client: MarketBusClient,
    count: int,
    timeout: float = 5.0,
) -> list[Envelope]:
    """Subscribe to governance topic and collect validation results."""
    results: list[Envelope] = []
    done = asyncio.Event()

    async def handler(env: Envelope) -> None:
        results.append(env)
        if len(results) >= count:
            done.set()

    await client.subscribe(Topics.GOVERNANCE, handler)
    await asyncio.sleep(0.3)  # Let subscription settle

    return results, done  # type: ignore[return-value]


class TestGovernorIntegration:
    async def test_valid_offer_accepted(
        self, governor: GovernorAgent, test_client: MarketBusClient
    ):
        results, done = await _collect_results(test_client, 1)

        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, env)

        await asyncio.wait_for(done.wait(), timeout=5.0)

        # Find the result for our message (skip any stale results)
        result = next(
            r for r in results
            if r.payload.get("reference_msg_id") == env.id
        )
        assert result.payload["valid"] is True
        assert result.from_agent == "governor"

    async def test_unknown_item_rejected(
        self, governor: GovernorAgent, test_client: MarketBusClient
    ):
        results, done = await _collect_results(test_client, 1)

        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "diamond", "quantity": 1, "price_per_unit": 100.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, env)

        await asyncio.wait_for(done.wait(), timeout=5.0)

        result = next(
            r for r in results
            if r.payload.get("reference_msg_id") == env.id
        )
        assert result.payload["valid"] is False
        assert "Unknown item" in result.payload["reason"]

    async def test_invalid_recipe_rejected(
        self, governor: GovernorAgent, test_client: MarketBusClient
    ):
        results, done = await _collect_results(test_client, 1)

        env = create_message(
            from_agent="crafter-01",
            topic=Topics.GENERAL,
            msg_type=MessageType.CRAFT_START,
            payload={"recipe": "cake", "inputs": {"sugar": 1}, "estimated_ticks": 1},
            tick=1,
        )
        await test_client.publish(Topics.GENERAL, env)

        await asyncio.wait_for(done.wait(), timeout=5.0)

        result = next(
            r for r in results
            if r.payload.get("reference_msg_id") == env.id
        )
        assert result.payload["valid"] is False
        assert "Unknown recipe" in result.payload["reason"]

    async def test_rate_limiting(
        self, governor: GovernorAgent, test_client: MarketBusClient
    ):
        # Send MAX_ACTIONS_PER_TICK + 1 messages — last one should be rate limited
        total = MAX_ACTIONS_PER_TICK + 1
        results, done = await _collect_results(test_client, total)

        for i in range(total):
            env = create_message(
                from_agent="spammer-01",
                topic=Topics.RAW_GOODS,
                msg_type=MessageType.OFFER,
                payload={"item": "potato", "quantity": 1, "price_per_unit": 1.0},
                tick=1,
            )
            await test_client.publish(Topics.RAW_GOODS, env)
            await asyncio.sleep(0.05)  # Small delay to ensure ordering

        await asyncio.wait_for(done.wait(), timeout=10.0)

        # At least one result should be rate-limited
        rate_limited = [
            r for r in results
            if r.payload.get("valid") is False
            and r.payload.get("reason")
            and "Rate limited" in r.payload["reason"]
        ]
        assert len(rate_limited) >= 1

    async def test_governor_ignores_own_messages(
        self, governor: GovernorAgent, test_client: MarketBusClient
    ):
        """Governor should not validate its own validation_result messages.

        We send a valid offer, wait for the result, then verify only one
        result was produced (not an infinite loop of self-validation).
        """
        results, done = await _collect_results(test_client, 1)

        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "wood", "quantity": 5, "price_per_unit": 3.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, env)

        await asyncio.wait_for(done.wait(), timeout=5.0)
        # Give time for any potential loop to produce extra messages
        await asyncio.sleep(1.0)

        # Should have exactly 1 result for our message
        our_results = [
            r for r in results
            if r.payload.get("reference_msg_id") == env.id
        ]
        assert len(our_results) == 1
