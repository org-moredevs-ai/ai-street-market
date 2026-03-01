"""Tests for the Agent Manager — NATS request-reply CRUD service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from streetmarket.db.models import AgentConfig, AgentStatus, User

from services.agent_manager.manager import AgentManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeCollection:
    """In-memory MongoDB collection mock."""

    def __init__(self):
        self._docs: list[dict] = []

    async def find_one(self, query: dict) -> dict | None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items() if not k.startswith("$")):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict):
        self._docs.append(dict(doc))
        return MagicMock(inserted_id="fake_id")

    async def update_one(self, query: dict, update: dict):
        for doc in self._docs:
            match = all(doc.get(k) == v for k, v in query.items() if not k.startswith("$"))
            if match:
                if "$set" in update:
                    doc.update(update["$set"])
                if "$push" in update:
                    for k, v in update["$push"].items():
                        doc.setdefault(k, []).append(v)
                if "$pull" in update:
                    for k, v in update["$pull"].items():
                        if k in doc and v in doc[k]:
                            doc[k].remove(v)
                return MagicMock(modified_count=1)
        return MagicMock(modified_count=0)

    async def delete_one(self, query: dict):
        for i, doc in enumerate(self._docs):
            if all(doc.get(k) == v for k, v in query.items()):
                self._docs.pop(i)
                return MagicMock(deleted_count=1)
        return MagicMock(deleted_count=0)

    def find(self, query: dict):
        """Return async iterable of matching docs."""
        results = []
        for doc in self._docs:
            match = True
            for k, v in query.items():
                if k.startswith("$"):
                    continue
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                results.append(dict(doc))

        return _AsyncCursor(results)

    async def create_index(self, *args, **kwargs):
        pass


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


@pytest.fixture
def mock_nc():
    nc = AsyncMock()
    nc.publish = AsyncMock()
    nc.subscribe = AsyncMock()
    return nc


@pytest.fixture
def users_col():
    return FakeCollection()


@pytest.fixture
def agents_col():
    return FakeCollection()


@pytest.fixture
def manager(mock_nc, users_col, agents_col):
    mgr = AgentManager(mock_nc)
    # Override DB collections
    mock_db = MagicMock()
    mock_db.__getitem__ = lambda self, key: users_col if key == "users" else agents_col
    mgr._db = mock_db
    return mgr


@pytest.fixture
def sample_user_doc():
    return User(
        google_id="g123",
        email="test@example.com",
        display_name="Test User",
    ).to_mongo()


async def _seed_user(users_col, google_id="g123"):
    user = User(
        google_id=google_id,
        email=f"{google_id}@example.com",
        display_name="Test User",
    )
    await users_col.insert_one(user.to_mongo())
    return user


# ---------------------------------------------------------------------------
# User Handlers
# ---------------------------------------------------------------------------


class TestUserHandlers:
    @pytest.mark.asyncio
    async def test_upsert_creates_new_user(self, manager, users_col):
        result = await manager._handle_user_upsert(
            {
                "google_id": "g123",
                "email": "test@example.com",
                "display_name": "Test User",
            }
        )
        assert result["google_id"] == "g123"
        assert result["email"] == "test@example.com"
        assert len(users_col._docs) == 1

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_user(self, manager, users_col):
        await _seed_user(users_col)

        result = await manager._handle_user_upsert(
            {
                "google_id": "g123",
                "display_name": "Updated Name",
            }
        )
        assert result["display_name"] == "Updated Name"

    @pytest.mark.asyncio
    async def test_upsert_requires_google_id(self, manager):
        with pytest.raises(ValueError, match="google_id"):
            await manager._handle_user_upsert({})

    @pytest.mark.asyncio
    async def test_get_user(self, manager, users_col):
        await _seed_user(users_col)
        result = await manager._handle_user_get({"google_id": "g123"})
        assert result["google_id"] == "g123"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, manager):
        with pytest.raises(ValueError, match="not found"):
            await manager._handle_user_get({"google_id": "nonexistent"})


# ---------------------------------------------------------------------------
# Agent Handlers
# ---------------------------------------------------------------------------


class TestAgentHandlers:
    @pytest.mark.asyncio
    async def test_create_agent(self, manager, users_col, agents_col):
        await _seed_user(users_col)

        result = await manager._handle_agent_create(
            {
                "user_id": "g123",
                "display_name": "My Baker",
                "archetype": "baker",
            }
        )
        assert result["display_name"] == "My Baker"
        assert result["archetype"] == "baker"
        assert result["status"] == "draft"
        assert len(agents_col._docs) == 1

    @pytest.mark.asyncio
    async def test_create_agent_checks_limit(self, manager, users_col, agents_col):
        await _seed_user(users_col)
        # Fill up agents
        users_col._docs[0]["agents"] = ["a1", "a2", "a3"]

        with pytest.raises(ValueError, match="limit reached"):
            await manager._handle_agent_create(
                {
                    "user_id": "g123",
                    "display_name": "Too Many",
                    "archetype": "baker",
                }
            )

    @pytest.mark.asyncio
    async def test_create_agent_requires_display_name(self, manager, users_col):
        await _seed_user(users_col)
        with pytest.raises(ValueError, match="display_name"):
            await manager._handle_agent_create({"user_id": "g123", "archetype": "baker"})

    @pytest.mark.asyncio
    async def test_update_agent_draft(self, manager, users_col, agents_col):
        await _seed_user(users_col)
        created = await manager._handle_agent_create(
            {
                "user_id": "g123",
                "display_name": "Old Name",
                "archetype": "baker",
            }
        )
        agent_id = created["agent_id"]

        result = await manager._handle_agent_update(
            {
                "agent_id": agent_id,
                "display_name": "New Name",
                "personality": "Very grumpy",
            }
        )
        assert result["display_name"] == "New Name"
        assert result["personality"] == "Very grumpy"

    @pytest.mark.asyncio
    async def test_update_running_agent_fails(self, manager, agents_col):
        config = AgentConfig(
            user_id="g123",
            display_name="Running",
            archetype="baker",
            status=AgentStatus.RUNNING,
        )
        await agents_col.insert_one(config.to_mongo())

        with pytest.raises(ValueError, match="Cannot update"):
            await manager._handle_agent_update({"agent_id": config.agent_id, "display_name": "New"})

    @pytest.mark.asyncio
    async def test_delete_agent(self, manager, users_col, agents_col):
        await _seed_user(users_col)
        created = await manager._handle_agent_create(
            {"user_id": "g123", "display_name": "Delete Me", "archetype": "baker"}
        )
        agent_id = created["agent_id"]

        result = await manager._handle_agent_delete({"agent_id": agent_id})
        assert result["deleted"] == agent_id

    @pytest.mark.asyncio
    async def test_delete_running_fails(self, manager, agents_col):
        config = AgentConfig(
            user_id="g123",
            display_name="Running",
            archetype="baker",
            status=AgentStatus.RUNNING,
        )
        await agents_col.insert_one(config.to_mongo())

        with pytest.raises(ValueError, match="running"):
            await manager._handle_agent_delete({"agent_id": config.agent_id})

    @pytest.mark.asyncio
    async def test_list_agents(self, manager, users_col, agents_col):
        await _seed_user(users_col)
        await manager._handle_agent_create(
            {"user_id": "g123", "display_name": "Agent 1", "archetype": "baker"}
        )
        await manager._handle_agent_create(
            {"user_id": "g123", "display_name": "Agent 2", "archetype": "farmer"}
        )

        result = await manager._handle_agent_list({"user_id": "g123"})
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_agent(self, manager, users_col, agents_col):
        await _seed_user(users_col)
        created = await manager._handle_agent_create(
            {"user_id": "g123", "display_name": "Get Me", "archetype": "fisher"}
        )
        agent_id = created["agent_id"]

        result = await manager._handle_agent_get({"agent_id": agent_id})
        assert result["display_name"] == "Get Me"

    @pytest.mark.asyncio
    async def test_start_agent(self, manager, users_col, agents_col, mock_nc):
        await _seed_user(users_col)
        created = await manager._handle_agent_create(
            {"user_id": "g123", "display_name": "Start Me", "archetype": "baker"}
        )
        agent_id = created["agent_id"]

        result = await manager._handle_agent_start({"agent_id": agent_id})
        assert result["status"] == "ready"

        # Should have published system.agents.changed
        mock_nc.publish.assert_called()

    @pytest.mark.asyncio
    async def test_stop_agent(self, manager, agents_col, mock_nc):
        config = AgentConfig(
            user_id="g123",
            display_name="Running",
            archetype="baker",
            status=AgentStatus.RUNNING,
        )
        await agents_col.insert_one(config.to_mongo())

        result = await manager._handle_agent_stop({"agent_id": config.agent_id})
        assert result["status"] == "stopped"
        mock_nc.publish.assert_called()


# ---------------------------------------------------------------------------
# Prompt & Archetype Handlers
# ---------------------------------------------------------------------------


class TestPromptAndArchetypeHandlers:
    @pytest.mark.asyncio
    async def test_generate_prompt(self, manager):
        result = await manager._handle_prompt_generate(
            {
                "archetype": "baker",
                "display_name": "Hugo's Bakery",
                "personality": "Friendly",
            }
        )
        assert "Hugo's Bakery" in result["system_prompt"]
        assert "Friendly" in result["system_prompt"]

    @pytest.mark.asyncio
    async def test_list_archetypes(self, manager):
        result = await manager._handle_archetypes_list({})
        assert len(result) == 7
        ids = [a["id"] for a in result]
        assert "baker" in ids
        assert "custom" in ids
