"""Nature — the living world: crops, resources, fields.

Subscribes to tick events. On each tick, evaluates field growth,
resource replenishment, and environmental changes. Emits field_update
and resource_update events to the deterministic layer.
"""

from __future__ import annotations

import logging
from typing import Any

from streetmarket.agent.market_agent import MarketAgent
from streetmarket.models.envelope import Envelope
from streetmarket.models.ledger_event import EventTypes
from streetmarket.models.topics import Topics
from streetmarket.world_state.store import WorldStateStore

logger = logging.getLogger(__name__)

DEFAULT_NATURE_INTERVAL = 5


class NatureAgent(MarketAgent):
    """The living world — manages crops, resources, and field conditions.

    Reads world state for fields and resources, reasons about growth
    and conditions, and emits field_update/resource_update events.
    """

    def __init__(
        self,
        *,
        world_state: WorldStateStore,
        world_policy_text: str = "",
        nature_interval: int = DEFAULT_NATURE_INTERVAL,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._world_state = world_state
        self._world_policy_text = world_policy_text
        self._nature_interval = nature_interval
        self._last_nature_tick = 0

    def topics_to_subscribe(self) -> list[str]:
        return [Topics.TICK, Topics.LEDGER]

    def build_system_prompt(self) -> str:
        return (
            f"You are {self.character_name}, the spirit of nature.\n\n"
            f"PERSONALITY: {self.personality}\n\n"
            f"WORLD CONTEXT:\n{self._world_policy_text}\n\n"
            "YOUR ROLE:\n"
            "- Monitor field conditions and crop growth\n"
            "- Determine when crops are ready for harvest\n"
            "- Manage resource availability (wood, stone, fish, herbs)\n"
            "- Announce nature events to the market\n"
            "- React to weather changes (storms damage crops, rain helps)\n\n"
            "RESPOND with a JSON object:\n"
            "{\n"
            '  "announcement": "Nature update in character (1-2 sentences)",\n'
            '  "field_updates": [{"field_id": "id", "status": '
            '"empty|planted|growing|ready|flooded|depleted", '
            '"crop": "name or null", "ready_tick": null}],\n'
            '  "resource_updates": [{"resource_id": "id", '
            '"quantity_delta": 0, "reason": "why"}]\n'
            "}\n"
        )

    async def on_tick(self, tick: int) -> None:
        """Evaluate nature state at configured intervals."""
        if tick - self._last_nature_tick < self._nature_interval:
            return

        self._last_nature_tick = tick

        fields = await self._world_state.list_fields()
        resources = await self._world_state.list_resources()
        weather = await self._world_state.get_weather()

        context = (
            f"Current tick: {tick}\n"
            f"Weather: {weather.condition}, temp={weather.temperature}\n"
            f"Fields ({len(fields)}):\n"
        )
        for f in fields:
            context += (
                f"  - {f.id}: type={f.type}, status={f.status.value}, "
                f"crop={f.crop}, planted_tick={f.planted_tick}, "
                f"ready_tick={f.ready_tick}\n"
            )
        context += f"Resources ({len(resources)}):\n"
        for r in resources:
            context += f"  - {r.id}: type={r.type}, qty={r.quantity}, location={r.location}\n"
        context += (
            "\nEvaluate conditions. Update fields that should change. "
            "Replenish resources as appropriate."
        )

        result = await self.reason_json(context)
        if not result:
            return

        # Publish natural language announcement
        announcement = result.get("announcement", "")
        if announcement:
            await self.respond(Topics.WEATHER, announcement)

        # Emit field_update events
        for update in result.get("field_updates", []):
            field_id = update.get("field_id")
            if field_id:
                event = self._make_event(
                    EventTypes.FIELD_UPDATE,
                    {
                        "field_id": field_id,
                        "status": update.get("status"),
                        "crop": update.get("crop"),
                        "ready_tick": update.get("ready_tick"),
                    },
                )
                await self.emit_event(event)

        # Emit resource_update events
        for update in result.get("resource_updates", []):
            resource_id = update.get("resource_id")
            if resource_id:
                event = self._make_event(
                    EventTypes.RESOURCE_UPDATE,
                    {
                        "resource_id": resource_id,
                        "quantity_delta": update.get("quantity_delta", 0),
                        "reason": update.get("reason", ""),
                    },
                )
                await self.emit_event(event)

    async def on_message(self, envelope: Envelope) -> None:
        """React to weather changes from Meteo."""
        if envelope.topic == Topics.LEDGER:
            try:
                from streetmarket.agent.llm_brain import extract_json

                event_data = extract_json(envelope.message)
                if event_data.get("event") == EventTypes.WEATHER_CHANGE:
                    logger.info(
                        "Nature noticed weather change: %s",
                        event_data.get("data", {}).get("condition", "unknown"),
                    )
            except (ValueError, KeyError):
                pass
