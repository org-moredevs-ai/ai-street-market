"""WorldEngine — tick clock, nature spawns, and gather protocol."""

import asyncio
import logging
import os
import time

from streetmarket import (
    Envelope,
    GatherResult,
    MarketBusClient,
    MessageType,
    Spawn,
    Tick,
    Topics,
    create_message,
)

from services.world.rules import process_gather, process_tick
from services.world.state import DEFAULT_TICK_INTERVAL, WorldState

logger = logging.getLogger(__name__)


class WorldEngine:
    """The World Engine is the simulation's heartbeat.

    It publishes Tick messages at a configurable interval,
    spawns raw materials each tick, and handles FCFS gathering.
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
        """Execute one tick: advance state, publish Tick + Spawn."""
        tick_number, spawn_id, items = process_tick(self._state)

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

        logger.info(
            "[tick %d] Published tick + spawn (spawn_id=%s)",
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

        granted, success, reason = process_gather(envelope, self._state)

        result_msg = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.NATURE,
            msg_type=MessageType.GATHER_RESULT,
            payload=GatherResult(
                reference_msg_id=envelope.id,
                spawn_id=envelope.payload.get("spawn_id", ""),
                agent_id=envelope.from_agent,
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
                "[tick %d] GATHER from %s: %d %s granted",
                self._state.current_tick,
                envelope.from_agent,
                granted,
                envelope.payload.get("item", ""),
            )
        else:
            logger.warning(
                "[tick %d] GATHER from %s rejected: %s",
                self._state.current_tick,
                envelope.from_agent,
                reason,
            )
