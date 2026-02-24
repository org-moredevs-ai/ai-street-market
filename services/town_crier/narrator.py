"""Narrator — LLM-powered narrative generation for the Town Crier.

Uses LangChain/OpenRouter for structured narration output.
LLM is always on — there is no toggle. Falls back to deterministic
summaries only on runtime errors (not by configuration).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from streetmarket.agent.llm_config import LLMConfig
from streetmarket.models.messages import MarketWeather

logger = logging.getLogger(__name__)

LLM_TIMEOUT = 15.0

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


class NarrationSchema(BaseModel):
    """Structured output schema for narration generation."""

    headline: str = Field(
        description="Punchy one-liner summarizing the market mood",
        max_length=100,
    )
    body: str = Field(description="2-4 paragraph dramatic narration of events", max_length=500)
    predictions: str | None = Field(
        default=None,
        description="Optional market predictions (can be wrong!)",
    )
    drama_level: int = Field(
        description="1=quiet day, 3=interesting, 5=explosive",
        ge=1,
        le=5,
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

    Always uses LLM via OpenRouter. Falls back to deterministic
    summaries only on runtime errors.
    """

    async def generate_narration(
        self, summary: dict[str, Any], weather: MarketWeather
    ) -> NarrationResult:
        """Generate a narration from the window summary.

        Tries LLM first, falls back to deterministic on error.
        """
        try:
            return await self._call_llm(summary, weather)
        except Exception as e:
            logger.warning("Narrator LLM call failed: %s — using fallback", e)
            return self._fallback_narration(summary, weather)

    async def _call_llm(
        self, summary: dict[str, Any], weather: MarketWeather
    ) -> NarrationResult:
        """Call LLM via OpenRouter for a narrative summary."""
        config = LLMConfig.for_service("town_crier")
        llm = ChatOpenAI(
            model=config.model,
            api_key=config.api_key,  # type: ignore[arg-type]
            base_url=config.api_base,
            max_tokens=config.max_tokens,  # type: ignore[call-arg]
            temperature=config.temperature,
        )
        structured = llm.with_structured_output(NarrationSchema)
        prompt = self._build_prompt(summary, weather)

        result: NarrationSchema = await asyncio.wait_for(
            structured.ainvoke([  # type: ignore[arg-type]
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]),
            timeout=LLM_TIMEOUT,
        )

        return NarrationResult(
            headline=result.headline[:100],
            body=result.body[:500],
            predictions=result.predictions[:200] if result.predictions else None,
            drama_level=max(1, min(5, result.drama_level)),
        )

    def _build_prompt(self, summary: dict[str, Any], weather: MarketWeather) -> str:
        """Build the LLM prompt from window summary data."""
        parts = [
            f"Market weather: {weather.value.upper()}",
            f"Ticks {summary['window_start_tick']} to {summary['window_end_tick']}",
        ]

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

        crafts = summary.get("crafts", [])
        if crafts:
            craft_lines = [f"  {c['agent_id']} crafted {c['output']}" for c in crafts]
            parts.append("Crafting:\n" + "\n".join(craft_lines))

        bankruptcies = summary.get("bankruptcies", [])
        if bankruptcies:
            parts.append(f"BANKRUPTCIES: {', '.join(bankruptcies)}")

        for event in summary.get("nature_events", []):
            parts.append(f"Nature event: {event['title']} — {event['description']}")

        energy = summary.get("energy_levels", {})
        if energy:
            energy_str = ", ".join(
                f"{a}: {e:.0f}" for a, e in sorted(energy.items())
            )
            parts.append(f"Energy levels: {energy_str}")

        joins = summary.get("joins", [])
        if joins:
            parts.append(f"New arrivals: {', '.join(joins)}")

        parts.append(
            f"All-time: {summary.get('total_settlements', 0)} trades, "
            f"{summary.get('total_coins_traded', 0):.0f} coins exchanged, "
            f"{summary.get('total_crafts', 0)} items crafted"
        )

        return "\n\n".join(parts)

    def _fallback_narration(
        self, summary: dict[str, Any], weather: MarketWeather
    ) -> NarrationResult:
        """Generate a deterministic bullet-point summary."""
        lines: list[str] = []
        settlements = summary.get("settlements", [])
        crafts = summary.get("crafts", [])
        bankruptcies = summary.get("bankruptcies", [])
        joins = summary.get("joins", [])
        nature_events = summary.get("nature_events", [])

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
