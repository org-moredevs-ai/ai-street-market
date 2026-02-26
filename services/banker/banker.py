"""BankerAgent — subscribes to market messages and settles trades."""

import logging

from streetmarket import (
    Bankruptcy,
    ConsumeResult,
    EconomyHalt,
    Envelope,
    ItemSpoiled,
    MarketBusClient,
    MessageType,
    RentDue,
    Settlement,
    Topics,
    create_message,
)

from services.banker.rules import (
    RentResultData,
    check_all_bankruptcies,
    process_accept,
    process_bid,
    process_consume,
    process_craft_complete,
    process_craft_start,
    process_gather_result,
    process_join,
    process_offer,
    process_rent,
)
from services.banker.state import BankerState, SpoilageResult, TradeResult

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
        # Skip our own messages to avoid infinite loops
        if envelope.from_agent == self.AGENT_ID and envelope.type in (
            MessageType.SETTLEMENT,
            MessageType.CONSUME_RESULT,
            MessageType.ITEM_SPOILED,
        ):
            return

        # Reject all actions from bankrupt agents (except JOIN — no-op anyway)
        if envelope.type != MessageType.JOIN and self._state.is_bankrupt(envelope.from_agent):
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

        elif msg_type == MessageType.CONSUME:
            consume_result = process_consume(envelope, self._state)
            if consume_result.errors:
                logger.warning("[tick %d] CONSUME from %s rejected: %s",
                               self._state.current_tick, envelope.from_agent, consume_result.errors)
                await self._publish_consume_result(
                    consume_result.reference_msg_id,
                    consume_result.agent_id,
                    consume_result.item,
                    consume_result.quantity,
                    success=False,
                    energy_restored=0.0,
                    reason="; ".join(consume_result.errors),
                )
            else:
                await self._publish_consume_result(
                    consume_result.reference_msg_id,
                    consume_result.agent_id,
                    consume_result.item,
                    consume_result.quantity,
                    success=True,
                    energy_restored=consume_result.energy_restored,
                )
                logger.info(
                    "[tick %d] CONSUME from %s — %d %s consumed, %.1f energy to restore",
                    self._state.current_tick,
                    envelope.from_agent,
                    consume_result.quantity,
                    consume_result.item,
                    consume_result.energy_restored,
                )

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
        """Handle a system tick — advance state, purge expired orders, rent, bankruptcy."""
        if envelope.type != MessageType.TICK:
            return
        tick_number = envelope.payload.get("tick_number", 0)
        if not self._state.advance_tick(tick_number):
            logger.warning(
                "Banker ignoring stale tick %d (current: %d)",
                tick_number, self._state.current_tick,
            )
            return
        expired = self._state.purge_expired_orders()
        if expired:
            logger.info("Purged %d expired orders at tick %d", len(expired), tick_number)

        # Process spoilage BEFORE rent (removes rotten items)
        spoilage_results = self._state.process_spoilage()
        for spoilage in spoilage_results:
            await self._publish_item_spoiled(spoilage)
            logger.info(
                "[tick %d] SPOILED: %d %s from %s",
                tick_number, spoilage.quantity, spoilage.item, spoilage.agent_id,
            )

        # Process rent for all agents
        for agent_id in self._state.get_all_agent_ids():
            if self._state.is_bankrupt(agent_id):
                continue
            rent_result = process_rent(agent_id, self._state)
            # Only publish RENT_DUE when rent was actually charged
            if rent_result.amount > 0 or not rent_result.exempt:
                await self._publish_rent_due(rent_result)
            if rent_result.amount > 0:
                logger.info(
                    "[tick %d] Rent: %s paid %.2f (wallet: %.2f)",
                    tick_number,
                    agent_id,
                    rent_result.amount,
                    rent_result.wallet_after,
                )

        # Check bankruptcies after rent
        newly_bankrupt = check_all_bankruptcies(self._state)
        for agent_id in newly_bankrupt:
            await self._publish_bankruptcy(agent_id)
            logger.warning("[tick %d] BANKRUPTCY: %s declared bankrupt", tick_number, agent_id)

        # Halt economy if all agents are bankrupt
        if newly_bankrupt and self._state.all_agents_bankrupt():
            await self._publish_economy_halt(tick_number)
            logger.warning(
                "[tick %d] ECONOMY HALT: All agents bankrupt — stopping market",
                tick_number,
            )

        logger.info("Banker advanced to tick %d", tick_number)

    async def _publish_settlement(self, result: TradeResult) -> None:
        """Publish a Settlement message to the bank topic."""
        # Include wallet-after for both parties so the bridge can track wallets
        buyer_account = self._state.get_account(result.buyer)
        seller_account = self._state.get_account(result.seller)
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
                buyer_wallet_after=buyer_account.wallet if buyer_account else None,
                seller_wallet_after=seller_account.wallet if seller_account else None,
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.BANK, msg)

    async def _publish_consume_result(
        self,
        reference_msg_id: str,
        agent_id: str,
        item: str,
        quantity: int,
        *,
        success: bool,
        energy_restored: float,
        reason: str | None = None,
    ) -> None:
        """Publish a ConsumeResult message to the bank topic."""
        msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.BANK,
            msg_type=MessageType.CONSUME_RESULT,
            payload=ConsumeResult(
                reference_msg_id=reference_msg_id,
                agent_id=agent_id,
                item=item,
                quantity=quantity,
                success=success,
                energy_restored=energy_restored,
                reason=reason,
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.BANK, msg)

    async def _publish_rent_due(self, rent_data: RentResultData) -> None:
        """Publish a RentDue message to the bank topic."""
        msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.BANK,
            msg_type=MessageType.RENT_DUE,
            payload=RentDue(
                agent_id=rent_data.agent_id,
                amount=rent_data.amount,
                wallet_after=rent_data.wallet_after,
                exempt=rent_data.exempt,
                reason=rent_data.reason,
                treasury_balance=self._state.town_treasury,
                total_rent_collected=self._state.total_rent_collected,
                confiscated_items=rent_data.confiscated_items,
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.BANK, msg)

    async def _publish_item_spoiled(self, spoilage: SpoilageResult) -> None:
        """Publish an ItemSpoiled message to the bank topic."""
        msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.BANK,
            msg_type=MessageType.ITEM_SPOILED,
            payload=ItemSpoiled(
                agent_id=spoilage.agent_id,
                item=spoilage.item,
                quantity=spoilage.quantity,
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.BANK, msg)

    def _bankruptcy_reason(self, agent_id: str) -> str:
        """Build a human-readable bankruptcy reason string."""
        zero_since = self._state.get_zero_wallet_since(agent_id)
        duration = self._state.current_tick - zero_since
        return (
            f"Zero wallet since tick {zero_since} ({duration} ticks) "
            f"— declared bankrupt at tick {self._state.current_tick}"
        )

    async def _publish_bankruptcy(self, agent_id: str) -> None:
        """Publish a Bankruptcy message to the bank topic."""
        msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.BANK,
            msg_type=MessageType.BANKRUPTCY,
            payload=Bankruptcy(
                agent_id=agent_id,
                reason=self._bankruptcy_reason(agent_id),
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.BANK, msg)

    async def _publish_economy_halt(self, tick_number: int) -> None:
        """Publish an ECONOMY_HALT message — all agents are bankrupt."""
        agents = self._state.get_all_agent_ids()
        msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.BANK,
            msg_type=MessageType.ECONOMY_HALT,
            payload=EconomyHalt(
                reason=f"All {len(agents)} agents declared bankrupt",
                final_tick=tick_number,
            ),
            tick=tick_number,
        )
        await self._bus.publish(Topics.BANK, msg)
