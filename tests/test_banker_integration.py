"""Integration tests for the Banker Agent. Requires NATS running."""

import asyncio

import pytest
from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Topics,
    create_message,
)

from services.banker.banker import BankerAgent

pytestmark = pytest.mark.integration


@pytest.fixture
async def banker(nats_url: str) -> BankerAgent:
    """Start a Banker agent, tear it down after the test."""
    b = BankerAgent(nats_url)
    await b.start()
    await asyncio.sleep(0.5)  # Let subscriptions settle
    yield b  # type: ignore[misc]
    await b.stop()


@pytest.fixture
async def test_client(nats_url: str) -> MarketBusClient:
    """Separate client for sending test messages and receiving results."""
    client = MarketBusClient(nats_url)
    await client.connect()
    yield client  # type: ignore[misc]
    await client.close()


async def _collect_settlements(
    client: MarketBusClient,
    count: int,
) -> tuple[list[Envelope], asyncio.Event]:
    """Subscribe to bank topic and collect settlement messages."""
    results: list[Envelope] = []
    done = asyncio.Event()

    async def handler(env: Envelope) -> None:
        results.append(env)
        if len(results) >= count:
            done.set()

    await client.subscribe(Topics.BANK, handler)
    await asyncio.sleep(0.3)  # Let subscription settle

    return results, done


async def _send_join(client: MarketBusClient, agent_id: str, tick: int = 1) -> None:
    """Send a JOIN message for an agent."""
    env = create_message(
        from_agent=agent_id,
        topic=Topics.SQUARE,
        msg_type=MessageType.JOIN,
        payload={"agent_id": agent_id, "name": agent_id, "description": "Test agent"},
        tick=tick,
    )
    await client.publish(Topics.SQUARE, env)


async def _seed_inventory(
    client: MarketBusClient,
    agent_id: str,
    inventory: dict[str, int],
    tick: int = 1,
) -> None:
    """Seed an agent's inventory via CRAFT_COMPLETE messages."""
    env = create_message(
        from_agent=agent_id,
        topic=Topics.GENERAL,
        msg_type=MessageType.CRAFT_COMPLETE,
        payload={"recipe": "seed", "output": inventory, "agent": agent_id},
        tick=tick,
    )
    await client.publish(Topics.GENERAL, env)


