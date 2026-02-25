"""TownCrierService — subscribes to market/system/world topics, accumulates
events, and publishes periodic LLM-generated (or fallback) narrations.
"""

from __future__ import annotations

import logging

from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Narration,
    Topics,
    create_message,
)

from services.town_crier.narrator import Narrator
from services.town_crier.state import TownCrierState

logger = logging.getLogger(__name__)


class TownCrierService:
    """The Town Crier watches all market activity and publishes narrative summaries.

    Subscribes to `/market/>`, `/system/>`, and `/world/>`.
    Every NARRATION_INTERVAL ticks, generates a narration and publishes it
    to `/market/square`.
    """

    AGENT_ID = "town_crier"

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._bus = MarketBusClient(nats_url)
        self._state = TownCrierState()
        self._narrator = Narrator()

    @property
    def state(self) -> TownCrierState:
        """Expose state for testing."""
        return self._state

    @property
    def narrator(self) -> Narrator:
        """Expose narrator for testing."""
        return self._narrator

    async def start(self) -> None:
        """Connect to NATS and subscribe to all relevant topics."""
        await self._bus.connect()
        logger.info("Town Crier connected to NATS")

        await self._bus.subscribe("/market/>", self._on_market_message)
        logger.info("Town Crier subscribed to market.>")

        await self._bus.subscribe("/system/>", self._on_system_message)
        logger.info("Town Crier subscribed to system.>")

        await self._bus.subscribe("/world/>", self._on_world_message)
        logger.info("Town Crier subscribed to world.>")

    async def stop(self) -> None:
        """Clean shutdown."""
        await self._bus.close()
        logger.info("Town Crier stopped")

    async def _on_system_message(self, envelope: Envelope) -> None:
        """Handle system messages (TICK, ENERGY_UPDATE)."""
        if envelope.type == MessageType.TICK:
            tick_number = envelope.payload.get("tick_number", 0)
            self._state.advance_tick(tick_number)
            await self._maybe_narrate(tick_number)

        elif envelope.type == MessageType.ENERGY_UPDATE:
            levels = envelope.payload.get("energy_levels", {})
            self._state.update_energy(levels)

    async def _on_market_message(self, envelope: Envelope) -> None:
        """Handle market messages (settlements, bankruptcies, joins, crafts, etc.)."""
        # Skip our own messages
        if envelope.from_agent == self.AGENT_ID:
            return

        msg_type = envelope.type

        if msg_type == MessageType.SETTLEMENT:
            p = envelope.payload
            self._state.record_settlement(
                buyer=p.get("buyer", ""),
                seller=p.get("seller", ""),
                item=p.get("item", ""),
                quantity=p.get("quantity", 0),
                total_price=p.get("total_price", 0.0),
            )
            self._state.record_activity(p.get("buyer", ""))
            self._state.record_activity(p.get("seller", ""))

        elif msg_type == MessageType.BANKRUPTCY:
            self._state.record_bankruptcy(envelope.payload.get("agent_id", ""))

        elif msg_type == MessageType.RENT_DUE:
            p = envelope.payload
            self._state.record_rent(
                agent_id=p.get("agent_id", ""),
                amount=p.get("amount", 0.0),
                wallet_after=p.get("wallet_after", 0.0),
            )

        elif msg_type == MessageType.JOIN:
            self._state.record_join(envelope.payload.get("agent_id", ""))

        elif msg_type == MessageType.CRAFT_COMPLETE:
            p = envelope.payload
            output = p.get("output", {})
            # output is a dict like {"soup": 1}
            for item, qty in output.items() if isinstance(output, dict) else []:
                self._state.record_craft(
                    agent_id=p.get("agent", ""),
                    recipe=p.get("recipe", ""),
                    output=item,
                    quantity=qty,
                )

        elif msg_type in (
            MessageType.OFFER,
            MessageType.BID,
            MessageType.ACCEPT,
            MessageType.CRAFT_START,
            MessageType.GATHER,
        ):
            self._state.record_activity(envelope.from_agent)

    async def _on_world_message(self, envelope: Envelope) -> None:
        """Handle world messages (NATURE_EVENT)."""
        if envelope.type == MessageType.NATURE_EVENT:
            p = envelope.payload
            self._state.record_nature_event(
                title=p.get("title", ""),
                description=p.get("description", ""),
            )

    async def _maybe_narrate(self, tick: int) -> None:
        """Generate and publish a narration if it's time.

        Special narrations:
        - tick 1: "The market is open!" announcement (before agents arrive)
        - Every time a new agent joins: welcome narration
        - Every NARRATION_INTERVAL ticks: regular market update
        """
        opening = tick == 1
        welcome = len(self._state.joins) > 0 and tick > 1
        if not opening and not welcome and not self._state.should_narrate(tick):
            return

        weather = self._state.compute_market_weather()
        summary = self._state.get_window_summary()

        result = await self._narrator.generate_narration(summary, weather)

        narration_payload = Narration(
            headline=result.headline,
            body=result.body,
            weather=weather,
            predictions=result.predictions,
            drama_level=result.drama_level,
            window_start_tick=self._state.window_start_tick,
            window_end_tick=tick,
        )

        envelope = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.SQUARE,
            msg_type=MessageType.NARRATION,
            payload=narration_payload,
            tick=tick,
        )

        await self._bus.publish(Topics.SQUARE, envelope)
        logger.info(
            "[tick %d] Narration: %s (weather=%s, drama=%d)",
            tick,
            result.headline,
            weather.value,
            result.drama_level,
        )

        self._state.reset_window()
