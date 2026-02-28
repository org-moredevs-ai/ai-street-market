#!/usr/bin/env python3
"""Run a full AI Street Market season.

Wires all components together:
1. Loads season + world policy from YAML
2. Creates deterministic infrastructure (ledger, registry, world state)
3. Validates LLM environment variables
4. Connects to NATS and purges stale messages
5. Creates and starts all 6 market agents
6. Optionally starts WebSocket bridge for viewer
7. Runs tick clock through the full season lifecycle
8. Computes final rankings and prints results
9. Handles graceful shutdown on CTRL+C

Usage:
    python scripts/run_season.py
    python scripts/run_season.py --tick-override 2
    python scripts/run_season.py --season season-1.yaml --no-bridge
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from streetmarket.agent.llm_config import LLMConfig  # noqa: E402
from streetmarket.agent.market_agent import MarketAgent  # noqa: E402
from streetmarket.client.nats_client import STREAM_NAME, MarketBusClient  # noqa: E402
from streetmarket.ledger.memory import InMemoryLedger  # noqa: E402
from streetmarket.models.envelope import Envelope  # noqa: E402
from streetmarket.persistence.snapshots import StateSnapshot  # noqa: E402
from streetmarket.policy.engine import PolicyEngine, SeasonConfig, WorldPolicy  # noqa: E402
from streetmarket.ranking.engine import RankingEngine, RankingEntry  # noqa: E402
from streetmarket.registry.registry import AgentRegistry  # noqa: E402
from streetmarket.season.manager import SeasonManager, SeasonPhase  # noqa: E402
from streetmarket.world_state.store import WorldStateStore  # noqa: E402

from services.banker.banker import BankerAgent  # noqa: E402
from services.governor.governor import GovernorAgent  # noqa: E402
from services.landlord.landlord import LandlordAgent  # noqa: E402
from services.meteo.meteo import MeteoAgent  # noqa: E402
from services.nature.nature import NatureAgent  # noqa: E402
from services.tick_clock.clock import TickClock  # noqa: E402
from services.town_crier.narrator import TownCrierAgent  # noqa: E402
from services.websocket_bridge.bridge import WebSocketBridge  # noqa: E402

logger = logging.getLogger("run_season")

# ANSI colors for terminal output
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RED = "\033[31m"
_RESET = "\033[0m"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run a full AI Street Market season.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--season",
        default="season-1.yaml",
        help="Season YAML filename (in policy dir)",
    )
    parser.add_argument(
        "--policy-dir",
        default="policies/",
        help="Directory containing policy YAML files",
    )
    parser.add_argument(
        "--nats-url",
        default="nats://localhost:4222",
        help="NATS server URL",
    )
    parser.add_argument(
        "--ws-port",
        type=int,
        default=9090,
        help="WebSocket bridge port",
    )
    parser.add_argument(
        "--no-bridge",
        action="store_true",
        help="Skip starting the WebSocket bridge",
    )
    parser.add_argument(
        "--tick-override",
        type=int,
        default=None,
        help="Override tick interval in seconds (for faster testing)",
    )
    parser.add_argument(
        "--snapshot-dir",
        default="/data/snapshots",
        help="Directory for state snapshots (crash recovery)",
    )
    parser.add_argument(
        "--snapshot-interval",
        type=int,
        default=50,
        help="Save state snapshot every N ticks (0 to disable)",
    )
    return parser.parse_args(argv)


def validate_environment() -> None:
    """Validate required environment variables are set.

    Raises:
        SystemExit: If required variables are missing.
    """
    missing = []
    if not os.environ.get("OPENROUTER_API_KEY"):
        missing.append("OPENROUTER_API_KEY")
    if not os.environ.get("DEFAULT_MODEL"):
        missing.append("DEFAULT_MODEL")

    if missing:
        print(f"{_RED}Missing required environment variables:{_RESET}")
        for var in missing:
            print(f"  - {var}")
        print("\nSet them in your shell or .env file. See .env.example for reference.")
        sys.exit(1)


async def purge_nats_stream(nats_url: str) -> None:
    """Connect to NATS and purge stale messages from the STREETMARKET stream."""
    import nats as nats_lib

    nc = await nats_lib.connect(nats_url)
    js = nc.jetstream()

    try:
        await js.find_stream_name_by_subject("market.>")
        await js.purge_stream(STREAM_NAME)
        logger.info("Purged stale messages from stream '%s'", STREAM_NAME)
    except Exception:
        logger.info("No existing stream to purge — will be created on connect")
    finally:
        await nc.close()


def create_market_agents(
    *,
    season_config: SeasonConfig,
    world_policy: WorldPolicy,
    ledger: InMemoryLedger,
    registry: AgentRegistry,
    world_state: WorldStateStore,
    ranking_engine: RankingEngine,
    publish_fn: Any,
    subscribe_fn: Any,
) -> list[MarketAgent]:
    """Create all 6 market agents wired to infrastructure.

    Returns:
        List of MarketAgent instances (not yet started).
    """
    agents: list[MarketAgent] = []
    characters = season_config.characters

    # Governor
    gov_char = characters.get("governor")
    gov_config = LLMConfig.for_service("governor")
    agents.append(
        GovernorAgent(
            agent_id="governor",
            character_name=gov_char.character if gov_char else "Governor",
            personality=gov_char.personality if gov_char else "",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_config=gov_config,
            ledger=ledger,
            registry=registry,
            ranking_engine=ranking_engine,
            world_policy_text=world_policy.raw_text,
            season_description=season_config.description,
        )
    )

    # Banker
    bank_char = characters.get("banker")
    bank_config = LLMConfig.for_service("banker")
    agents.append(
        BankerAgent(
            agent_id="banker",
            character_name=bank_char.character if bank_char else "Banker",
            personality=bank_char.personality if bank_char else "",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_config=bank_config,
            ledger=ledger,
            registry=registry,
        )
    )

    # Nature
    nature_char = characters.get("nature")
    nature_config = LLMConfig.for_service("nature")
    agents.append(
        NatureAgent(
            agent_id="nature",
            character_name=nature_char.character if nature_char else "Nature",
            personality=nature_char.personality if nature_char else "",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_config=nature_config,
            world_state=world_state,
            world_policy_text=world_policy.raw_text,
        )
    )

    # Meteo
    meteo_char = characters.get("meteo")
    meteo_config = LLMConfig.for_service("meteo")
    agents.append(
        MeteoAgent(
            agent_id="meteo",
            character_name=meteo_char.character if meteo_char else "Meteo",
            personality=meteo_char.personality if meteo_char else "",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_config=meteo_config,
            world_state=world_state,
            world_policy_text=world_policy.raw_text,
        )
    )

    # Landlord
    landlord_char = characters.get("landlord")
    landlord_config = LLMConfig.for_service("landlord")
    agents.append(
        LandlordAgent(
            agent_id="landlord",
            character_name=landlord_char.character if landlord_char else "Landlord",
            personality=landlord_char.personality if landlord_char else "",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_config=landlord_config,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
        )
    )

    # Town Crier
    crier_char = characters.get("town_crier")
    crier_config = LLMConfig.for_service("town_crier")
    agents.append(
        TownCrierAgent(
            agent_id="town_crier",
            character_name=crier_char.character if crier_char else "Town Crier",
            personality=crier_char.personality if crier_char else "",
            publish_fn=publish_fn,
            subscribe_fn=subscribe_fn,
            llm_config=crier_config,
            season_description=season_config.description,
        )
    )

    return agents


def print_rankings(rankings: list[RankingEntry], season_name: str) -> None:
    """Pretty-print final season rankings."""
    print(f"\n{_BOLD}{_CYAN}{'=' * 60}{_RESET}")
    print(f"{_BOLD}{_CYAN}  SEASON RESULTS: {season_name}{_RESET}")
    print(f"{_BOLD}{_CYAN}{'=' * 60}{_RESET}\n")

    if not rankings:
        print(f"  {_YELLOW}No agents participated.{_RESET}\n")
        return

    # Winner
    winner = rankings[0]
    print(f"  {_BOLD}{_GREEN}WINNER: {winner.agent_id} (owner: {winner.owner}){_RESET}")
    print(f"  {_GREEN}Score: {winner.total_score:.1f}{_RESET}\n")

    # Full leaderboard
    print(f"  {_BOLD}{'Rank':<6} {'Agent':<25} {'Owner':<20} {'Score':>8}{_RESET}")
    print(f"  {'-' * 63}")

    for entry in rankings:
        marker = " *" if entry.rank == 1 else ""
        state_label = f" ({entry.death_reason})" if entry.death_reason else ""
        print(
            f"  {entry.rank:<6} {entry.agent_id:<25} {entry.owner:<20} "
            f"{entry.total_score:>8.1f}{state_label}{marker}"
        )

    print(f"\n  {_BOLD}Score Breakdown (top agent):{_RESET}")
    for metric, value in winner.scores.items():
        print(f"    {metric}: {value:.1f}")

    print()


async def main(argv: list[str] | None = None) -> None:
    """Main entry point — orchestrate a full season."""
    args = parse_args(argv)

    # Set up logging
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_format)
    logging.getLogger("nats").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

    print(f"\n{_BOLD}{_CYAN}AI Street Market — Season Runner{_RESET}")
    print(f"{_CYAN}{'=' * 40}{_RESET}\n")

    # 1. Validate environment
    validate_environment()

    # 2. Load policies
    policy_dir = Path(args.policy_dir)
    if not policy_dir.is_absolute():
        policy_dir = PROJECT_ROOT / policy_dir

    engine = PolicyEngine(policy_dir)
    season_config = engine.load_season(args.season)
    world_policy = engine.load_world(season_config.world_policy_file)

    print(f"  Season: {_BOLD}{season_config.name}{_RESET} (#{season_config.number})")
    print(f"  World:  {world_policy.name} ({world_policy.era}, {world_policy.climate})")
    print(f"  Ticks:  {season_config.total_ticks} ({season_config.tick_interval_seconds}s each)")

    # Apply tick override
    effective_interval = season_config.tick_interval_seconds
    if args.tick_override is not None:
        effective_interval = args.tick_override
        orig = season_config.tick_interval_seconds
        print(f"  {_YELLOW}Tick override: {effective_interval}s (was {orig}s){_RESET}")
        # Create a new SeasonConfig with the overridden tick interval
        season_config = SeasonConfig(
            name=season_config.name,
            number=season_config.number,
            description=season_config.description,
            starts_at=season_config.starts_at,
            ends_at=season_config.ends_at,
            tick_interval_seconds=effective_interval,
            world_policy_file=season_config.world_policy_file,
            biases=season_config.biases,
            agent_defaults=season_config.agent_defaults,
            winning_criteria=season_config.winning_criteria,
            awards=season_config.awards,
            closing_percent=season_config.closing_percent,
            preparation_hours=season_config.preparation_hours,
            next_season_hint=season_config.next_season_hint,
            characters=season_config.characters,
        )

    print()

    # 3. Create infrastructure
    ledger = InMemoryLedger()
    registry = AgentRegistry()
    world_state = WorldStateStore()
    season_manager = SeasonManager(season_config)
    ranking_engine = RankingEngine(season_config, ledger, registry)

    # 3b. Restore from snapshot if available
    restored_tick = 0
    snapshot_file = StateSnapshot.find_latest(args.snapshot_dir)
    if snapshot_file:
        logger.info("Found snapshot: %s — restoring state...", snapshot_file)
        state_data = StateSnapshot.restore(snapshot_file)
        restored_tick = StateSnapshot.apply(
            state_data,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            season_manager=season_manager,
            ranking_engine=ranking_engine,
        )
        # If the restored snapshot is from an ENDED season, discard it and start fresh
        if season_manager.phase == SeasonPhase.ENDED:
            logger.info(
                "Snapshot is from ended season (tick %d) — starting fresh",
                restored_tick,
            )
            restored_tick = 0
            ledger = InMemoryLedger()
            registry = AgentRegistry()
            world_state = WorldStateStore()
            season_manager = SeasonManager(season_config)
            ranking_engine = RankingEngine(season_config, ledger, registry)
        else:
            print(f"  {_GREEN}Restored from snapshot at tick {restored_tick}{_RESET}\n")
    else:
        logger.info("No snapshot found in %s — starting fresh", args.snapshot_dir)

    # 4. Purge stale NATS messages and connect
    logger.info("Connecting to NATS at %s...", args.nats_url)
    if not restored_tick:
        await purge_nats_stream(args.nats_url)
    else:
        logger.info("Skipping NATS purge (restoring from snapshot)")

    nats_client = MarketBusClient(args.nats_url)
    await nats_client.connect()
    logger.info("NATS connected")

    # Shutdown event
    shutdown_event = asyncio.Event()
    agents: list[MarketAgent] = []
    bridge: WebSocketBridge | None = None
    clock: TickClock | None = None

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()
        if clock:
            clock.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        # 5. Create and start market agents
        logger.info("Creating market agents...")
        agents = create_market_agents(
            season_config=season_config,
            world_policy=world_policy,
            ledger=ledger,
            registry=registry,
            world_state=world_state,
            ranking_engine=ranking_engine,
            publish_fn=nats_client.publish,
            subscribe_fn=nats_client.subscribe,
        )

        for agent in agents:
            await agent.start()
            logger.info("  Started: %s (%s)", agent.character_name, agent.agent_id)

        print(f"  {_GREEN}All 6 market agents started{_RESET}\n")

        # 6. Start WebSocket bridge (optional)
        if not args.no_bridge:
            bridge = WebSocketBridge(
                nats_url=args.nats_url,
                ws_port=args.ws_port,
                registry=registry,
                world_state=world_state,
                season_manager=season_manager,
                ranking_engine=ranking_engine,
            )
            await bridge.start()
            logger.info("WebSocket bridge started on port %d", args.ws_port)
        else:
            logger.info("WebSocket bridge skipped (--no-bridge)")

        # 7. Run season lifecycle
        if not restored_tick:
            # Fresh start: advance through phases
            season_manager.advance_to(SeasonPhase.PREPARATION)
            logger.info("Phase: PREPARATION")
            season_manager.advance_to(SeasonPhase.OPEN)
            logger.info("Phase: OPEN — trading begins!")
        else:
            logger.info(
                "Resuming from tick %d — phase: %s",
                restored_tick,
                season_manager.phase.value.upper(),
            )

        # Create and start tick clock
        async def publish_fn(topic: str, envelope: Envelope) -> None:
            await nats_client.publish(topic, envelope)

        clock = TickClock(season_manager, publish_fn)

        # Run clock with periodic progress logging + snapshots
        last_log_tick = 0
        last_snapshot_tick = restored_tick

        async def _monitor_progress() -> None:
            nonlocal last_log_tick, last_snapshot_tick
            while not shutdown_event.is_set() and season_manager.is_running:
                await asyncio.sleep(5)
                current = season_manager.current_tick
                if current - last_log_tick >= 10:
                    last_log_tick = current
                    phase = season_manager.phase.value.upper()
                    progress = season_manager.progress_percent
                    logger.info(
                        "Tick %d / %d (%.1f%%) — Phase: %s",
                        current,
                        season_manager.total_ticks,
                        progress,
                        phase,
                    )

                # Periodic snapshot saving
                if (
                    args.snapshot_interval > 0
                    and current - last_snapshot_tick >= args.snapshot_interval
                ):
                    try:
                        StateSnapshot.save(
                            args.snapshot_dir,
                            tick=current,
                            ledger=ledger,
                            registry=registry,
                            world_state=world_state,
                            season_manager=season_manager,
                            ranking_engine=ranking_engine,
                        )
                        last_snapshot_tick = current
                    except Exception:
                        logger.exception("Failed to save snapshot at tick %d", current)

        monitor_task = asyncio.create_task(_monitor_progress())

        # Run clock until season ends or shutdown
        clock_task = asyncio.create_task(clock.start())

        # Wait for either clock to finish or shutdown signal
        done, pending = await asyncio.wait(
            [clock_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # 8. Finalize — compute rankings
        if season_manager.phase != SeasonPhase.ENDED:
            season_manager.advance_to(SeasonPhase.ENDED)

        logger.info("Phase: ENDED — computing final rankings...")

        final_rankings = await ranking_engine.calculate_rankings(season_manager.current_tick)
        print_rankings(final_rankings, season_config.name)

        logger.info(
            "Season '%s' completed after %d ticks",
            season_config.name,
            season_manager.current_tick,
        )

    finally:
        # 9. Save final snapshot before shutdown
        if args.snapshot_interval > 0:
            try:
                StateSnapshot.save(
                    args.snapshot_dir,
                    tick=season_manager.current_tick,
                    ledger=ledger,
                    registry=registry,
                    world_state=world_state,
                    season_manager=season_manager,
                    ranking_engine=ranking_engine,
                )
                logger.info("Final snapshot saved at tick %d", season_manager.current_tick)
            except Exception:
                logger.exception("Failed to save final snapshot")

        # 10. Graceful cleanup
        logger.info("Shutting down...")

        if clock and clock.is_running:
            clock.stop()

        if bridge:
            await bridge.stop()
            logger.info("WebSocket bridge stopped")

        await nats_client.close()
        logger.info("NATS disconnected")

        print(f"\n  {_BOLD}Goodbye from the AI Street Market!{_RESET}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
