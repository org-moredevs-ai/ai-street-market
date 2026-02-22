"""WorldEngine — tick clock, nature spawns, gather protocol, and energy system."""

import asyncio
import logging
import os
import time

from streetmarket import (
    EnergyUpdate,
    Envelope,
    GatherResult,
    MarketBusClient,
    MessageType,
    Spawn,
    Tick,
    Topics,
    create_message,
)

from services.world.rules import (
    apply_regen,
    check_gather_energy,
    deduct_gather_energy,
    get_energy_cost,
    process_consume_result,
    process_gather,
    process_tick,
)
from services.world.state import DEFAULT_TICK_INTERVAL, WorldState

logger = logging.getLogger(__name__)


class WorldEngine:
    """The World Engine is the simulation's heartbeat.

    It publishes Tick messages at a configurable interval,
    spawns raw materials each tick, handles FCFS gathering,
    and manages the energy system (regen, deductions, consume results).
    """

    AGENT_ID = "world"

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._bus = MarketBusClient(nats_url)
        self._state = WorldState()
        self._tick_interval = float(
            os.environ.get("WORLD_TICK_INTERVAL", DEFAULT_TICK_INTERVAL)
        )
        self._running = False
        self._tick_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> WorldState:
        """Expose state for testing."""
        return self._state

    async def start(self) -> None:
        """Connect to NATS, subscribe to gather requests, start tick loop."""
        await self._bus.connect()
        logger.info("World Engine connected to NATS")

        await self._bus.subscribe(Topics.NATURE, self._on_nature_message)
        logger.info("World Engine subscribed to %s", Topics.NATURE)

        # Subscribe to governance for energy deduction on validated market actions
        await self._bus.subscribe(Topics.GOVERNANCE, self._on_governance_message)
        logger.info("World Engine subscribed to %s", Topics.GOVERNANCE)

        # Subscribe to bank for CONSUME_RESULT (energy restoration)
        await self._bus.subscribe(Topics.BANK, self._on_bank_message)
        logger.info("World Engine subscribed to %s", Topics.BANK)

        # Subscribe to market/square for JOIN (register energy)
        await self._bus.subscribe(Topics.SQUARE, self._on_square_message)
        logger.info("World Engine subscribed to %s", Topics.SQUARE)

        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info(
            "World Engine started (tick interval: %.1fs)", self._tick_interval
        )

    async def stop(self) -> None:
        """Clean shutdown."""
        self._running = False
        if self._tick_task is not None:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        await self._bus.close()
        logger.info("World Engine stopped")

    async def _tick_loop(self) -> None:
        """Periodically advance tick, publish Tick and Spawn messages."""
        while self._running:
            await self._do_tick()
            await asyncio.sleep(self._tick_interval)

    async def _do_tick(self) -> None:
        """Execute one tick: advance state, regen energy, publish Tick + Spawn + EnergyUpdate."""
        tick_number, spawn_id, items = process_tick(self._state)

        # Apply energy regen before publishing
        apply_regen(self._state)

        # Publish Tick to /system/tick
        tick_msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.TICK,
            msg_type=MessageType.TICK,
            payload=Tick(tick_number=tick_number, timestamp=time.time()),
            tick=tick_number,
        )
        await self._bus.publish(Topics.TICK, tick_msg)

        # Publish Spawn to /world/nature
        spawn_msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.NATURE,
            msg_type=MessageType.SPAWN,
            payload=Spawn(spawn_id=spawn_id, tick=tick_number, items=items),
            tick=tick_number,
        )
        await self._bus.publish(Topics.NATURE, spawn_msg)

        # Publish EnergyUpdate to /system/tick
        energy_levels = self._state.get_all_energy()
        if energy_levels:
            energy_msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.TICK,
                msg_type=MessageType.ENERGY_UPDATE,
                payload=EnergyUpdate(tick=tick_number, energy_levels=energy_levels),
                tick=tick_number,
            )
            await self._bus.publish(Topics.TICK, energy_msg)

        logger.info(
            "[tick %d] Published tick + spawn + energy (spawn_id=%s)",
            tick_number,
            spawn_id[:8],
        )

    async def _on_nature_message(self, envelope: Envelope) -> None:
        """Handle incoming messages on /world/nature."""
        # Skip our own messages (SPAWN, GATHER_RESULT)
        if envelope.from_agent == self.AGENT_ID:
            return

        if envelope.type != MessageType.GATHER:
            return

        agent_id = envelope.from_agent

        # Energy check for gather
        energy_error = check_gather_energy(agent_id, self._state)
        if energy_error is not None:
            result_msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.NATURE,
                msg_type=MessageType.GATHER_RESULT,
                payload=GatherResult(
                    reference_msg_id=envelope.id,
                    spawn_id=envelope.payload.get("spawn_id", ""),
                    agent_id=agent_id,
                    item=envelope.payload.get("item", ""),
                    quantity=0,
                    success=False,
                    reason=energy_error,
                ),
                tick=self._state.current_tick,
            )
            await self._bus.publish(Topics.NATURE, result_msg)
            logger.warning(
                "[tick %d] GATHER from %s rejected: %s",
                self._state.current_tick,
                agent_id,
                energy_error,
            )
            return

        granted, success, reason = process_gather(envelope, self._state)

        # Deduct energy only if gather succeeded
        if success:
            deduct_gather_energy(agent_id, self._state)

        result_msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER_RESULT,
            payload=GatherResult(
                reference_msg_id=envelope.id,
                spawn_id=envelope.payload.get("spawn_id", ""),
                agent_id=agent_id,
                item=envelope.payload.get("item", ""),
                quantity=granted,
                success=success,
                reason=reason,
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.NATURE, result_msg)

        if success:
            logger.info(
                "[tick %d] GATHER from %s: %d %s granted (energy: %.1f)",
                self._state.current_tick,
                agent_id,
                granted,
                envelope.payload.get("item", ""),
                self._state.get_energy(agent_id),
            )
        else:
            logger.warning(
                "[tick %d] GATHER from %s rejected: %s",
                self._state.current_tick,
                agent_id,
                reason,
            )

    async def _on_governance_message(self, envelope: Envelope) -> None:
        """Handle ValidationResult messages — deduct energy for valid market actions."""
        if envelope.type != MessageType.VALIDATION_RESULT:
            return

        valid = envelope.payload.get("valid", False)
        if not valid:
            return

        agent_id = envelope.payload.get("agent_id")
        if not agent_id:
            return

        action = envelope.payload.get("action", "")
        cost = get_energy_cost(action)
        if cost > 0:
            self._state.deduct_energy(agent_id, cost)
            logger.debug(
                "[tick %d] Deducted %.1f energy from %s for %s",
                self._state.current_tick,
                cost,
                agent_id,
                action,
            )

    async def _on_bank_message(self, envelope: Envelope) -> None:
        """Handle bank messages — process CONSUME_RESULT for energy restoration."""
        if envelope.type != MessageType.CONSUME_RESULT:
            return

        success = envelope.payload.get("success", False)
        if not success:
            return

        agent_id = envelope.payload.get("agent_id", "")
        energy_restored = envelope.payload.get("energy_restored", 0.0)

        if agent_id and energy_restored > 0:
            new_energy = process_consume_result(agent_id, energy_restored, self._state)
            logger.info(
                "[tick %d] CONSUME: %s restored %.1f energy (now %.1f)",
                self._state.current_tick,
                agent_id,
                energy_restored,
                new_energy,
            )

    async def _on_square_message(self, envelope: Envelope) -> None:
        """Handle square messages — register energy on JOIN."""
        if envelope.type != MessageType.JOIN:
            return

        agent_id = envelope.payload.get("agent_id", envelope.from_agent)
        self._state.register_energy(agent_id)
        logger.info(
            "[tick %d] Registered energy for %s",
            self._state.current_tick,
            agent_id,
        )
