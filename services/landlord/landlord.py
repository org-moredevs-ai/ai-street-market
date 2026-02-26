"""Landlord — property management, rentals, and land allocation.

Subscribes to tick events for rent collection and /market/property
for agent property inquiries. Emits rent_collected and property_transfer
events to the deterministic layer.
"""

from __future__ import annotations

import logging
from typing import Any

from streetmarket.agent.market_agent import MarketAgent
from streetmarket.ledger.interfaces import LedgerInterface
from streetmarket.models.envelope import Envelope
from streetmarket.models.ledger_event import EventTypes
from streetmarket.models.topics import Topics
from streetmarket.registry.registry import AgentRegistry, AgentState
from streetmarket.world_state.store import WorldStateStore

logger = logging.getLogger(__name__)

DEFAULT_RENT_INTERVAL = 10
DEFAULT_RENT_AMOUNT = 0.5
DEFAULT_GRACE_TICKS = 50


class LandlordAgent(MarketAgent):
    """Property manager — handles rentals, rent collection, land sales.

    Reads world state for property records, reasons about property
    matters, and emits rent/property events.
    """

    def __init__(
        self,
        *,
        ledger: LedgerInterface,
        registry: AgentRegistry,
        world_state: WorldStateStore,
        rent_interval: int = DEFAULT_RENT_INTERVAL,
        rent_amount: float = DEFAULT_RENT_AMOUNT,
        grace_ticks: int = DEFAULT_GRACE_TICKS,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ledger = ledger
        self._registry = registry
        self._world_state = world_state
        self._rent_interval = rent_interval
        self._rent_amount = rent_amount
        self._grace_ticks = grace_ticks
        self._last_rent_tick = 0

    def topics_to_subscribe(self) -> list[str]:
        return [Topics.TICK, Topics.PROPERTY]

    def build_system_prompt(self) -> str:
        return (
            f"You are {self.character_name}, the market's landlord.\n\n"
            f"PERSONALITY: {self.personality}\n\n"
            "YOUR DUTIES:\n"
            "- Manage property listings and rentals\n"
            "- Collect rent from tenants at regular intervals\n"
            "- Handle property purchase requests\n"
            "- Announce available properties\n\n"
            "When responding to property inquiries, provide helpful "
            "information about available land, prices, and conditions.\n"
        )

    async def on_tick(self, tick: int) -> None:
        """Collect rent at configured intervals."""
        if tick - self._last_rent_tick < self._rent_interval:
            return

        self._last_rent_tick = tick

        # Collect rent from all active agents past grace period
        agents = await self._registry.list_agents(state=AgentState.ACTIVE)
        for agent in agents:
            ticks_alive = tick - agent.joined_tick
            if ticks_alive < self._grace_ticks:
                continue

            # Check if agent owns a house (exempt from rent)
            properties = await self._world_state.list_properties(owner=agent.id)
            owns_house = any(p.get("type") == "house" for p in properties)
            if owns_house:
                continue

            # Emit rent collection event
            event = self._make_event(
                EventTypes.RENT_COLLECTED,
                {
                    "agent": agent.id,
                    "amount": self._rent_amount,
                },
            )
            await self.emit_event(event)

    async def on_message(self, envelope: Envelope) -> None:
        """Handle property inquiries."""
        if envelope.topic != Topics.PROPERTY:
            return

        # Get property context
        properties = await self._world_state.list_properties()
        available = [p for p in properties if p.get("owner") is None]

        context = (
            f"An agent is asking about properties.\n"
            f"Agent: {envelope.from_agent}\n"
            f"Their message: {envelope.message}\n"
            f"Total properties: {len(properties)}\n"
            f"Available (unowned): {len(available)}\n"
            "\nRespond to their inquiry in character."
        )

        raw_response = await self.reason(context)
        if raw_response:
            await self.respond(Topics.PROPERTY, raw_response)
