"""Tick clock — broadcasts ticks at configurable intervals.

The tick clock is the heartbeat of the economy. It publishes tick
messages to /system/tick at the configured interval. The season
manager determines when the clock starts and stops.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from streetmarket.helpers.factory import create_message
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics
from streetmarket.season.manager import SeasonManager

logger = logging.getLogger(__name__)

PublishFn = Callable[[str, Envelope], Coroutine[Any, Any, None]]


class TickClock:
    """Broadcasts ticks to the message bus.

    The clock runs as an async loop, publishing tick messages at the
    interval specified by the season config.
    """

    def __init__(
        self,
        season: SeasonManager,
        publish_fn: PublishFn,
    ) -> None:
        self._season = season
        self._publish = publish_fn
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the tick clock loop."""
        self._running = True
        interval = self._season.config.tick_interval_seconds
        logger.info(
            "Tick clock started (interval=%ds, total=%d ticks)",
            interval,
            self._season.total_ticks,
        )
        try:
            while self._running and self._season.is_running:
                await asyncio.sleep(interval)
                if not self._running:
                    break
                tick = self._season.tick()
                envelope = create_message(
                    from_agent="system",
                    topic=Topics.TICK,
                    message=f"Tick {tick}",
                    tick=tick,
                )
                await self._publish(Topics.TICK, envelope)
                logger.debug("Tick %d (%.1f%%)", tick, self._season.progress_percent)

                if not self._season.is_running:
                    logger.info("Season ended at tick %d", tick)
                    break
        finally:
            self._running = False
            logger.info("Tick clock stopped")

    def stop(self) -> None:
        """Stop the tick clock."""
        self._running = False

    async def single_tick(self) -> int:
        """Advance a single tick and publish. For testing."""
        tick = self._season.tick()
        envelope = create_message(
            from_agent="system",
            topic=Topics.TICK,
            message=f"Tick {tick}",
            tick=tick,
        )
        await self._publish(Topics.TICK, envelope)
        return tick
