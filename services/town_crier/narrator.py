"""Town Crier — dramatic narration for the market viewer.

Subscribes to all public topics and /system/ledger. Generates
entertaining narrations for the viewer. Does NOT emit ledger events
— Town Crier is purely entertainment.
"""

from __future__ import annotations

import logging
from typing import Any

from streetmarket.agent.market_agent import MarketAgent
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics

logger = logging.getLogger(__name__)

DEFAULT_NARRATION_INTERVAL = 15
MAX_RECENT_EVENTS = 20


class TownCrierAgent(MarketAgent):
    """Dramatic narrator — generates stories for the viewer.

    Reads all public messages and ledger events, collects interesting
    happenings, and periodically generates dramatic narrations.
    """

    def __init__(
        self,
        *,
        narration_interval: int = DEFAULT_NARRATION_INTERVAL,
        season_description: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._narration_interval = narration_interval
        self._season_description = season_description
        self._last_narration_tick = 0
        self._recent_events: list[str] = []

    def topics_to_subscribe(self) -> list[str]:
        return [
            Topics.TICK,
            Topics.SQUARE,
            Topics.TRADES,
            Topics.BANK,
            Topics.WEATHER,
            Topics.PROPERTY,
            Topics.LEDGER,
        ]

    def build_system_prompt(self) -> str:
        return (
            f"You are {self.character_name}, the town crier of the market.\n\n"
            f"PERSONALITY: {self.personality}\n\n"
            f"SEASON: {self._season_description}\n\n"
            "YOUR ROLE:\n"
            "- Narrate market events in dramatic, entertaining fashion\n"
            "- Highlight interesting trades, newcomers, and drama\n"
            "- Tell stories about underdog agents and spectacular failures\n"
            "- Use medieval flair and theatrical language\n"
            "- Keep narrations concise (2-4 sentences max)\n\n"
            "Respond with ONLY your narration text (no JSON needed).\n"
        )

    async def on_tick(self, tick: int) -> None:
        """Generate narration at configured intervals."""
        if tick - self._last_narration_tick < self._narration_interval:
            return
        if not self._recent_events:
            return

        self._last_narration_tick = tick

        context = f"Current tick: {tick}\nRecent events to narrate:\n"
        for event in self._recent_events[-MAX_RECENT_EVENTS:]:
            context += f"  - {event}\n"
        context += (
            "\nCreate a dramatic narration covering the most interesting "
            "recent events. Be entertaining and theatrical."
        )

        raw_response = await self.reason(context)
        if raw_response:
            # Strip any JSON wrapper — Town Crier responds in plain text
            narration = raw_response.strip()
            if len(narration) > 800:
                narration = narration[:797] + "..."
            await self.respond(Topics.NEWS, narration)

        # Clear events after narrating
        self._recent_events.clear()

    async def on_message(self, envelope: Envelope) -> None:
        """Collect interesting events for narration."""
        # Skip our own messages and tick messages
        if envelope.from_agent == self.agent_id:
            return

        summary = f"[{envelope.topic}] {envelope.from_agent}: {envelope.message[:150]}"
        self._recent_events.append(summary)
