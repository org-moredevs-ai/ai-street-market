"""Narrator — LLM-powered narrative generation for the Town Crier.

Calls Claude Haiku to generate dramatic market narrations using tool_use
for structured output. Falls back to deterministic bullet-point summaries
on any error or when LLM is disabled.

Follows the same pattern as services/world/nature.py.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from streetmarket.models.messages import MarketWeather

logger = logging.getLogger(__name__)

# Tool definition for structured output
NARRATION_TOOL = {
    "name": "publish_narration",
    "description": (
        "Publish a narrative summary of recent market activity. "
        "You are a medieval town announcer meets Wall Street commentator."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "maxLength": 100,
                "description": "Punchy one-liner summarizing the market mood",
            },
            "body": {
                "type": "string",
                "maxLength": 500,
                "description": "2-4 paragraph dramatic narration of events",
            },
            "predictions": {
                "type": "string",
                "maxLength": 200,
                "description": "Optional market predictions (can be wrong!)",
            },
            "drama_level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "1=quiet day, 3=interesting, 5=explosive",
            },
        },
        "required": ["headline", "body", "drama_level"],
    },
}

SYSTEM_PROMPT = (
    "You are the Town Crier of the AI Street Market — a medieval town announcer "
    "who also moonlights as a financial commentator. Your job is to narrate the "
    "market activity dramatically and entertainingly.\n\n"
    "Style guidelines:\n"
    "- Start announcements with 'Hear ye, hear ye!' or similar medieval flair\n"
    "- Reference agents by name (farmer, chef, baker, etc.)\n"
    "- Use market weather to set the tone\n"
    "- Make bold predictions (you're often wrong, and that's entertaining)\n"
    "- Keep it fun, dramatic, and opinionated\n"
    "- Use financial jargon mixed with medieval expressions\n"
    "- Never break character"
)


@dataclass
class NarrationResult:
    """The output of a narration generation."""

    headline: str
    body: str
    predictions: str | None
    drama_level: int


@dataclass
class Narrator:
    """LLM-powered narrator for market events.

    When enabled, calls Claude Haiku with tool_use for structured output.
    Falls back to deterministic summaries on any error.
    """

    enabled: bool = False
    _client: object | None = None  # anthropic.AsyncAnthropic

    def __post_init__(self) -> None:
        self.enabled = os.environ.get("TOWN_CRIER_USE_LLM", "false").lower() == "true"
        if self.enabled:
            try:
                import anthropic

                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    logger.warning("TOWN_CRIER_USE_LLM=true but no ANTHROPIC_API_KEY — disabling")
                    self.enabled = False
                else:
                    self._client = anthropic.AsyncAnthropic()
                    logger.info("Narrator LLM enabled — will generate narrative summaries")
            except ImportError:
                logger.warning("anthropic package not installed — disabling Narrator LLM")
                self.enabled = False

    async def generate_narration(
        self, summary: dict, weather: MarketWeather
    ) -> NarrationResult:
        """Generate a narration from the window summary.

        Tries LLM first (if enabled), falls back to deterministic.
        """
        if self.enabled:
            try:
                return await self._call_llm(summary, weather)
            except Exception as e:
                logger.warning("Narrator LLM call failed: %s — using fallback", e)

        return self._fallback_narration(summary, weather)

    async def _call_llm(
        self, summary: dict, weather: MarketWeather
    ) -> NarrationResult:
        """Call Claude Haiku for a narrative summary."""
        client = self._client
        if client is None:
            raise RuntimeError("Narrator client not initialized")

        prompt = self._build_prompt(summary, weather)

        response = await client.messages.create(  # type: ignore[union-attr]
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            tools=[NARRATION_TOOL],  # type: ignore[list-item]
            messages=[{"role": "user", "content": prompt}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "publish_narration":
                return self._parse_tool_response(block.input)

        raise ValueError("LLM response had no publish_narration tool_use")

    def _build_prompt(self, summary: dict, weather: MarketWeather) -> str:
        """Build the LLM prompt from window summary data."""
        parts = [
            f"Market weather: {weather.value.upper()}",
            f"Ticks {summary['window_start_tick']} to {summary['window_end_tick']}",
        ]

        # Settlements
        settlements = summary.get("settlements", [])
        if settlements:
            trade_lines = []
            for s in settlements:
                ppu = s["total_price"] / s["quantity"] if s["quantity"] > 0 else 0
                trade_lines.append(
                    f"  {s['buyer']} bought {s['quantity']}x {s['item']} "
                    f"from {s['seller']} at {ppu:.1f}/unit"
                )
            parts.append(f"Trades ({len(settlements)}):\n" + "\n".join(trade_lines))
        else:
            parts.append("No trades this window.")

        # Crafts
        crafts = summary.get("crafts", [])
        if crafts:
            craft_lines = [f"  {c['agent_id']} crafted {c['output']}" for c in crafts]
            parts.append("Crafting:\n" + "\n".join(craft_lines))

        # Bankruptcies
        bankruptcies = summary.get("bankruptcies", [])
        if bankruptcies:
            parts.append(f"BANKRUPTCIES: {', '.join(bankruptcies)}")

        # Nature events
        for event in summary.get("nature_events", []):
            parts.append(f"Nature event: {event['title']} — {event['description']}")

        # Energy
        energy = summary.get("energy_levels", {})
        if energy:
            energy_str = ", ".join(
                f"{a}: {e:.0f}" for a, e in sorted(energy.items())
            )
            parts.append(f"Energy levels: {energy_str}")

        # Joins
        joins = summary.get("joins", [])
        if joins:
            parts.append(f"New arrivals: {', '.join(joins)}")

        # All-time stats
        parts.append(
            f"All-time: {summary.get('total_settlements', 0)} trades, "
            f"{summary.get('total_coins_traded', 0):.0f} coins exchanged, "
            f"{summary.get('total_crafts', 0)} items crafted"
        )

        return "\n\n".join(parts)

    def _parse_tool_response(self, tool_input: dict) -> NarrationResult:
        """Parse the LLM's tool_use response into a NarrationResult."""
        headline = str(tool_input.get("headline", "Market Update"))[:100]
        body = str(tool_input.get("body", ""))[:500]
        predictions = tool_input.get("predictions")
        if predictions:
            predictions = str(predictions)[:200]
        drama_level = max(1, min(5, int(tool_input.get("drama_level", 3))))

        return NarrationResult(
            headline=headline,
            body=body,
            predictions=predictions,
            drama_level=drama_level,
        )

    def _fallback_narration(
        self, summary: dict, weather: MarketWeather
    ) -> NarrationResult:
        """Generate a deterministic bullet-point summary."""
        lines: list[str] = []
        settlements = summary.get("settlements", [])
        crafts = summary.get("crafts", [])
        bankruptcies = summary.get("bankruptcies", [])
        joins = summary.get("joins", [])
        nature_events = summary.get("nature_events", [])

        # Headline
        if bankruptcies:
            headline = f"Crisis! {', '.join(bankruptcies)} declared bankrupt"
        elif len(settlements) >= 3:
            headline = f"Busy market: {len(settlements)} trades completed"
        elif joins:
            headline = f"Welcome {', '.join(joins)} to the market!"
        elif nature_events:
            headline = nature_events[0]["title"]
        else:
            headline = "Market report"

        # Body
        tick_range = (
            f"Ticks {summary['window_start_tick']}-{summary['window_end_tick']}"
        )
        lines.append(f"[{tick_range}] Weather: {weather.value}")

        if settlements:
            total = sum(s["total_price"] for s in settlements)
            lines.append(f"Trades: {len(settlements)} for {total:.0f} coins")

        if crafts:
            craft_summary: dict[str, int] = {}
            for c in crafts:
                craft_summary[c["output"]] = craft_summary.get(c["output"], 0) + 1
            craft_str = ", ".join(f"{q}x {item}" for item, q in craft_summary.items())
            lines.append(f"Crafted: {craft_str}")

        if bankruptcies:
            lines.append(f"Bankrupt: {', '.join(bankruptcies)}")

        if nature_events:
            for e in nature_events:
                lines.append(f"Nature: {e['title']}")

        if joins:
            lines.append(f"Joined: {', '.join(joins)}")

        body = "\n".join(lines)[:500]

        # Drama level from weather
        drama_map = {
            MarketWeather.STABLE: 1,
            MarketWeather.BOOMING: 3,
            MarketWeather.STRESSED: 3,
            MarketWeather.CHAOTIC: 4,
            MarketWeather.CRISIS: 5,
        }
        drama_level = drama_map.get(weather, 2)

        return NarrationResult(
            headline=headline[:100],
            body=body,
            predictions=None,
            drama_level=drama_level,
        )
