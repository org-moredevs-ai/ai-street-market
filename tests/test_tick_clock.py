"""Tests for the tick clock — single_tick and stop behaviour.

All tests are async (pytest-asyncio, asyncio_mode="auto").
No NATS needed — uses a mock publish function.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import Topics
from streetmarket.policy.engine import SeasonConfig, WinningCriterion
from streetmarket.season.manager import SeasonManager, SeasonPhase

from services.tick_clock.clock import TickClock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_season_config() -> SeasonConfig:
    """10-minute season, 10s ticks = 60 ticks."""
    return SeasonConfig(
        name="Test",
        number=1,
        description="test",
        starts_at=datetime(2026, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 3, 15, 10, 10, 0, tzinfo=timezone.utc),
        tick_interval_seconds=10,
        world_policy_file="test.yaml",
        biases={},
        agent_defaults={},
        winning_criteria=[
            WinningCriterion(metric="net_worth", weight=0.4),
            WinningCriterion(metric="survival_ticks", weight=0.3),
            WinningCriterion(metric="community_contribution", weight=0.3),
        ],
        awards=[],
        closing_percent=20,
        preparation_hours=1,
        next_season_hint="",
        characters={},
    )


@pytest.fixture
def season_config() -> SeasonConfig:
    return _make_season_config()


@pytest.fixture
def season_manager(season_config: SeasonConfig) -> SeasonManager:
    mgr = SeasonManager(season_config)
    # Advance to OPEN so ticking is allowed
    mgr.advance_to(SeasonPhase.OPEN)
    return mgr


class MockPublisher:
    """Collects published envelopes for assertion."""

    def __init__(self) -> None:
        self.published: list[tuple[str, Envelope]] = []

    async def __call__(self, topic: str, envelope: Envelope) -> None:
        self.published.append((topic, envelope))


@pytest.fixture
def publisher() -> MockPublisher:
    return MockPublisher()


@pytest.fixture
def clock(
    season_manager: SeasonManager,
    publisher: MockPublisher,
) -> TickClock:
    return TickClock(season=season_manager, publish_fn=publisher)


# ---------------------------------------------------------------------------
# Tests — single_tick advances tick and publishes
# ---------------------------------------------------------------------------


async def test_single_tick_advances_tick(
    clock: TickClock,
    season_manager: SeasonManager,
    publisher: MockPublisher,
) -> None:
    """single_tick should advance the season tick counter by 1."""
    assert season_manager.current_tick == 0

    tick = await clock.single_tick()

    assert tick == 1
    assert season_manager.current_tick == 1


async def test_single_tick_advances_incrementally(
    clock: TickClock,
    season_manager: SeasonManager,
    publisher: MockPublisher,
) -> None:
    """Multiple single_tick calls advance sequentially."""
    t1 = await clock.single_tick()
    t2 = await clock.single_tick()
    t3 = await clock.single_tick()

    assert t1 == 1
    assert t2 == 2
    assert t3 == 3
    assert season_manager.current_tick == 3


async def test_single_tick_publishes_one_message(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """single_tick should publish exactly one envelope."""
    await clock.single_tick()

    assert len(publisher.published) == 1


# ---------------------------------------------------------------------------
# Tests — single_tick publishes to /system/tick
# ---------------------------------------------------------------------------


async def test_single_tick_publishes_to_system_tick(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """The published message topic should be /system/tick."""
    await clock.single_tick()

    topic, _ = publisher.published[0]
    assert topic == Topics.TICK
    assert topic == "/system/tick"


async def test_single_tick_envelope_topic_field(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """The envelope's topic field should also be /system/tick."""
    await clock.single_tick()

    _, envelope = publisher.published[0]
    assert envelope.topic == Topics.TICK


# ---------------------------------------------------------------------------
# Tests — published envelope has correct tick number
# ---------------------------------------------------------------------------


async def test_published_envelope_has_correct_tick_number(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """The envelope tick field should match the returned tick number."""
    tick = await clock.single_tick()

    _, envelope = publisher.published[0]
    assert envelope.tick == tick
    assert envelope.tick == 1


async def test_published_envelope_tick_increments(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """Each successive envelope should carry the incremented tick."""
    await clock.single_tick()
    await clock.single_tick()
    await clock.single_tick()

    ticks = [env.tick for _, env in publisher.published]
    assert ticks == [1, 2, 3]


async def test_published_envelope_from_system(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """The envelope should be from 'system'."""
    await clock.single_tick()

    _, envelope = publisher.published[0]
    assert envelope.from_agent == "system"


async def test_published_envelope_has_message(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """The envelope should contain a tick message."""
    tick = await clock.single_tick()

    _, envelope = publisher.published[0]
    assert f"Tick {tick}" in envelope.message


async def test_published_envelope_is_valid(
    clock: TickClock,
    publisher: MockPublisher,
) -> None:
    """The published envelope should be a valid Envelope with all fields."""
    await clock.single_tick()

    _, envelope = publisher.published[0]
    assert isinstance(envelope, Envelope)
    assert envelope.id  # UUID string, non-empty
    assert envelope.timestamp > 0


# ---------------------------------------------------------------------------
# Tests — stop prevents further ticks
# ---------------------------------------------------------------------------


async def test_stop_sets_running_false(
    clock: TickClock,
) -> None:
    """stop() should set is_running to False."""
    # TickClock._running starts False (only set True by start())
    clock._running = True
    assert clock.is_running is True

    clock.stop()

    assert clock.is_running is False


async def test_stop_does_not_prevent_single_tick(
    clock: TickClock,
    publisher: MockPublisher,
    season_manager: SeasonManager,
) -> None:
    """stop() affects the start() loop, but single_tick is independent.

    single_tick() is a manual test helper — it does not check _running.
    The stop() method prevents the start() loop from continuing.
    """
    clock.stop()

    # single_tick still works because it bypasses the _running flag
    tick = await clock.single_tick()
    assert tick == 1
    assert len(publisher.published) == 1


async def test_clock_not_running_initially(
    clock: TickClock,
) -> None:
    """The clock should not be running before start() is called."""
    assert clock.is_running is False


async def test_season_config_total_ticks(
    season_config: SeasonConfig,
) -> None:
    """Verify the test season has 60 ticks (10 min / 10s)."""
    assert season_config.total_ticks == 60
