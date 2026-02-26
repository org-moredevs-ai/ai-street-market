"""Meteo — the weather oracle of the market.

Subscribes to tick events. On each tick (or periodic intervals),
generates weather forecasts and updates using LLM reasoning.
Emits weather_change events to the deterministic layer.
"""

from __future__ import annotations

import logging
from typing import Any

from streetmarket.agent.market_agent import MarketAgent
from streetmarket.models.ledger_event import EventTypes
from streetmarket.models.topics import Topics
from streetmarket.world_state.store import WorldStateStore

logger = logging.getLogger(__name__)

# Meteo broadcasts every N ticks (not every tick)
DEFAULT_FORECAST_INTERVAL = 10


class MeteoAgent(MarketAgent):
    """Weather oracle — generates forecasts and weather updates.

    Reads world state for current weather, reasons about patterns,
    and emits weather_change events for the deterministic layer.
    """

    def __init__(
        self,
        *,
        world_state: WorldStateStore,
        world_policy_text: str = "",
        forecast_interval: int = DEFAULT_FORECAST_INTERVAL,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._world_state = world_state
        self._world_policy_text = world_policy_text
        self._forecast_interval = forecast_interval
        self._last_forecast_tick = 0

    def topics_to_subscribe(self) -> list[str]:
        return [Topics.TICK]

    def build_system_prompt(self) -> str:
        return (
            f"You are {self.character_name}, the weather oracle of the market.\n\n"
            f"PERSONALITY: {self.personality}\n\n"
            f"WORLD CONTEXT:\n{self._world_policy_text}\n\n"
            "YOUR ROLE:\n"
            "- Observe weather patterns and generate forecasts\n"
            "- Announce weather changes to the market\n"
            "- Warn about extreme weather that affects crops and resources\n"
            "- Be dramatic and entertaining, but accurate\n\n"
            "RESPOND with a JSON object:\n"
            "{\n"
            '  "forecast": "Your weather announcement in character (1-2 sentences)",\n'
            '  "condition": "sunny|cloudy|rainy|stormy|foggy|snowy|windy|clear",\n'
            '  "temperature": "hot|warm|mild|cool|cold|freezing",\n'
            '  "wind": "calm|light|moderate|strong|gale",\n'
            '  "effects": [{"type": "crop_boost|crop_damage|area_blocked|'
            'construction_delay", "target": "location", "modifier": 1.0, '
            '"reason": "why"}]\n'
            "}\n"
        )

    async def on_tick(self, tick: int) -> None:
        """Generate weather forecast at configured intervals."""
        if tick - self._last_forecast_tick < self._forecast_interval:
            return

        self._last_forecast_tick = tick
        weather = await self._world_state.get_weather()

        context = (
            f"Current tick: {tick}\n"
            f"Current weather: {weather.condition}, "
            f"temp={weather.temperature}, wind={weather.wind}\n"
            f"Weather started at tick: {weather.started_tick}\n"
            "Generate a new weather forecast. Consider seasonal patterns "
            "and the time that has passed."
        )

        result = await self.reason_json(context)
        if not result:
            return

        # Publish natural language forecast
        forecast = result.get("forecast", "")
        if forecast:
            await self.respond(Topics.WEATHER, forecast)

        # Emit structured weather_change event
        event = self._make_event(
            EventTypes.WEATHER_CHANGE,
            {
                "condition": result.get("condition", weather.condition),
                "temperature": result.get("temperature", weather.temperature),
                "wind": result.get("wind", weather.wind),
                "effects": result.get("effects", []),
            },
        )
        await self.emit_event(event)
