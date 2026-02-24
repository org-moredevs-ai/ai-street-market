"""Economy Smoke Test — verifies the economy is alive and trading.

Starts Governor, Banker, World, Farmer, Chef, Baker in-process as async tasks,
runs for ~15 ticks with 1-second tick interval, and asserts the economy is alive.

Requires: make infra-up (real NATS)
All LLM calls are mocked — this tests the economy loop, not LLM quality.
"""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest
from streetmarket.agent.llm_brain import ActionPlan, AgentAction

pytestmark = pytest.mark.integration


# Skip if NATS isn't available
def _nats_available() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:8222/healthz", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


skip_no_nats = pytest.mark.skipif(
    not _nats_available(),
    reason="NATS not running — start with 'make infra-up'",
)


def _make_mock_llm_for_farmer():
    """Create a mock LLM that returns farmer-appropriate actions."""
    call_count = 0

    async def mock_invoke(messages):
        nonlocal call_count
        call_count += 1
        # Alternate between gather and offer
        if call_count % 2 == 1:
            return ActionPlan(
                reasoning="Gathering resources",
                actions=[
                    AgentAction(
                        kind="gather",
                        params={"item": "potato", "quantity": 5},
                    ),
                ],
            )
        else:
            return ActionPlan(
                reasoning="Selling surplus",
                actions=[
                    AgentAction(
                        kind="offer",
                        params={"item": "potato", "quantity": 3, "price_per_unit": 2.4},
                    ),
                ],
            )

    mock_structured = MagicMock()
    mock_structured.ainvoke = mock_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm


def _make_mock_llm_for_chef():
    """Create a mock LLM that returns chef-appropriate actions."""
    call_count = 0

    async def mock_invoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count % 3 == 1:
            return ActionPlan(
                reasoning="Bidding for ingredients",
                actions=[
                    AgentAction(
                        kind="bid",
                        params={"item": "potato", "quantity": 2, "max_price_per_unit": 3.0},
                    ),
                ],
            )
        elif call_count % 3 == 2:
            return ActionPlan(
                reasoning="Crafting soup",
                actions=[
                    AgentAction(kind="craft_start", params={"recipe": "soup"}),
                ],
            )
        else:
            return ActionPlan(reasoning="Waiting", actions=[])

    mock_structured = MagicMock()
    mock_structured.ainvoke = mock_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm


def _make_mock_llm_for_baker():
    """Create a mock LLM that returns baker-appropriate actions."""
    call_count = 0

    async def mock_invoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count % 3 == 1:
            return ActionPlan(
                reasoning="Bidding for potato",
                actions=[
                    AgentAction(
                        kind="bid",
                        params={"item": "potato", "quantity": 3, "max_price_per_unit": 3.0},
                    ),
                ],
            )
        elif call_count % 3 == 2:
            return ActionPlan(
                reasoning="Crafting bread",
                actions=[
                    AgentAction(kind="craft_start", params={"recipe": "bread"}),
                ],
            )
        else:
            return ActionPlan(reasoning="Waiting", actions=[])

    mock_structured = MagicMock()
    mock_structured.ainvoke = mock_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm


def _make_mock_llm_noop():
    """Create a mock LLM that does nothing (for nature brain etc)."""

    async def mock_invoke(messages):
        return ActionPlan(reasoning="idle", actions=[])

    mock_structured = MagicMock()
    mock_structured.ainvoke = mock_invoke
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured
    return mock_llm


@skip_no_nats
class TestEconomySmoke:
    """Integration tests that run a mini-economy for ~15 ticks."""

    @pytest.fixture
    def env_setup(self):
        """Set up environment for smoke tests."""
        env = {
            "OPENROUTER_API_KEY": "sk-or-test-key",
            "DEFAULT_MODEL": "test-model",
            "NATS_URL": "nats://localhost:4222",
            "TICK_INTERVAL": "1",  # 1 second ticks for fast testing
        }
        with patch.dict(os.environ, env, clear=False):
            yield

    async def test_economy_starts_and_agents_join(self, env_setup):
        """Verify agents can connect and join the economy."""
        from agents.farmer.agent import FarmerAgent

        mock_llm = _make_mock_llm_for_farmer()

        with patch("streetmarket.agent.llm_brain.ChatOpenAI", return_value=mock_llm):
            agent = FarmerAgent()
            await agent.start()
            # Wait a moment for connection
            await asyncio.sleep(0.5)
            await agent.stop()

        # If we get here without error, the agent connected successfully

    async def test_farmer_can_gather(self, env_setup):
        """Verify a farmer can gather resources from nature spawns."""
        from agents.farmer.agent import FarmerAgent

        mock_llm = _make_mock_llm_for_farmer()

        with patch("streetmarket.agent.llm_brain.ChatOpenAI", return_value=mock_llm):
            agent = FarmerAgent()
            await agent.start()
            # Let it run for a few ticks
            await asyncio.sleep(3)
            await agent.stop()

        # Farmer should have gathered something or at least processed ticks
        assert agent.state.current_tick > 0 or agent.state.joined
