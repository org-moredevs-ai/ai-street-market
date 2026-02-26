"""Season manager — UTC-based season lifecycle.

Manages season phases: ANNOUNCED -> PREPARATION -> OPEN -> CLOSING -> ENDED.
Ticks are inferred from UTC dates and tick interval.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone

from streetmarket.policy.engine import SeasonConfig


class SeasonPhase(str, enum.Enum):
    """Season lifecycle phases."""

    DORMANT = "dormant"
    ANNOUNCED = "announced"
    PREPARATION = "preparation"
    OPEN = "open"
    CLOSING = "closing"
    ENDED = "ended"


@dataclass
class SeasonState:
    """Current season runtime state."""

    config: SeasonConfig
    phase: SeasonPhase = SeasonPhase.ANNOUNCED
    current_tick: int = 0
    announced_at: datetime | None = None
    preparation_at: datetime | None = None
    opened_at: datetime | None = None
    closing_at: datetime | None = None
    ended_at: datetime | None = None


class SeasonManager:
    """Manages the season lifecycle.

    The season manager tracks the current phase and tick count.
    Phase transitions are time-based (UTC) or tick-based.
    """

    def __init__(self, config: SeasonConfig) -> None:
        self._state = SeasonState(
            config=config,
            announced_at=datetime.now(timezone.utc),
        )

    @property
    def phase(self) -> SeasonPhase:
        return self._state.phase

    @property
    def current_tick(self) -> int:
        return self._state.current_tick

    @property
    def config(self) -> SeasonConfig:
        return self._state.config

    @property
    def total_ticks(self) -> int:
        return self._state.config.total_ticks

    @property
    def is_accepting_agents(self) -> bool:
        """Can new agents join? Only during OPEN phase."""
        return self._state.phase == SeasonPhase.OPEN

    @property
    def is_running(self) -> bool:
        """Is the economy running? During OPEN or CLOSING."""
        return self._state.phase in (SeasonPhase.OPEN, SeasonPhase.CLOSING)

    @property
    def progress_percent(self) -> float:
        """Current progress through the season (0-100)."""
        if self.total_ticks == 0:
            return 0.0
        return min(100.0, (self._state.current_tick / self.total_ticks) * 100)

    def advance_to(self, phase: SeasonPhase) -> None:
        """Manually advance to a specific phase."""
        now = datetime.now(timezone.utc)
        self._state.phase = phase
        if phase == SeasonPhase.PREPARATION:
            self._state.preparation_at = now
        elif phase == SeasonPhase.OPEN:
            self._state.opened_at = now
        elif phase == SeasonPhase.CLOSING:
            self._state.closing_at = now
        elif phase == SeasonPhase.ENDED:
            self._state.ended_at = now

    def tick(self) -> int:
        """Advance one tick. Returns the new tick number.

        Automatically transitions to CLOSING when progress threshold is reached.
        """
        if not self.is_running:
            raise RuntimeError(
                f"Cannot tick in phase {self._state.phase.value} — season must be OPEN or CLOSING"
            )
        self._state.current_tick += 1

        # Auto-transition to CLOSING when threshold reached
        if (
            self._state.phase == SeasonPhase.OPEN
            and self._state.current_tick >= self._state.config.closing_tick
        ):
            self.advance_to(SeasonPhase.CLOSING)

        # Auto-transition to ENDED when total ticks reached
        if self._state.current_tick >= self.total_ticks:
            self.advance_to(SeasonPhase.ENDED)

        return self._state.current_tick

    def tick_to_utc(self, tick: int) -> datetime:
        """Convert a tick number to its UTC timestamp."""
        seconds_offset = tick * self._state.config.tick_interval_seconds
        from datetime import timedelta

        return self._state.config.starts_at + timedelta(seconds=seconds_offset)

    def utc_to_tick(self, dt: datetime) -> int:
        """Convert a UTC datetime to its approximate tick number."""
        delta = (dt - self._state.config.starts_at).total_seconds()
        return max(0, int(delta / self._state.config.tick_interval_seconds))

    def snapshot(self) -> dict:
        """Return a snapshot of the current season state."""
        return {
            "name": self._state.config.name,
            "number": self._state.config.number,
            "phase": self._state.phase.value,
            "current_tick": self._state.current_tick,
            "total_ticks": self.total_ticks,
            "progress_percent": round(self.progress_percent, 1),
            "tick_interval_seconds": self._state.config.tick_interval_seconds,
            "starts_at": self._state.config.starts_at.isoformat(),
            "ends_at": self._state.config.ends_at.isoformat(),
        }
