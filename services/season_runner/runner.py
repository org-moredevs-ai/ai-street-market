"""Season runner — orchestrates the full season lifecycle.

The season runner is the top-level service that ties everything together:
- Loads season config and world policy
- Initializes infrastructure (ledger, registry, world state)
- Creates and starts market agents (Governor, Banker, Nature, etc.)
- Runs the tick clock through the season
- Computes final rankings and declares winners
- Handles phase transitions (ANNOUNCED → PREPARATION → OPEN → CLOSING → ENDED)

Usage:
    runner = SeasonRunner(
        season_config_file="season-1.yaml",
        policy_dir="policies/",
        nats_url="nats://localhost:4222",
    )
    await runner.run()
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from streetmarket.client.nats_client import MarketBusClient
from streetmarket.ledger.memory import InMemoryLedger
from streetmarket.models.envelope import Envelope
from streetmarket.policy.engine import SeasonConfig
from streetmarket.ranking.engine import RankingEngine, RankingEntry
from streetmarket.registry.registry import AgentRegistry
from streetmarket.season.manager import SeasonManager, SeasonPhase
from streetmarket.world_state.store import WorldStateStore

from services.tick_clock.clock import TickClock

logger = logging.getLogger(__name__)

# Type for callbacks
EventCallback = Callable[[str, Any], Coroutine[Any, Any, None]]


@dataclass
class SeasonResult:
    """Result of a completed season."""

    season_number: int
    season_name: str
    total_ticks: int
    final_rankings: list[RankingEntry]
    winner_agent_id: str = ""
    winner_owner: str = ""


@dataclass
class SeasonRunnerConfig:
    """Configuration for the season runner."""

    season_config: SeasonConfig
    nats_url: str = "nats://localhost:4222"
    ws_enabled: bool = False
    ws_port: int = 9090
    on_phase_change: EventCallback | None = None
    on_season_end: EventCallback | None = None


class SeasonRunner:
    """Orchestrates the full season lifecycle.

    Lifecycle:
        1. ANNOUNCED — config loaded, infrastructure initialized
        2. PREPARATION — market agents started, waiting for season open
        3. OPEN — tick clock running, agents can join and trade
        4. CLOSING — ~20% before end, next season announced
        5. ENDED — final rankings computed, winner declared
    """

    def __init__(self, config: SeasonRunnerConfig) -> None:
        self._config = config
        self._season_config = config.season_config

        # Infrastructure components
        self._nats: MarketBusClient | None = None
        self._ledger = InMemoryLedger()
        self._registry = AgentRegistry()
        self._world_state = WorldStateStore()
        self._season = SeasonManager(self._season_config)
        self._ranking = RankingEngine(
            self._season_config,
            self._ledger,
            self._registry,
        )
        self._clock: TickClock | None = None

        # State
        self._running = False
        self._result: SeasonResult | None = None
        self._phase_callbacks: list[EventCallback] = []
        if config.on_phase_change:
            self._phase_callbacks.append(config.on_phase_change)

    @property
    def season(self) -> SeasonManager:
        return self._season

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    @property
    def ledger(self) -> InMemoryLedger:
        return self._ledger

    @property
    def world_state(self) -> WorldStateStore:
        return self._world_state

    @property
    def ranking(self) -> RankingEngine:
        return self._ranking

    @property
    def result(self) -> SeasonResult | None:
        return self._result

    @property
    def is_running(self) -> bool:
        return self._running

    # -- Full lifecycle --

    async def run(self) -> SeasonResult:
        """Run the full season lifecycle. Returns the season result."""
        try:
            self._running = True

            # Phase 1: Announced (already in this state from constructor)
            await self._on_phase_change(SeasonPhase.ANNOUNCED)

            # Phase 2: Preparation — connect NATS, set up market agents
            await self.prepare()

            # Phase 3: Open — start tick clock, accept agents
            await self.open()

            # Phase 4–5: Run tick clock until season ends (CLOSING auto-transitions)
            await self._run_season()

            # Phase 6: Finalize — compute rankings, declare winner
            result = await self.finalize()
            return result

        finally:
            self._running = False
            await self._cleanup()

    # -- Individual phase methods --

    async def prepare(self) -> None:
        """ANNOUNCED → PREPARATION: Connect to NATS, initialize agents."""
        self._nats = MarketBusClient(self._config.nats_url)
        await self._nats.connect()

        self._season.advance_to(SeasonPhase.PREPARATION)
        await self._on_phase_change(SeasonPhase.PREPARATION)

        logger.info(
            "Season '%s' preparing (NATS connected)",
            self._season_config.name,
        )

    async def open(self) -> None:
        """PREPARATION → OPEN: Start tick clock."""
        self._season.advance_to(SeasonPhase.OPEN)

        # Create tick clock
        async def publish_fn(topic: str, envelope: Envelope) -> None:
            if self._nats:
                await self._nats.publish(topic, envelope)

        self._clock = TickClock(self._season, publish_fn)

        await self._on_phase_change(SeasonPhase.OPEN)

        logger.info(
            "Season '%s' is OPEN (tick interval: %ds, total ticks: %d)",
            self._season_config.name,
            self._season_config.tick_interval_seconds,
            self._season.total_ticks,
        )

    async def _run_season(self) -> None:
        """Run the tick clock until the season ends."""
        if not self._clock:
            raise RuntimeError("Cannot run season — clock not initialized (call open() first)")

        previous_phase = self._season.phase

        # Run the clock — it will stop when the season ends
        await self._clock.start()

        # Check for phase transitions that happened during the run
        if self._season.phase != previous_phase:
            if self._season.phase == SeasonPhase.CLOSING:
                await self._on_phase_change(SeasonPhase.CLOSING)
            if self._season.phase == SeasonPhase.ENDED:
                await self._on_phase_change(SeasonPhase.ENDED)

    async def finalize(self) -> SeasonResult:
        """ENDED: Compute final rankings and declare winner."""
        if self._season.phase != SeasonPhase.ENDED:
            self._season.advance_to(SeasonPhase.ENDED)
            await self._on_phase_change(SeasonPhase.ENDED)

        # Compute final rankings
        final_rankings = await self._ranking.calculate_rankings(self._season.current_tick)

        # Determine winner
        winner_id = ""
        winner_owner = ""
        if final_rankings:
            winner_id = final_rankings[0].agent_id
            winner_owner = final_rankings[0].owner

        self._result = SeasonResult(
            season_number=self._season_config.number,
            season_name=self._season_config.name,
            total_ticks=self._season.current_tick,
            final_rankings=final_rankings,
            winner_agent_id=winner_id,
            winner_owner=winner_owner,
        )

        logger.info(
            "Season '%s' ended after %d ticks. Winner: %s (owner: %s)",
            self._season_config.name,
            self._season.current_tick,
            winner_id or "nobody",
            winner_owner or "n/a",
        )

        return self._result

    # -- Callbacks --

    async def _on_phase_change(self, phase: SeasonPhase) -> None:
        """Notify phase change callbacks."""
        for cb in self._phase_callbacks:
            try:
                await cb(phase.value, self._season.snapshot())
            except Exception:
                logger.exception("Phase change callback failed for %s", phase.value)

    # -- Cleanup --

    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self._clock and self._clock.is_running:
            self._clock.stop()
        if self._nats:
            await self._nats.close()
            self._nats = None

    # -- Convenience methods --

    async def register_agent(
        self,
        agent_id: str,
        owner: str,
        display_name: str,
    ) -> None:
        """Register an agent (convenience method for testing)."""
        await self._registry.register(
            agent_id=agent_id,
            owner=owner,
            display_name=display_name,
            tick=self._season.current_tick,
        )
        await self._ledger.create_wallet(agent_id, initial_balance=Decimal("100"))

    def stop(self) -> None:
        """Stop the season runner."""
        self._running = False
        if self._clock:
            self._clock.stop()
