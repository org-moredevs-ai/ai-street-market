"""Pydantic models for managed agents — stored in MongoDB.

Collections:
- users: Google OAuth users who own agents
- agent_configs: Agent configurations created by users

All models serialize to/from MongoDB-compatible dicts.
"""

from __future__ import annotations

import enum
import time
import uuid

from pydantic import BaseModel, Field


class AgentStatus(str, enum.Enum):
    """Agent lifecycle status."""

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class AgentStats(BaseModel):
    """Runtime statistics for a managed agent."""

    ticks_active: int = 0
    messages_sent: int = 0
    llm_calls: int = 0
    last_active_tick: int = 0


class AgentConfig(BaseModel):
    """Configuration for a managed agent — stored in MongoDB agent_configs collection.

    Indexes: agent_id (unique), user_id, status
    """

    agent_id: str = Field(default_factory=lambda: generate_agent_id())
    user_id: str
    display_name: str
    archetype: str
    personality: str = ""
    strategy: str = ""
    system_prompt: str = ""
    tick_interval: int = 3
    status: AgentStatus = AgentStatus.DRAFT
    stats: AgentStats = Field(default_factory=AgentStats)
    claimed_by: str | None = None
    error_message: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def to_mongo(self) -> dict:
        """Convert to MongoDB document."""
        return self.model_dump()

    @classmethod
    def from_mongo(cls, doc: dict) -> AgentConfig:
        """Create from MongoDB document."""
        doc.pop("_id", None)
        return cls(**doc)

    def to_public(self) -> dict:
        """Convert to public-facing dict (no internal fields)."""
        data = self.model_dump()
        data.pop("claimed_by", None)
        data.pop("error_message", None)
        return data


class User(BaseModel):
    """User account — stored in MongoDB users collection.

    Indexes: google_id (unique), email (unique)
    """

    google_id: str
    email: str
    display_name: str = ""
    avatar_url: str = ""
    max_agents: int = 3
    agents: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def to_mongo(self) -> dict:
        """Convert to MongoDB document."""
        return self.model_dump()

    @classmethod
    def from_mongo(cls, doc: dict) -> User:
        """Create from MongoDB document."""
        doc.pop("_id", None)
        return cls(**doc)


def generate_agent_id() -> str:
    """Generate a unique agent ID for managed agents.

    Format: managed-{short_uuid} (e.g., managed-a1b2c3d4)
    """
    return f"managed-{uuid.uuid4().hex[:8]}"
