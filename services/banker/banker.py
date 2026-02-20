"""BankerAgent — subscribes to market messages and settles trades."""

import logging

from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Settlement,
    Topics,
    create_message,
)

from services.banker.rules import (
    process_accept,
    process_bid,
    process_craft_complete,
    process_craft_start,
    process_gather_result,
    process_join,
    process_offer,
)
from services.banker.state import BankerState, TradeResult

logger = logging.getLogger(__name__)


class BankerAgent:
    """The Banker is the economic authority of the AI Street Market.

    It subscribes to `market.>` (all market topics) and `/system/tick`.
    It maintains agent wallets and inventories, tracks an order book,
    and publishes Settlement messages when trades are completed.
    """

    AGENT_ID = "banker"

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._bus = MarketBusClient(nats_url)
        self._state = BankerState()

    @property
    def state(self) -> BankerState:
        """Expose state for testing."""
        return self._state

    async def start(self) -> None:
        """Connect to NATS and start listening."""
        await self._bus.connect()
        logger.info("Banker connected to NATS")

        await self._bus.subscribe("/market/>", self._on_market_message)
        logger.info("Banker subscribed to market.>")

        await self._bus.subscribe(Topics.TICK, self._on_tick)
        logger.info("Banker subscribed to %s", Topics.TICK)

        await self._bus.subscribe("/world/>", self._on_world_message)
        logger.info("Banker subscribed to world.>")

    async def stop(self) -> None:
        """Clean shutdown."""
        await self._bus.close()
        logger.info("Banker stopped")

    async def _on_market_message(self, envelope: Envelope) -> None:
        """Handle an incoming market message."""
        # Skip our own settlement messages to avoid infinite loops
        if (
            envelope.from_agent == self.AGENT_ID
            and envelope.type == MessageType.SETTLEMENT
        ):
            return

        msg_type = envelope.type

        if msg_type == MessageType.JOIN:
            errors = process_join(envelope, self._state)
            if errors:
                logger.warning("[tick %d] JOIN from %s failed: %s",
                               self._state.current_tick, envelope.from_agent, errors)

        elif msg_type == MessageType.OFFER:
            errors = process_offer(envelope, self._state)
            if errors:
                logger.warning("[tick %d] OFFER from %s rejected: %s",
                               self._state.current_tick, envelope.from_agent, errors)
            else:
                logger.info("[tick %d] OFFER from %s accepted into book",
                            self._state.current_tick, envelope.from_agent)

        elif msg_type == MessageType.BID:
            errors = process_bid(envelope, self._state)
            if errors:
                logger.warning("[tick %d] BID from %s rejected: %s",
                               self._state.current_tick, envelope.from_agent, errors)
            else:
                logger.info("[tick %d] BID from %s accepted into book",
                            self._state.current_tick, envelope.from_agent)

        elif msg_type == MessageType.ACCEPT:
            result = process_accept(envelope, self._state)
            if result.errors:
                logger.warning("[tick %d] ACCEPT from %s failed: %s",
                               self._state.current_tick, envelope.from_agent, result.errors)
            else:
                await self._publish_settlement(result)
                logger.info(
                    "[tick %d] SETTLED: %s sold %d %s to %s for %.2f",
                    self._state.current_tick,
                    result.seller,
                    result.quantity,
                    result.item,
                    result.buyer,
                    result.total_price,
                )

        elif msg_type == MessageType.CRAFT_START:
            errors = process_craft_start(envelope, self._state)
            if errors:
                logger.warning("[tick %d] CRAFT_START from %s rejected: %s",
                               self._state.current_tick, envelope.from_agent, errors)
            else:
                logger.info("[tick %d] CRAFT_START from %s — inputs debited",
                            self._state.current_tick, envelope.from_agent)

        elif msg_type == MessageType.CRAFT_COMPLETE:
            errors = process_craft_complete(envelope, self._state)
            if errors:
                logger.warning("[tick %d] CRAFT_COMPLETE from %s rejected: %s",
                               self._state.current_tick, envelope.from_agent, errors)
            else:
                logger.info("[tick %d] CRAFT_COMPLETE from %s — outputs credited",
                            self._state.current_tick, envelope.from_agent)

        # COUNTER, HEARTBEAT, VALIDATION_RESULT, SETTLEMENT, TICK — ignored

    async def _on_world_message(self, envelope: Envelope) -> None:
        """Handle incoming world messages — credit inventory on successful gathers."""
        if envelope.type != MessageType.GATHER_RESULT:
            return

        success = envelope.payload.get("success", False)
        if not success:
            return

        errors = process_gather_result(envelope, self._state)
        if errors:
            logger.warning(
                "[tick %d] GATHER_RESULT for %s failed: %s",
                self._state.current_tick,
                envelope.payload.get("agent_id", "?"),
                errors,
            )
        else:
            logger.info(
                "[tick %d] GATHER_RESULT: credited %d %s to %s",
                self._state.current_tick,
                envelope.payload.get("quantity", 0),
                envelope.payload.get("item", "?"),
                envelope.payload.get("agent_id", "?"),
            )

    async def _on_tick(self, envelope: Envelope) -> None:
        """Handle a system tick — advance state, purge expired orders."""
        tick_number = envelope.payload.get("tick_number", 0)
        self._state.advance_tick(tick_number)
        expired = self._state.purge_expired_orders()
        if expired:
            logger.info("Purged %d expired orders at tick %d", len(expired), tick_number)
        logger.info("Banker advanced to tick %d", tick_number)

    async def _publish_settlement(self, result: TradeResult) -> None:
        """Publish a Settlement message to the bank topic."""
        msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.BANK,
            msg_type=MessageType.SETTLEMENT,
            payload=Settlement(
                reference_msg_id=result.reference_msg_id,
                buyer=result.buyer,
                seller=result.seller,
                item=result.item,
                quantity=result.quantity,
                total_price=result.total_price,
                status="completed",
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.BANK, msg)
