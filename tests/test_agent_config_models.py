"""Tests for Pydantic models: User, AgentConfig, AgentStatus, generate_agent_id."""

from __future__ import annotations

from streetmarket.db.models import (
    AgentConfig,
    AgentStats,
    AgentStatus,
    User,
    generate_agent_id,
)

# ---------------------------------------------------------------------------
# AgentStatus enum
# ---------------------------------------------------------------------------


class TestAgentStatus:
    def test_all_values(self):
        assert AgentStatus.DRAFT == "draft"
        assert AgentStatus.READY == "ready"
        assert AgentStatus.RUNNING == "running"
        assert AgentStatus.STOPPED == "stopped"
        assert AgentStatus.ERROR == "error"

    def test_status_count(self):
        assert len(AgentStatus) == 5


# ---------------------------------------------------------------------------
# AgentStats
# ---------------------------------------------------------------------------


class TestAgentStats:
    def test_defaults(self):
        stats = AgentStats()
        assert stats.ticks_active == 0
        assert stats.messages_sent == 0
        assert stats.llm_calls == 0
        assert stats.last_active_tick == 0


# ---------------------------------------------------------------------------
# generate_agent_id
# ---------------------------------------------------------------------------


class TestGenerateAgentId:
    def test_format(self):
        agent_id = generate_agent_id()
        assert agent_id.startswith("managed-")
        assert len(agent_id) == len("managed-") + 8

    def test_unique(self):
        ids = {generate_agent_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    def test_creation_with_defaults(self):
        config = AgentConfig(
            user_id="user123",
            display_name="My Baker",
            archetype="baker",
        )
        assert config.user_id == "user123"
        assert config.display_name == "My Baker"
        assert config.archetype == "baker"
        assert config.status == AgentStatus.DRAFT
        assert config.tick_interval == 3
        assert config.claimed_by is None
        assert config.agent_id.startswith("managed-")

    def test_to_mongo(self):
        config = AgentConfig(
            agent_id="managed-test1234",
            user_id="user123",
            display_name="My Baker",
            archetype="baker",
        )
        doc = config.to_mongo()
        assert doc["agent_id"] == "managed-test1234"
        assert doc["user_id"] == "user123"
        assert doc["status"] == "draft"

    def test_from_mongo(self):
        doc = {
            "_id": "mongo_object_id",
            "agent_id": "managed-test1234",
            "user_id": "user123",
            "display_name": "My Baker",
            "archetype": "baker",
            "personality": "Friendly",
            "strategy": "Buy low sell high",
            "system_prompt": "You are a baker",
            "tick_interval": 3,
            "status": "draft",
            "stats": {"ticks_active": 0, "messages_sent": 0, "llm_calls": 0, "last_active_tick": 0},
            "claimed_by": None,
            "error_message": None,
            "created_at": 1000.0,
            "updated_at": 1000.0,
        }
        config = AgentConfig.from_mongo(doc)
        assert config.agent_id == "managed-test1234"
        assert config.status == AgentStatus.DRAFT

    def test_to_public_excludes_internal_fields(self):
        config = AgentConfig(
            user_id="user123",
            display_name="My Baker",
            archetype="baker",
            claimed_by="runner-abc",
            error_message="some error",
        )
        public = config.to_public()
        assert "claimed_by" not in public
        assert "error_message" not in public
        assert public["display_name"] == "My Baker"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class TestUser:
    def test_creation_with_defaults(self):
        user = User(
            google_id="g123",
            email="test@example.com",
            display_name="Test User",
        )
        assert user.google_id == "g123"
        assert user.max_agents == 3
        assert user.agents == []

    def test_to_mongo(self):
        user = User(
            google_id="g123",
            email="test@example.com",
        )
        doc = user.to_mongo()
        assert doc["google_id"] == "g123"
        assert doc["email"] == "test@example.com"
        assert doc["max_agents"] == 3

    def test_from_mongo(self):
        doc = {
            "_id": "mongo_id",
            "google_id": "g123",
            "email": "test@example.com",
            "display_name": "Test",
            "avatar_url": "",
            "max_agents": 3,
            "agents": ["managed-abc"],
            "created_at": 1000.0,
            "updated_at": 1000.0,
        }
        user = User.from_mongo(doc)
        assert user.google_id == "g123"
        assert user.agents == ["managed-abc"]
