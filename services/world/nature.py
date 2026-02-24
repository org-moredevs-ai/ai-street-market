"""NatureBrain — LLM-powered nature intelligence for dynamic spawn tables.

Calls Claude Haiku every N ticks to generate contextual spawn amounts and
optional nature events. Falls back to DEFAULT_SPAWN_TABLE on any failure.
"""

import logging
import os
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How often (in ticks) to query the LLM
LLM_CALL_INTERVAL = 5

# Tool definition for structured output
SPAWN_TOOL = {
    "name": "set_nature",
    "description": (
        "Set the spawn quantities for this tick cycle and optionally trigger a nature event. "
        "Spawn quantities are the number of each raw material available per tick."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "spawns": {
                "type": "object",
                "description": "Raw material spawn quantities per tick",
                "properties": {
                    "potato": {"type": "integer", "minimum": 0, "maximum": 50},
                    "onion": {"type": "integer", "minimum": 0, "maximum": 50},
                    "wood": {"type": "integer", "minimum": 0, "maximum": 50},
                    "nails": {"type": "integer", "minimum": 0, "maximum": 50},
                    "stone": {"type": "integer", "minimum": 0, "maximum": 50},
                },
                "required": ["potato", "onion", "wood", "nails", "stone"],
            },
            "event": {
                "type": "object",
                "description": "Optional nature event (drought, flood, bonanza, etc.)",
                "properties": {
                    "title": {"type": "string", "maxLength": 50},
                    "description": {"type": "string", "maxLength": 200},
                    "duration_ticks": {"type": "integer", "minimum": 1, "maximum": 15},
                },
                "required": ["title", "description", "duration_ticks"],
            },
        },
        "required": ["spawns"],
    },
}


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

    When enabled, calls Claude Haiku every LLM_CALL_INTERVAL ticks to
    generate contextual spawn tables. Results are cached between calls.
    Falls back to default on any error.
    """

    enabled: bool = False
    _cached_spawns: dict[str, int] | None = None
    _active_event: NatureEvent | None = None
    _last_call_tick: int = 0
    _gather_history: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.enabled = os.environ.get("WORLD_USE_LLM_NATURE", "false").lower() == "true"
        if self.enabled:
            try:
                import anthropic  # noqa: F401

                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if not api_key:
                    logger.warning("WORLD_USE_LLM_NATURE=true but no ANTHROPIC_API_KEY — disabling")
                    self.enabled = False
                else:
                    logger.info(
                        "NatureBrain enabled — will call LLM every %d ticks",
                        LLM_CALL_INTERVAL,
                    )
            except ImportError:
                logger.warning("anthropic package not installed — disabling NatureBrain")
                self.enabled = False

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
        # Keep only last 50
        if len(self._gather_history) > 50:
            self._gather_history = self._gather_history[-50:]

    def get_recent_gathers(self) -> list[dict]:
        """Get the recent gather history."""
        return list(self._gather_history)

    def should_call_llm(self, current_tick: int) -> bool:
        """Check if it's time to query the LLM."""
        if not self.enabled:
            return False
        return (current_tick - self._last_call_tick) >= LLM_CALL_INTERVAL

    def get_spawn_table(
        self, current_tick: int, default_table: dict[str, int]
    ) -> dict[str, int]:
        """Get the spawn table — from LLM cache or default.

        Does NOT call the LLM. Use call_llm() separately for async calls.
        """
        if self._cached_spawns is not None:
            spawns = dict(self._cached_spawns)
            # Apply event effects if active
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
        if not self.enabled:
            return dict(default_table)

        self._last_call_tick = current_tick

        try:
            import anthropic

            client = anthropic.AsyncAnthropic()

            # Build context for the LLM
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
                f"bonanza, blight, etc.) to add drama. Events should last 3-10 ticks."
            )

            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                tools=[SPAWN_TOOL],  # type: ignore[list-item]
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract tool_use from response
            for block in response.content:
                if block.type == "tool_use" and block.name == "set_nature":
                    return self._process_llm_response(block.input, current_tick)

            logger.warning("LLM response had no tool_use — using default spawns")
            return dict(default_table)

        except Exception as e:
            logger.warning("NatureBrain LLM call failed: %s — using defaults", e)
            return dict(default_table)

    def _process_llm_response(
        self, tool_input: dict, current_tick: int
    ) -> dict[str, int]:
        """Process the LLM's tool_use response into a spawn table."""
        spawns_raw = tool_input.get("spawns", {})
        spawns: dict[str, int] = {}
        for item in ("potato", "onion", "wood", "nails", "stone"):
            val = spawns_raw.get(item, 0)
            spawns[item] = max(0, min(50, int(val)))

        self._cached_spawns = spawns

        # Handle optional event
        event_data = tool_input.get("event")
        if event_data and not self._active_event:
            effects: dict[str, float] = {}
            # Compute effects as ratios of new spawns vs defaults
            from services.world.state import DEFAULT_SPAWN_TABLE

            for item, default_qty in DEFAULT_SPAWN_TABLE.items():
                if default_qty > 0 and item in spawns:
                    ratio = spawns[item] / default_qty
                    if abs(ratio - 1.0) > 0.05:  # Only record significant changes
                        effects[item] = round(ratio, 2)

            self._active_event = NatureEvent(
                event_id=str(uuid.uuid4()),
                title=event_data.get("title", "Unknown Event"),
                description=event_data.get("description", ""),
                effects=effects,
                duration_ticks=max(1, min(15, event_data.get("duration_ticks", 5))),
                remaining_ticks=max(1, min(15, event_data.get("duration_ticks", 5))),
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

        # Count items gathered per item type
        totals: dict[str, int] = {}
        for g in self._gather_history:
            item = g["item"]
            totals[item] = totals.get(item, 0) + g["quantity"]

        parts = [f"{item}: {qty} gathered" for item, qty in sorted(totals.items())]
        return ", ".join(parts)
