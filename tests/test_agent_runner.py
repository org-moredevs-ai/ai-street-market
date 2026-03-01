"""Tests for the Agent Runner — loads and runs managed agents."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from streetmarket.db.models import AgentConfig, AgentStatus

from services.agent_runner.runner import AgentRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCollection:
    """In-memory MongoDB collection mock."""

    def __init__(self, docs: list[dict] | None = None):
        self._docs: list[dict] = docs or []

    async def find_one(self, query: dict) -> dict | None:
        for doc in self._docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def update_one(self, query: dict, update: dict):
        for doc in self._docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                return MagicMock(modified_count=1)
        return MagicMock(modified_count=0)

    async def update_many(self, query: dict, update: dict):
        count = 0
        for doc in self._docs:
            if self._matches(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                count += 1
        return MagicMock(modified_count=count)

    def find(self, query: dict):
        results = [dict(d) for d in self._docs if self._matches(d, query)]
        return _AsyncCursor(results)

    def _matches(self, doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if k == "$or":
                if not any(self._matches(doc, sub) for sub in v):
                    return False
            elif k.startswith("$"):
                continue
            elif isinstance(v, dict):
                if "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        return False
                elif "$ne" in v:
                    if doc.get(k) == v["$ne"]:
                        return False
                else:
                    if doc.get(k) != v:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = docs
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._index]
        self._index += 1
        return doc


def _make_agent_doc(**overrides) -> dict:
    defaults = AgentConfig(
        agent_id="managed-test1234",
        user_id="g123",
        display_name="Test Baker",
        archetype="baker",
        system_prompt="You are a test baker.",
        status=AgentStatus.READY,
    ).to_mongo()
    defaults.update(overrides)
    return defaults


@pytest.fixture
def mock_nc():
    nc = AsyncMock()
    nc.publish = AsyncMock()
    nc.subscribe = AsyncMock()
    return nc


@pytest.fixture
def agents_col():
    return FakeCollection()


@pytest.fixture
def runner(mock_nc, agents_col):
    r = AgentRunner(
        mock_nc,
        runner_id="test-runner-1",
        nats_url="nats://localhost:4222",
    )
    mock_db = MagicMock()
    mock_db.__getitem__ = lambda self, key: agents_col
    r._db = mock_db
    return r


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestRunnerConstruction:
    def test_basic_construction(self, mock_nc):
        runner = AgentRunner(mock_nc, runner_id="r1")
        assert runner.runner_id == "r1"
        assert len(runner.active_agents) == 0

    def test_auto_generated_id(self, mock_nc):
        runner = AgentRunner(mock_nc)
        assert runner.runner_id.startswith("runner-")


# ---------------------------------------------------------------------------
# Agent Start/Stop
# ---------------------------------------------------------------------------


class TestAgentStartStop:
    @pytest.mark.asyncio
    @patch("services.agent_runner.runner.create_managed_agent")
    async def test_start_agent_claims_and_runs(self, mock_create, runner, agents_col):
        doc = _make_agent_doc()
        agents_col._docs.append(doc)

        mock_agent = AsyncMock()
        mock_agent.stats = MagicMock(
            ticks_active=0, messages_sent=0, llm_calls=0, last_active_tick=0
        )
        mock_agent.run = AsyncMock(side_effect=asyncio.CancelledError)
        mock_create.return_value = mock_agent

        config = AgentConfig.from_mongo(dict(doc))
        await runner._start_agent(config)

        # Agent should be claimed
        assert doc["status"] == "running"
        assert doc["claimed_by"] == "test-runner-1"

        # Agent should be in active agents
        assert "managed-test1234" in runner.active_agents

        mock_agent.connect.assert_called_once()
        mock_agent.join.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.agent_runner.runner.create_managed_agent")
    async def test_stop_agent(self, mock_create, runner, agents_col):
        doc = _make_agent_doc(status="running", claimed_by="test-runner-1")
        agents_col._docs.append(doc)

        mock_agent = AsyncMock()
        mock_agent.stats = MagicMock(
            ticks_active=10, messages_sent=5, llm_calls=3, last_active_tick=10
        )
        mock_create.return_value = mock_agent

        # Manually add to runner
        runner._agents["managed-test1234"] = mock_agent

        await runner._stop_agent("managed-test1234")

        mock_agent.stop.assert_called_once()
        mock_agent.disconnect.assert_called_once()
        assert "managed-test1234" not in runner.active_agents

    @pytest.mark.asyncio
    @patch("services.agent_runner.runner.create_managed_agent")
    async def test_start_already_claimed_skips(self, mock_create, runner, agents_col):
        doc = _make_agent_doc(status="running", claimed_by="other-runner")
        agents_col._docs.append(doc)

        config = AgentConfig.from_mongo(dict(doc))
        await runner._start_agent(config)

        # Should not create an agent
        mock_create.assert_not_called()
        assert "managed-test1234" not in runner.active_agents


# ---------------------------------------------------------------------------
# Event Handling
# ---------------------------------------------------------------------------


class TestEventHandling:
    @pytest.mark.asyncio
    @patch("services.agent_runner.runner.create_managed_agent")
    async def test_on_agents_changed_start(self, mock_create, runner, agents_col):
        doc = _make_agent_doc()
        agents_col._docs.append(doc)

        mock_agent = AsyncMock()
        mock_agent.stats = MagicMock(
            ticks_active=0, messages_sent=0, llm_calls=0, last_active_tick=0
        )
        mock_agent.run = AsyncMock(side_effect=asyncio.CancelledError)
        mock_create.return_value = mock_agent

        msg = MagicMock()
        msg.data = json.dumps({"action": "start", "agent_id": "managed-test1234"}).encode()

        await runner._on_agents_changed(msg)

        assert "managed-test1234" in runner.active_agents

    @pytest.mark.asyncio
    async def test_on_agents_changed_stop(self, runner, agents_col):
        doc = _make_agent_doc(status="running", claimed_by="test-runner-1")
        agents_col._docs.append(doc)

        mock_agent = AsyncMock()
        mock_agent.stats = MagicMock(
            ticks_active=0, messages_sent=0, llm_calls=0, last_active_tick=0
        )
        runner._agents["managed-test1234"] = mock_agent

        msg = MagicMock()
        msg.data = json.dumps({"action": "stop", "agent_id": "managed-test1234"}).encode()

        await runner._on_agents_changed(msg)

        assert "managed-test1234" not in runner.active_agents


# ---------------------------------------------------------------------------
# Stats Flush
# ---------------------------------------------------------------------------


class TestStatsFlush:
    @pytest.mark.asyncio
    async def test_flush_agent_stats(self, runner, agents_col):
        doc = _make_agent_doc(status="running", claimed_by="test-runner-1")
        agents_col._docs.append(doc)

        mock_agent = MagicMock()
        mock_agent.stats = MagicMock(
            ticks_active=50,
            messages_sent=20,
            llm_calls=15,
            last_active_tick=50,
        )
        runner._agents["managed-test1234"] = mock_agent

        await runner._flush_agent_stats("managed-test1234", mock_agent)

        assert agents_col._docs[0]["stats.ticks_active"] == 50
        assert agents_col._docs[0]["stats.messages_sent"] == 20

    @pytest.mark.asyncio
    async def test_flush_all_stats(self, runner, agents_col):
        doc = _make_agent_doc(status="running", claimed_by="test-runner-1")
        agents_col._docs.append(doc)

        mock_agent = MagicMock()
        mock_agent.stats = MagicMock(
            ticks_active=10, messages_sent=5, llm_calls=3, last_active_tick=10
        )
        runner._agents["managed-test1234"] = mock_agent

        await runner._flush_all_stats()

        assert agents_col._docs[0]["stats.ticks_active"] == 10


# ---------------------------------------------------------------------------
# Runner Lifecycle
# ---------------------------------------------------------------------------


class TestRunnerLifecycle:
    @pytest.mark.asyncio
    async def test_stop_releases_claims(self, runner, mock_nc, agents_col):
        doc = _make_agent_doc(status="running", claimed_by="test-runner-1")
        agents_col._docs.append(doc)

        runner._running = True
        await runner.stop()

        assert doc["status"] == "stopped"
        assert doc["claimed_by"] is None
