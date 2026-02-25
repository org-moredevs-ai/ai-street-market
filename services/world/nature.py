"""NatureBrain — LLM-powered nature intelligence for dynamic spawn tables.

Uses LangChain/OpenRouter to generate contextual spawn amounts and
optional nature events. LLM is always on — there is no toggle.
Falls back to DEFAULT_SPAWN_TABLE only on runtime errors.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from streetmarket.agent.llm_brain import extract_json
from streetmarket.agent.llm_config import LLMConfig

logger = logging.getLogger(__name__)

# How often (in ticks) to query the LLM
LLM_CALL_INTERVAL = 5
LLM_TIMEOUT = 15.0


class NatureEventSchema(BaseModel):
    """Optional nature event schema for structured output."""

    title: str = Field(max_length=50)
    description: str = Field(max_length=200)
    duration_ticks: int = Field(ge=1, le=15)


class NatureOutputSchema(BaseModel):
    """Structured output schema for nature intelligence."""

    spawns: dict[str, int] = Field(
        description=(
            "Raw material spawn quantities per tick"
            " (potato, onion, wood, nails, stone). Range 0-50."
        )
    )
    event: NatureEventSchema | None = Field(
        default=None,
        description="Optional nature event (drought, flood, bonanza, etc.)",
    )


@dataclass
class NatureEvent:
    """An active nature event affecting spawns."""

    event_id: str
    title: str
    description: str
    effects: dict[str, float]  # item -> multiplier
    duration_ticks: int
    remaining_ticks: int


@dataclass
class NatureBrain:
    """LLM-powered nature intelligence.

    Always uses LLM via OpenRouter every LLM_CALL_INTERVAL ticks.
    Results are cached between calls. Falls back to default on error.
    """

    _cached_spawns: dict[str, int] | None = None
    _active_event: NatureEvent | None = None
    _last_call_tick: int = 0
    _gather_history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def active_event(self) -> NatureEvent | None:
        return self._active_event

    def record_gather(self, agent_id: str, item: str, quantity: int, tick: int) -> None:
        """Record a gather event for context."""
        self._gather_history.append({
            "agent": agent_id,
            "item": item,
            "quantity": quantity,
            "tick": tick,
        })
        if len(self._gather_history) > 50:
            self._gather_history = self._gather_history[-50:]

    def get_recent_gathers(self) -> list[dict[str, Any]]:
        """Get the recent gather history."""
        return list(self._gather_history)

    def should_call_llm(self, current_tick: int) -> bool:
        """Check if it's time to query the LLM."""
        return (current_tick - self._last_call_tick) >= LLM_CALL_INTERVAL

    def get_spawn_table(
        self, current_tick: int, default_table: dict[str, int]
    ) -> dict[str, int]:
        """Get the spawn table — from LLM cache or default.

        Does NOT call the LLM. Use call_llm() separately for async calls.
        """
        if self._cached_spawns is not None:
            spawns = dict(self._cached_spawns)
            if self._active_event and self._active_event.remaining_ticks > 0:
                for item, multiplier in self._active_event.effects.items():
                    if item in spawns:
                        spawns[item] = max(0, int(spawns[item] * multiplier))
            return spawns
        return dict(default_table)

    def tick_event(self) -> NatureEvent | None:
        """Advance the active event by one tick. Returns it if still active."""
        if self._active_event is None:
            return None
        self._active_event.remaining_ticks -= 1
        if self._active_event.remaining_ticks <= 0:
            logger.info("Nature event '%s' has ended", self._active_event.title)
            self._active_event = None
            return None
        return self._active_event

    async def call_llm(
        self,
        current_tick: int,
        default_table: dict[str, int],
        energy_levels: dict[str, float],
    ) -> dict[str, int]:
        """Call the LLM for a new spawn table. Returns the spawn table to use.

        Falls back to default_table on any error.
        """
        self._last_call_tick = current_tick

        try:
            config = LLMConfig.for_service("world")
            llm = ChatOpenAI(
                model=config.model,
                api_key=config.api_key,  # type: ignore[arg-type]
                base_url=config.api_base,
                max_tokens=config.max_tokens,  # type: ignore[call-arg]
                temperature=config.temperature,
            )

            gather_summary = self._summarize_gathers()
            energy_summary = ", ".join(
                f"{a}: {e:.0f}" for a, e in sorted(energy_levels.items())
            ) if energy_levels else "No agents yet"

            event_context = ""
            if self._active_event:
                event_context = (
                    f"\nCurrent event: {self._active_event.title} "
                    f"({self._active_event.remaining_ticks} ticks remaining)"
                )

            prompt = (
                f"You are the Nature Intelligence for an AI economy simulation. "
                f"Current tick: {current_tick}.\n\n"
                f"Recent gather activity:\n{gather_summary}\n\n"
                f"Agent energy levels: {energy_summary}\n"
                f"Default spawn amounts: {default_table}\n"
                f"{event_context}\n\n"
                f"Based on the economy state, set spawn quantities for the next "
                f"{LLM_CALL_INTERVAL} ticks. You may adjust quantities up or down "
                f"(0-50 range). Optionally create a nature event (drought, flood, "
                f"bonanza, blight, etc.) to add drama. Events should last 3-10 ticks.\n\n"
                f"You MUST respond with ONLY a JSON object (no other text) matching this schema:\n"
                f'{{"spawns": {{"potato": 20, "onion": 15, "wood": 15, "nails": 10, "stone": 10}}, '
                f'"event": null}}\n'
                f'For an event: {{"spawns": {{...}}, "event": {{"title": "Drought", '
                f'"description": "Water dries up", "duration_ticks": 5}}}}'
            )

            response = await asyncio.wait_for(
                llm.ainvoke([
                    HumanMessage(content=prompt),
                ]),
                timeout=LLM_TIMEOUT,
            )

            raw = response.content
            raw_text = raw if isinstance(raw, str) else str(raw)
            data = extract_json(raw_text)
            result = NatureOutputSchema.model_validate(data)

            return self._process_llm_response(result, current_tick)

        except Exception as e:
            logger.warning("NatureBrain LLM call failed: %s — using defaults", e)
            return dict(default_table)

    def _process_llm_response(
        self, result: NatureOutputSchema, current_tick: int
    ) -> dict[str, int]:
        """Process the LLM's structured response into a spawn table."""
        spawns: dict[str, int] = {}
        for item in ("potato", "onion", "wood", "nails", "stone"):
            val = result.spawns.get(item, 0)
            spawns[item] = max(0, min(50, int(val)))

        self._cached_spawns = spawns

        # Handle optional event
        if result.event and not self._active_event:
            effects: dict[str, float] = {}
            from services.world.state import DEFAULT_SPAWN_TABLE

            for item, default_qty in DEFAULT_SPAWN_TABLE.items():
                if default_qty > 0 and item in spawns:
                    ratio = spawns[item] / default_qty
                    if abs(ratio - 1.0) > 0.05:
                        effects[item] = round(ratio, 2)

            self._active_event = NatureEvent(
                event_id=str(uuid.uuid4()),
                title=result.event.title[:50],
                description=result.event.description[:200],
                effects=effects,
                duration_ticks=max(1, min(15, result.event.duration_ticks)),
                remaining_ticks=max(1, min(15, result.event.duration_ticks)),
            )
            logger.info(
                "Nature event: '%s' — %s (duration: %d ticks)",
                self._active_event.title,
                self._active_event.description,
                self._active_event.duration_ticks,
            )

        return spawns

    def _summarize_gathers(self) -> str:
        """Summarize recent gathers for the LLM prompt."""
        if not self._gather_history:
            return "No gather activity yet."

        totals: dict[str, int] = {}
        for g in self._gather_history:
            item = g["item"]
            totals[item] = totals.get(item, 0) + g["quantity"]

        parts = [f"{item}: {qty} gathered" for item, qty in sorted(totals.items())]
        return ", ".join(parts)
