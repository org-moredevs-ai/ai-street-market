"""Agent Runner — loads managed agent configs from MongoDB and runs them.

Lifecycle:
1. On startup: loads all status=ready configs, creates ManagedAgent instances
2. Subscribes to system.agents.changed for real-time start/stop
3. Periodic sync every 30s (catch missed events)
4. Periodic stats flush to MongoDB every 60s
5. Horizontal scaling via claimed_by locking (unique RUNNER_ID per instance)

Each runner instance gets a unique RUNNER_ID. When starting an agent,
it sets claimed_by=RUNNER_ID. Only the claiming runner manages that agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from streetmarket.agent.managed_agent import ManagedAgent, create_managed_agent
from streetmarket.db.connection import get_database
from streetmarket.db.models import AgentConfig, AgentStatus

logger = logging.getLogger(__name__)

# Sync interval: check MongoDB for agents we should be running
SYNC_INTERVAL = 30.0

# Stats flush interval: write runtime stats to MongoDB
STATS_FLUSH_INTERVAL = 60.0


class AgentRunner:
    """Stateful service that loads and runs ManagedAgent instances."""

    def __init__(
        self,
        nats_client: Any,
        *,
        runner_id: str | None = None,
        nats_url: str = "nats://localhost:4222",
    ) -> None:
        self._nc = nats_client
        self._nats_url = nats_url
        self._runner_id = runner_id or f"runner-{uuid.uuid4().hex[:8]}"
        self._db = get_database()
        self._agents: dict[str, ManagedAgent] = {}
        self._agent_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
        self._running = False
        self._sync_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._stats_task: asyncio.Task | None = None  # type: ignore[type-arg]

    @property
    def runner_id(self) -> str:
        return self._runner_id

    @property
    def agent_configs(self):
        return self._db["agent_configs"]

    @property
    def active_agents(self) -> dict[str, ManagedAgent]:
        return dict(self._agents)

    async def start(self) -> None:
        """Start the runner: load agents, subscribe to events, start background tasks."""
        self._running = True
        logger.info("Agent Runner %s starting...", self._runner_id)

        # Subscribe to agent change notifications
        await self._nc.subscribe("system.agents.changed", cb=self._on_agents_changed)

        # Initial load of ready agents
        await self._sync_agents()

        # Start background tasks
        self._sync_task = asyncio.create_task(self._periodic_sync())
        self._stats_task = asyncio.create_task(self._periodic_stats_flush())

        logger.info(
            "Agent Runner %s started — %d agents loaded",
            self._runner_id,
            len(self._agents),
        )

    async def stop(self) -> None:
        """Stop the runner: stop all agents, flush stats, cleanup."""
        self._running = False
        logger.info("Agent Runner %s stopping...", self._runner_id)

        # Cancel background tasks
        for task in (self._sync_task, self._stats_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop all agents
        agent_ids = list(self._agents.keys())
        for agent_id in agent_ids:
            await self._stop_agent(agent_id, set_status=False)

        # Release all claimed agents
        await self.agent_configs.update_many(
            {"claimed_by": self._runner_id},
            {
                "$set": {
                    "status": AgentStatus.STOPPED.value,
                    "claimed_by": None,
                    "updated_at": time.time(),
                }
            },
        )

        logger.info("Agent Runner %s stopped", self._runner_id)

    # -- Agent Lifecycle --

    async def _start_agent(self, config: AgentConfig) -> None:
        """Start a managed agent from config."""
        agent_id = config.agent_id

        if agent_id in self._agents:
            logger.warning("Agent %s already running — skipping", agent_id)
            return

        # Claim the agent (atomic: only succeed if not already claimed)
        result = await self.agent_configs.update_one(
            {
                "agent_id": agent_id,
                "status": {"$in": [AgentStatus.READY.value, AgentStatus.ERROR.value]},
                "$or": [
                    {"claimed_by": None},
                    {"claimed_by": self._runner_id},
                ],
            },
            {
                "$set": {
                    "status": AgentStatus.RUNNING.value,
                    "claimed_by": self._runner_id,
                    "error_message": None,
                    "updated_at": time.time(),
                }
            },
        )

        if result.modified_count == 0:
            logger.debug("Agent %s already claimed by another runner — skipping", agent_id)
            return

        try:
            agent = create_managed_agent(
                agent_id=config.agent_id,
                display_name=config.display_name,
                system_prompt=config.system_prompt,
                tick_interval=config.tick_interval,
                archetype=config.archetype,
                personality=config.personality,
                strategy=config.strategy,
            )

            await agent.connect(self._nats_url)
            await agent.join(
                f"Greetings! I am {config.display_name}, a {config.archetype} ready to trade!"
            )

            self._agents[agent_id] = agent
            self._agent_tasks[agent_id] = asyncio.create_task(self._run_agent(agent_id, agent))

            logger.info("Started agent: %s (%s)", agent_id, config.display_name)

        except Exception as e:
            logger.exception("Failed to start agent %s: %s", agent_id, e)
            await self.agent_configs.update_one(
                {"agent_id": agent_id},
                {
                    "$set": {
                        "status": AgentStatus.ERROR.value,
                        "error_message": str(e),
                        "claimed_by": None,
                        "updated_at": time.time(),
                    }
                },
            )

    async def _run_agent(self, agent_id: str, agent: ManagedAgent) -> None:
        """Run an agent until stopped or errored."""
        try:
            await agent.run()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Agent %s crashed: %s", agent_id, e)
            await self.agent_configs.update_one(
                {"agent_id": agent_id},
                {
                    "$set": {
                        "status": AgentStatus.ERROR.value,
                        "error_message": str(e),
                        "claimed_by": None,
                        "updated_at": time.time(),
                    }
                },
            )

    async def _stop_agent(self, agent_id: str, *, set_status: bool = True) -> None:
        """Stop a running agent."""
        agent = self._agents.pop(agent_id, None)
        task = self._agent_tasks.pop(agent_id, None)

        if agent:
            # Flush final stats
            await self._flush_agent_stats(agent_id, agent)

            agent.stop()
            await agent.disconnect()

        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if set_status:
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

        logger.info("Stopped agent: %s", agent_id)

    # -- Event Handling --

    async def _on_agents_changed(self, msg) -> None:
        """Handle system.agents.changed notifications."""
        try:
            data = json.loads(msg.data.decode())
            action = data.get("action")
            agent_id = data.get("agent_id")

            if not agent_id:
                return

            if action == "start":
                doc = await self.agent_configs.find_one({"agent_id": agent_id})
                if doc:
                    config = AgentConfig.from_mongo(doc)
                    await self._start_agent(config)

            elif action == "stop":
                if agent_id in self._agents:
                    await self._stop_agent(agent_id)

        except Exception:
            logger.exception("Error handling agents.changed event")

    # -- Background Tasks --

    async def _periodic_sync(self) -> None:
        """Periodically sync with MongoDB to catch missed events."""
        while self._running:
            try:
                await asyncio.sleep(SYNC_INTERVAL)
                if self._running:
                    await self._sync_agents()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in periodic sync")

    async def _sync_agents(self) -> None:
        """Sync running agents with MongoDB state."""
        # Find agents that should be running (ready, unclaimed or ours)
        cursor = self.agent_configs.find(
            {
                "status": {"$in": [AgentStatus.READY.value]},
                "$or": [
                    {"claimed_by": None},
                    {"claimed_by": self._runner_id},
                ],
            }
        )

        should_run: set[str] = set()
        async for doc in cursor:
            config = AgentConfig.from_mongo(doc)
            should_run.add(config.agent_id)
            if config.agent_id not in self._agents:
                await self._start_agent(config)

        # Stop agents that should no longer run
        # (Check MongoDB for agents we claim that are now stopped)
        for agent_id in list(self._agents.keys()):
            doc = await self.agent_configs.find_one({"agent_id": agent_id})
            if doc:
                config = AgentConfig.from_mongo(doc)
                if config.status in (AgentStatus.STOPPED, AgentStatus.DRAFT):
                    await self._stop_agent(agent_id)

    async def _periodic_stats_flush(self) -> None:
        """Periodically flush agent stats to MongoDB."""
        while self._running:
            try:
                await asyncio.sleep(STATS_FLUSH_INTERVAL)
                if self._running:
                    await self._flush_all_stats()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in stats flush")

    async def _flush_all_stats(self) -> None:
        """Flush all agent stats to MongoDB."""
        for agent_id, agent in self._agents.items():
            await self._flush_agent_stats(agent_id, agent)

    async def _flush_agent_stats(self, agent_id: str, agent: ManagedAgent) -> None:
        """Flush a single agent's stats to MongoDB."""
        try:
            stats = agent.stats
            await self.agent_configs.update_one(
                {"agent_id": agent_id},
                {
                    "$set": {
                        "stats.ticks_active": stats.ticks_active,
                        "stats.messages_sent": stats.messages_sent,
                        "stats.llm_calls": stats.llm_calls,
                        "stats.last_active_tick": stats.last_active_tick,
                        "updated_at": time.time(),
                    }
                },
            )
        except Exception:
            logger.debug("Failed to flush stats for %s", agent_id)
