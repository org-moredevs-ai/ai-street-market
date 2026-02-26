"""Narrator — LLM-powered narrative generation for the Town Crier.

Uses LangChain/OpenRouter with manual JSON parsing (works with ANY model).
LLM is always on — there is no toggle. Falls back to deterministic
summaries only on runtime errors (not by configuration).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from streetmarket.agent.llm_brain import extract_json
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
    "- Reference agents by name — use their full names:\n"
    "  farmer-01=Farmer Joe, chef-01=Chef Clara, baker-01=Baker Bella,\n"
    "  lumberjack-01=Jack Lumber, mason-01=Mason Pete, builder-01=Builder Bob\n"
    "- When agents join, give them a dramatic introduction!\n"
    "- Use market weather to set the tone\n"
    "- Make bold predictions (you're often wrong, and that's entertaining)\n"
    "- Keep it fun, dramatic, and opinionated\n"
    "- Use financial jargon mixed with medieval expressions\n"
    "- Never break character\n\n"
    "IMPORTANT: Keep your text SHORT. The body MUST be under 800 characters.\n\n"
    "You MUST respond with ONLY a JSON object (no other text) matching this schema:\n"
    '{"headline": "Punchy one-liner (max 80 chars)", '
    '"body": "2-3 short paragraphs (max 800 chars — BE CONCISE!)", '
    '"predictions": "One bold prediction or null", '
    '"drama_level": 1}'
    "\ndrama_level: 1=quiet, 3=interesting, 5=explosive"
)


class NarrationSchema(BaseModel):
    """Structured output schema for narration generation."""

    headline: str = Field(
        description="Punchy one-liner summarizing the market mood",
        max_length=100,
    )
    body: str = Field(description="2-4 paragraph dramatic narration of events", max_length=1000)
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


_AGENT_NAMES: dict[str, str] = {
    "farmer-01": "Farmer Joe",
    "chef-01": "Chef Clara",
    "baker-01": "Baker Bella",
    "lumberjack-01": "Jack Lumber",
    "mason-01": "Mason Pete",
    "builder-01": "Builder Bob",
}


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

        Tries LLM first (with retry), falls back to deterministic on error.
        """
        for attempt in range(2):
            try:
                use_system_msg = attempt == 0
                return await self._call_llm(summary, weather, use_system_msg=use_system_msg)
            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e)[:200]
                if attempt == 0:
                    logger.warning(
                        "Narrator LLM attempt 1 failed (%s: %s) — retrying without system message",
                        err_type, err_msg,
                    )
                else:
                    logger.error(
                        "Narrator LLM attempt 2 failed (%s: %s) — using fallback",
                        err_type, err_msg,
                    )
        return self._fallback_narration(summary, weather)

    async def _call_llm(
        self, summary: dict[str, Any], weather: MarketWeather,
        *, use_system_msg: bool = True,
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
        prompt = self._build_prompt(summary, weather)

        # Some models (e.g. gemma) don't support system messages — merge into user
        if use_system_msg:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        else:
            messages = [
                HumanMessage(content=f"{SYSTEM_PROMPT}\n\n---\n\n{prompt}"),
            ]

        response = await asyncio.wait_for(
            llm.ainvoke(messages),
            timeout=LLM_TIMEOUT,
        )

        raw = response.content
        raw_text = raw if isinstance(raw, str) else str(raw)

        # Strip <think>...</think> tags from reasoning models
        raw_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

        data = extract_json(raw_text)
        if data is None:
            raise ValueError(f"Could not extract JSON from LLM response: {raw_text[:200]}")
        result = NarrationSchema.model_validate(data)

        return NarrationResult(
            headline=result.headline[:100],
            body=result.body[:1000],
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

        spoilage = summary.get("spoilage_events", [])
        if spoilage:
            spoil_lines = [
                f"  {s['agent_id']} lost {s['quantity']}x {s['item']} to rot"
                for s in spoilage
            ]
            parts.append(f"SPOILAGE ({len(spoilage)} events):\n" + "\n".join(spoil_lines))

        rent_payments = summary.get("rent_payments", [])
        if rent_payments:
            struggling = [r for r in rent_payments if r["wallet_after"] < 5.0]
            if struggling:
                struggle_lines = [
                    f"  {r['agent_id']} paid {r['amount']:.1f} rent, wallet now {r['wallet_after']:.1f}"
                    for r in struggling
                ]
                parts.append("Agents struggling with rent:\n" + "\n".join(struggle_lines))

        energy = summary.get("energy_levels", {})
        if energy:
            energy_str = ", ".join(
                f"{a}: {e:.0f}" for a, e in sorted(energy.items())
            )
            parts.append(f"Energy levels: {energy_str}")

        joins = summary.get("joins", [])
        if joins:
            parts.append(f"New arrivals: {', '.join(joins)}")

        activity = summary.get("activity_counts", {})
        if activity:
            active_agents = [f"{a} ({c} actions)" for a, c in sorted(activity.items(), key=lambda x: -x[1])]
            parts.append(f"Active agents: {', '.join(active_agents)}")

        parts.append(
            f"All-time: {summary.get('total_settlements', 0)} trades, "
            f"{summary.get('total_coins_traded', 0):.0f} coins exchanged, "
            f"{summary.get('total_crafts', 0)} items crafted"
        )

        return "\n\n".join(parts)

    def _agent_name(self, agent_id: str) -> str:
        return _AGENT_NAMES.get(agent_id, agent_id)

    def _fallback_narration(
        self, summary: dict[str, Any], weather: MarketWeather
    ) -> NarrationResult:
        """Generate a deterministic narrative summary (no techy jargon)."""
        lines: list[str] = []
        settlements = summary.get("settlements", [])
        crafts = summary.get("crafts", [])
        bankruptcies = summary.get("bankruptcies", [])
        joins = summary.get("joins", [])
        nature_events = summary.get("nature_events", [])
        spoilage = summary.get("spoilage_events", [])
        rent_payments = summary.get("rent_payments", [])
        activity = summary.get("activity_counts", {})

        # Pick the most dramatic headline
        if bankruptcies:
            names = [self._agent_name(b) for b in bankruptcies]
            headline = f"Crisis! {', '.join(names)} declared bankrupt!"
        elif spoilage:
            total_spoiled = sum(s.get("quantity", 0) for s in spoilage)
            headline = f"Rot sets in! {total_spoiled} items spoiled in the market!"
        elif len(settlements) >= 3:
            headline = f"Busy day! {len(settlements)} trades completed!"
        elif joins:
            names = [self._agent_name(j) for j in joins]
            headline = f"Welcome {', '.join(names)} to the market!"
        elif nature_events:
            headline = nature_events[0]["title"]
        elif crafts:
            headline = f"The workshops are humming! {len(crafts)} items crafted!"
        elif activity:
            busiest = max(activity, key=activity.get)  # type: ignore[arg-type]
            headline = f"{self._agent_name(busiest)} is the busiest in town!"
        else:
            headline = "Hear ye! A quiet day at the market."

        if settlements:
            total = sum(s["total_price"] for s in settlements)
            trade_details = []
            for s in settlements:
                buyer = self._agent_name(s["buyer"])
                seller = self._agent_name(s["seller"])
                trade_details.append(
                    f"{buyer} bought {s['quantity']}x {s['item']} from {seller}"
                )
            if len(trade_details) <= 3:
                lines.append(". ".join(trade_details) + f" — {total:.0f} coins changed hands.")
            else:
                lines.append(f"{len(settlements)} trades totaling {total:.0f} coins!")

        if crafts:
            craft_summary: dict[str, list[str]] = {}
            for c in crafts:
                craft_summary.setdefault(c["output"], []).append(
                    self._agent_name(c.get("agent_id", "unknown"))
                )
            craft_parts = []
            for item, crafters in craft_summary.items():
                craft_parts.append(f"{', '.join(set(crafters))} crafted {item}")
            lines.append(". ".join(craft_parts) + ".")

        if spoilage:
            spoil_summary: dict[str, list[str]] = {}
            for s in spoilage:
                spoil_summary.setdefault(s["item"], []).append(
                    self._agent_name(s.get("agent_id", "unknown"))
                )
            spoil_parts = []
            for item, owners in spoil_summary.items():
                total_qty = sum(
                    s.get("quantity", 0) for s in spoilage if s["item"] == item
                )
                spoil_parts.append(f"{total_qty}x {item} rotted away ({', '.join(set(owners))})")
            lines.append("Spoilage! " + ". ".join(spoil_parts) + ".")

        if bankruptcies:
            names = [self._agent_name(b) for b in bankruptcies]
            lines.append(f"{', '.join(names)} have been evicted from the market!")

        struggling = [r for r in rent_payments if r["wallet_after"] < 5.0]
        if struggling:
            names = [self._agent_name(r["agent_id"]) for r in struggling]
            lines.append(f"{', '.join(names)} struggling to pay rent!")

        if nature_events:
            for e in nature_events:
                lines.append(f"{e['title']}: {e.get('description', '')}".strip())

        if joins:
            names = [self._agent_name(j) for j in joins]
            lines.append(f"New arrivals: {', '.join(names)} joined the market!")

        if not lines:
            lines.append("The market sits quiet. Perhaps tomorrow brings more action.")

        body = " ".join(lines)[:1000]

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