class TestBankerIntegration:
    async def test_full_trade_cycle(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """Full cycle: JOIN → seed inventory → OFFER → ACCEPT → Settlement."""
        results, done = await _collect_settlements(test_client, 1)

        # 1. Both agents join
        await _send_join(test_client, "seller-01")
        await _send_join(test_client, "buyer-01")
        await asyncio.sleep(0.3)

        # 2. Seed seller with potatoes
        await _seed_inventory(test_client, "seller-01", {"potato": 10})
        await asyncio.sleep(0.3)

        # 3. Seller posts an offer
        offer_env = create_message(
            from_agent="seller-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 5, "price_per_unit": 3.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, offer_env)
        await asyncio.sleep(0.3)

        # 4. Buyer accepts the offer
        accept_env = create_message(
            from_agent="buyer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload={"reference_msg_id": offer_env.id, "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, accept_env)

        # 5. Wait for settlement
        await asyncio.wait_for(done.wait(), timeout=5.0)

        # Find our settlement
        settlement = next(
            r for r in results
            if r.payload.get("reference_msg_id") == offer_env.id
        )
        assert settlement.from_agent == "banker"
        assert settlement.type == MessageType.SETTLEMENT
        assert settlement.payload["buyer"] == "buyer-01"
        assert settlement.payload["seller"] == "seller-01"
        assert settlement.payload["item"] == "potato"
        assert settlement.payload["quantity"] == 5
        assert settlement.payload["total_price"] == 15.0
        assert settlement.payload["status"] == "completed"

    async def test_no_settlement_missing_reference(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """ACCEPT with nonexistent reference should not produce a settlement."""
        results, done = await _collect_settlements(test_client, 1)

        await _send_join(test_client, "buyer-01")
        await asyncio.sleep(0.3)

        accept_env = create_message(
            from_agent="buyer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload={"reference_msg_id": "nonexistent-id", "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, accept_env)

        # Wait a bit — no settlement should arrive
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=2.0)
        assert len(results) == 0

    async def test_no_settlement_insufficient_funds(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """Buyer without enough funds should not get a settlement."""
        results, done = await _collect_settlements(test_client, 1)

        await _send_join(test_client, "seller-01")
        await _send_join(test_client, "buyer-01")
        await asyncio.sleep(0.3)

        await _seed_inventory(test_client, "seller-01", {"potato": 100})
        await asyncio.sleep(0.3)

        # Offer for 200 coins worth (buyer only has 100)
        offer_env = create_message(
            from_agent="seller-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 100, "price_per_unit": 5.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, offer_env)
        await asyncio.sleep(0.3)

        accept_env = create_message(
            from_agent="buyer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload={"reference_msg_id": offer_env.id, "quantity": 100},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, accept_env)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=2.0)
        assert len(results) == 0

    async def test_no_settlement_insufficient_inventory(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """Seller without enough inventory at settlement time gets no settlement."""
        results, done = await _collect_settlements(test_client, 1)

        await _send_join(test_client, "seller-01")
        await _send_join(test_client, "buyer-01")
        await asyncio.sleep(0.3)

        # Seed seller with only 2 potatoes
        await _seed_inventory(test_client, "seller-01", {"potato": 2})
        await asyncio.sleep(0.3)

        # Offer 10 potatoes (more than they have — no escrow)
        offer_env = create_message(
            from_agent="seller-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, offer_env)
        await asyncio.sleep(0.3)

        # Accept — should fail at settlement because seller doesn't have 10
        accept_env = create_message(
            from_agent="buyer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload={"reference_msg_id": offer_env.id, "quantity": 10},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, accept_env)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(done.wait(), timeout=2.0)
        assert len(results) == 0

    async def test_self_loop_prevention(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """Banker should not process its own settlement messages.

        We trigger a valid trade, get a settlement, wait, and confirm
        only one settlement is produced (no infinite loop).
        """
        results, done = await _collect_settlements(test_client, 1)

        await _send_join(test_client, "seller-01")
        await _send_join(test_client, "buyer-01")
        await asyncio.sleep(0.3)

        await _seed_inventory(test_client, "seller-01", {"wood": 5})
        await asyncio.sleep(0.3)

        offer_env = create_message(
            from_agent="seller-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "wood", "quantity": 5, "price_per_unit": 3.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, offer_env)
        await asyncio.sleep(0.3)

        accept_env = create_message(
            from_agent="buyer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload={"reference_msg_id": offer_env.id, "quantity": 5},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, accept_env)

        await asyncio.wait_for(done.wait(), timeout=5.0)
        # Give time for any potential loop to produce extras
        await asyncio.sleep(1.0)

        our_settlements = [
            r for r in results
            if r.payload.get("reference_msg_id") == offer_env.id
        ]
        assert len(our_settlements) == 1

    async def test_craft_start_debits_inventory(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """CRAFT_START should debit input items from the agent's inventory."""
        await _send_join(test_client, "crafter-01")
        await asyncio.sleep(0.3)

        await _seed_inventory(test_client, "crafter-01", {"potato": 5, "onion": 3})
        await asyncio.sleep(0.3)

        craft_env = create_message(
            from_agent="crafter-01",
            topic=Topics.GENERAL,
            msg_type=MessageType.CRAFT_START,
            payload={"recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2},
            tick=1,
        )
        await test_client.publish(Topics.GENERAL, craft_env)
        await asyncio.sleep(0.5)

        # Verify state via banker's internal state
        account = banker.state.get_account("crafter-01")
        assert account is not None
        assert account.inventory.get("potato") == 3
        assert account.inventory.get("onion") == 2

    async def test_bid_accept_trade(
        self, banker: BankerAgent, test_client: MarketBusClient
    ):
        """BID → ACCEPT (seller accepts bid) produces a settlement."""
        results, done = await _collect_settlements(test_client, 1)

        await _send_join(test_client, "buyer-01")
        await _send_join(test_client, "seller-01")
        await asyncio.sleep(0.3)

        await _seed_inventory(test_client, "seller-01", {"wood": 10})
        await asyncio.sleep(0.3)

        # Buyer posts a bid
        bid_env = create_message(
            from_agent="buyer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.BID,
            payload={"item": "wood", "quantity": 3, "max_price_per_unit": 4.0},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, bid_env)
        await asyncio.sleep(0.3)

        # Seller accepts the bid
        accept_env = create_message(
            from_agent="seller-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.ACCEPT,
            payload={"reference_msg_id": bid_env.id, "quantity": 3},
            tick=1,
        )
        await test_client.publish(Topics.RAW_GOODS, accept_env)

        await asyncio.wait_for(done.wait(), timeout=5.0)

        settlement = next(
            r for r in results
            if r.payload.get("reference_msg_id") == bid_env.id
        )
        assert settlement.payload["buyer"] == "buyer-01"
        assert settlement.payload["seller"] == "seller-01"
        assert settlement.payload["item"] == "wood"
        assert settlement.payload["quantity"] == 3
        assert settlement.payload["total_price"] == 12.0
