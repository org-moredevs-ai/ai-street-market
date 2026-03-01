"""Agent Manager — NATS request-reply service for managed agent CRUD.

Handles all management operations via NATS request-reply on system.manage.>:
- User CRUD (upsert, get)
- Agent CRUD (create, update, delete, list, get, start, stop)
- Prompt generation
- Archetype listing

No REST API — the viewer communicates through NATS via the WebSocket bridge.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from streetmarket.db.connection import get_database
from streetmarket.db.models import AgentConfig, AgentStatus, User

from services.agent_manager.archetypes import (
    archetype_to_dict,
    get_archetype,
    list_archetypes,
)
from services.agent_manager.prompt_generator import generate_system_prompt

logger = logging.getLogger(__name__)

# NATS subject prefix for management commands
MANAGE_PREFIX = "system.manage"


class AgentManager:
    """Stateless NATS request-reply service for managed agent CRUD.

    All state lives in MongoDB. This service just handles requests.
    """

    def __init__(self, nats_client: Any) -> None:
        self._nc = nats_client
        self._db = get_database()

    @property
    def users(self):
        return self._db["users"]

    @property
    def agent_configs(self):
        return self._db["agent_configs"]

    async def setup_indexes(self) -> None:
        """Create MongoDB indexes for users and agent_configs."""
        await self.users.create_index("google_id", unique=True)
        await self.users.create_index("email", unique=True)
        await self.agent_configs.create_index("agent_id", unique=True)
        await self.agent_configs.create_index("user_id")
        await self.agent_configs.create_index("status")
        logger.info("MongoDB indexes created")

    async def start(self) -> None:
        """Subscribe to all management subjects."""
        handlers = {
            f"{MANAGE_PREFIX}.user.upsert": self._handle_user_upsert,
            f"{MANAGE_PREFIX}.user.get": self._handle_user_get,
            f"{MANAGE_PREFIX}.agent.create": self._handle_agent_create,
            f"{MANAGE_PREFIX}.agent.update": self._handle_agent_update,
            f"{MANAGE_PREFIX}.agent.delete": self._handle_agent_delete,
            f"{MANAGE_PREFIX}.agent.list": self._handle_agent_list,
            f"{MANAGE_PREFIX}.agent.get": self._handle_agent_get,
            f"{MANAGE_PREFIX}.agent.start": self._handle_agent_start,
            f"{MANAGE_PREFIX}.agent.stop": self._handle_agent_stop,
            f"{MANAGE_PREFIX}.prompt.generate": self._handle_prompt_generate,
            f"{MANAGE_PREFIX}.archetypes.list": self._handle_archetypes_list,
        }

        for subject, handler in handlers.items():
            await self._nc.subscribe(subject, cb=self._make_handler(handler))
            logger.info("Subscribed to %s", subject)

        await self.setup_indexes()
        logger.info("Agent Manager started — %d handlers registered", len(handlers))

    def _make_handler(self, handler):
        """Wrap a handler with JSON parsing and error handling."""

        async def wrapper(msg):
            try:
                data = json.loads(msg.data.decode()) if msg.data else {}
                result = await handler(data)
                reply = json.dumps({"ok": True, "data": result})
            except Exception as e:
                logger.exception("Handler error: %s", e)
                reply = json.dumps({"ok": False, "error": str(e)})

            if msg.reply:
                await self._nc.publish(msg.reply, reply.encode())

        return wrapper

    # -- User Handlers --

    async def _handle_user_upsert(self, data: dict) -> dict:
        """Create or update a user (Google OAuth)."""
        google_id = data.get("google_id")
        if not google_id:
            raise ValueError("google_id is required")

        email = data.get("email", "")
        display_name = data.get("display_name", "")
        avatar_url = data.get("avatar_url", "")

        existing = await self.users.find_one({"google_id": google_id})

        if existing:
            update = {
                "$set": {
                    "email": email or existing.get("email", ""),
                    "display_name": display_name or existing.get("display_name", ""),
                    "avatar_url": avatar_url or existing.get("avatar_url", ""),
                    "updated_at": time.time(),
                }
            }
            await self.users.update_one({"google_id": google_id}, update)
            doc = await self.users.find_one({"google_id": google_id})
            user = User.from_mongo(doc)
            return user.to_mongo()
        else:
            user = User(
                google_id=google_id,
                email=email,
                display_name=display_name,
                avatar_url=avatar_url,
            )
            await self.users.insert_one(user.to_mongo())
            return user.to_mongo()

    async def _handle_user_get(self, data: dict) -> dict:
        """Get a user by google_id."""
        google_id = data.get("google_id")
        if not google_id:
            raise ValueError("google_id is required")

        doc = await self.users.find_one({"google_id": google_id})
        if not doc:
            raise ValueError(f"User not found: {google_id}")

        user = User.from_mongo(doc)
        return user.to_mongo()

    # -- Agent Handlers --

    async def _handle_agent_create(self, data: dict) -> dict:
        """Create a new agent config."""
        user_id = data.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")

        # Check user exists
        user_doc = await self.users.find_one({"google_id": user_id})
        if not user_doc:
            raise ValueError(f"User not found: {user_id}")

        user = User.from_mongo(user_doc)

        # Check agent limit
        if len(user.agents) >= user.max_agents:
            raise ValueError(
                f"Agent limit reached ({user.max_agents}). Delete an existing agent first."
            )

        # Create agent config
        display_name = data.get("display_name", "")
        if not display_name:
            raise ValueError("display_name is required")

        archetype_id = data.get("archetype", "custom")
        personality = data.get("personality", "")
        strategy = data.get("strategy", "")
        tick_interval = data.get("tick_interval", 3)

        # Generate system prompt
        system_prompt = generate_system_prompt(
            archetype_id=archetype_id,
            display_name=display_name,
            personality=personality,
            strategy=strategy,
        )

        archetype = get_archetype(archetype_id)
        if archetype and tick_interval == 3:
            tick_interval = archetype.suggested_tick_interval

        config = AgentConfig(
            user_id=user_id,
            display_name=display_name,
            archetype=archetype_id,
            personality=personality,
            strategy=strategy,
            system_prompt=system_prompt,
            tick_interval=tick_interval,
        )

        await self.agent_configs.insert_one(config.to_mongo())

        # Add agent to user's agents list
        await self.users.update_one(
            {"google_id": user_id},
            {
                "$push": {"agents": config.agent_id},
                "$set": {"updated_at": time.time()},
            },
        )

        return config.to_public()

    async def _handle_agent_update(self, data: dict) -> dict:
        """Update an agent config (only draft/stopped)."""
        agent_id = data.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        doc = await self.agent_configs.find_one({"agent_id": agent_id})
        if not doc:
            raise ValueError(f"Agent not found: {agent_id}")

        config = AgentConfig.from_mongo(doc)

        # Only allow updates when draft or stopped
        if config.status not in (AgentStatus.DRAFT, AgentStatus.STOPPED):
            raise ValueError(
                f"Cannot update agent in status '{config.status.value}'. Stop the agent first."
            )

        # Apply updates
        update_fields: dict[str, Any] = {"updated_at": time.time()}

        for field in ("display_name", "personality", "strategy", "tick_interval"):
            if field in data:
                update_fields[field] = data[field]

        if "archetype" in data:
            update_fields["archetype"] = data["archetype"]

        # Regenerate system prompt if any relevant field changed
        if any(f in data for f in ("archetype", "display_name", "personality", "strategy")):
            new_display = data.get("display_name", config.display_name)
            new_archetype = data.get("archetype", config.archetype)
            new_personality = data.get("personality", config.personality)
            new_strategy = data.get("strategy", config.strategy)

            update_fields["system_prompt"] = generate_system_prompt(
                archetype_id=new_archetype,
                display_name=new_display,
                personality=new_personality,
                strategy=new_strategy,
            )

        await self.agent_configs.update_one(
            {"agent_id": agent_id},
            {"$set": update_fields},
        )

        updated_doc = await self.agent_configs.find_one({"agent_id": agent_id})
        return AgentConfig.from_mongo(updated_doc).to_public()

    async def _handle_agent_delete(self, data: dict) -> dict:
        """Delete an agent config."""
        agent_id = data.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        doc = await self.agent_configs.find_one({"agent_id": agent_id})
        if not doc:
            raise ValueError(f"Agent not found: {agent_id}")

        config = AgentConfig.from_mongo(doc)

        # Don't delete running agents
        if config.status == AgentStatus.RUNNING:
            raise ValueError("Cannot delete a running agent. Stop it first.")

        # Remove from user's agents list
        await self.users.update_one(
            {"google_id": config.user_id},
            {
                "$pull": {"agents": agent_id},
                "$set": {"updated_at": time.time()},
            },
        )

        await self.agent_configs.delete_one({"agent_id": agent_id})

        return {"deleted": agent_id}

    async def _handle_agent_list(self, data: dict) -> list[dict]:
        """List agents for a user."""
        user_id = data.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")

        cursor = self.agent_configs.find({"user_id": user_id})
        agents = []
        async for doc in cursor:
            agents.append(AgentConfig.from_mongo(doc).to_public())

        return agents

    async def _handle_agent_get(self, data: dict) -> dict:
        """Get a single agent config."""
        agent_id = data.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        doc = await self.agent_configs.find_one({"agent_id": agent_id})
        if not doc:
            raise ValueError(f"Agent not found: {agent_id}")

        return AgentConfig.from_mongo(doc).to_public()

    async def _handle_agent_start(self, data: dict) -> dict:
        """Start an agent — set status=ready, notify runners."""
        agent_id = data.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        doc = await self.agent_configs.find_one({"agent_id": agent_id})
        if not doc:
            raise ValueError(f"Agent not found: {agent_id}")

        config = AgentConfig.from_mongo(doc)

        if config.status == AgentStatus.RUNNING:
            return config.to_public()  # Already running

        if config.status not in (
            AgentStatus.DRAFT,
            AgentStatus.STOPPED,
            AgentStatus.ERROR,
        ):
            raise ValueError(f"Cannot start agent in status '{config.status.value}'")

        await self.agent_configs.update_one(
            {"agent_id": agent_id},
            {
                "$set": {
                    "status": AgentStatus.READY.value,
                    "error_message": None,
                    "updated_at": time.time(),
                }
            },
        )

        # Notify runners
        event = json.dumps({"action": "start", "agent_id": agent_id})
        await self._nc.publish("system.agents.changed", event.encode())

        updated = await self.agent_configs.find_one({"agent_id": agent_id})
        return AgentConfig.from_mongo(updated).to_public()

    async def _handle_agent_stop(self, data: dict) -> dict:
        """Stop an agent — set status=stopped, notify runners."""
        agent_id = data.get("agent_id")
        if not agent_id:
            raise ValueError("agent_id is required")

        doc = await self.agent_configs.find_one({"agent_id": agent_id})
        if not doc:
            raise ValueError(f"Agent not found: {agent_id}")

        config = AgentConfig.from_mongo(doc)

        if config.status == AgentStatus.STOPPED:
            return config.to_public()  # Already stopped

        await self.agent_configs.update_one(
            {"agent_id": agent_id},
            {
                "$set": {
                    "status": AgentStatus.STOPPED.value,
                    "claimed_by": None,
                    "updated_at": time.time(),
                }
            },
        )

        # Notify runners
        event = json.dumps({"action": "stop", "agent_id": agent_id})
        await self._nc.publish("system.agents.changed", event.encode())

        updated = await self.agent_configs.find_one({"agent_id": agent_id})
        return AgentConfig.from_mongo(updated).to_public()

    # -- Prompt & Archetype Handlers --

    async def _handle_prompt_generate(self, data: dict) -> dict:
        """Generate a system prompt from archetype + personality + strategy."""
        archetype_id = data.get("archetype", "custom")
        display_name = data.get("display_name", "Agent")
        personality = data.get("personality", "")
        strategy = data.get("strategy", "")

        prompt = generate_system_prompt(
            archetype_id=archetype_id,
            display_name=display_name,
            personality=personality,
            strategy=strategy,
        )

        return {"system_prompt": prompt}

    async def _handle_archetypes_list(self, _data: dict) -> list[dict]:
        """List available archetypes."""
        return [archetype_to_dict(a) for a in list_archetypes()]
