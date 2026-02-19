"""MarketBusClient — async wrapper around NATS JetStream for AI Street Market."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import nats
from nats.aio.client import Client as NATSClient
from nats.aio.msg import Msg
from nats.js.api import DeliverPolicy
from nats.js.client import JetStreamContext

from streetmarket.models.envelope import Envelope
from streetmarket.models.topics import to_nats_subject

logger = logging.getLogger(__name__)

STREAM_NAME = "STREETMARKET"
STREAM_SUBJECTS = ["world.>", "market.>", "agent.>", "system.>"]


class MarketBusClient:
    """Async NATS client for the AI Street Market message bus.

    Usage:
        client = MarketBusClient("nats://localhost:4222")
        await client.connect()
        await client.publish(Topics.RAW_GOODS, envelope)
        await client.subscribe(Topics.RAW_GOODS, handler)
        await client.close()
    """

    def __init__(self, url: str = "nats://localhost:4222") -> None:
        self._url = url
        self._nc: NATSClient | None = None
        self._js: JetStreamContext | None = None
        self._subscriptions: list[Any] = []

    @property
    def is_connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    async def connect(self) -> None:
        """Connect to NATS and set up the JetStream stream."""
        self._nc = await nats.connect(
            self._url,
            reconnected_cb=self._on_reconnect,
            disconnected_cb=self._on_disconnect,
            error_cb=self._on_error,
            max_reconnect_attempts=10,
            reconnect_time_wait=2,
        )
        self._js = self._nc.jetstream()

        # Create or update the STREETMARKET stream
        try:
            await self._js.find_stream_name_by_subject(STREAM_SUBJECTS[0])
            logger.info("JetStream stream '%s' already exists", STREAM_NAME)
        except Exception:
            await self._js.add_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS,
            )
            logger.info("Created JetStream stream '%s'", STREAM_NAME)

    async def publish(self, topic: str, envelope: Envelope) -> None:
        """Publish an envelope to a topic via JetStream.

        Args:
            topic: Topic path (e.g., `/market/raw-goods`).
            envelope: The message envelope to publish.
        """
        if self._js is None:
            raise RuntimeError("Not connected. Call connect() first.")

        subject = to_nats_subject(topic)
        data = envelope.model_dump_json(by_alias=True).encode()
        await self._js.publish(subject, data)
        logger.debug("Published to %s: %s", subject, envelope.id)

    async def subscribe(
        self,
        topic: str,
        handler: Callable[[Envelope], Coroutine[Any, Any, None]],
        durable: str | None = None,
    ) -> None:
        """Subscribe to a topic. Tries JetStream first, falls back to core NATS.

        Args:
            topic: Topic path (e.g., `/market/raw-goods`).
            handler: Async callback receiving an Envelope.
            durable: Optional durable consumer name for JetStream.
        """
        subject = to_nats_subject(topic)

        async def _msg_handler(msg: Msg) -> None:
            try:
                envelope = Envelope.model_validate_json(msg.data)
                await handler(envelope)
            except Exception:
                logger.exception("Error handling message on %s", subject)
            finally:
                # Auto-ack for JetStream messages
                if msg._ackd is not True:
                    try:
                        await msg.ack()
                    except Exception:
                        pass

        # Try JetStream subscription first
        if self._js is not None:
            try:
                sub = await self._js.subscribe(
                    subject,
                    durable=durable,
                    manual_ack=True,
                    deliver_policy=DeliverPolicy.NEW if durable is None else None,
                )
                self._subscriptions.append(sub)
                # Start consuming in background
                asyncio.ensure_future(self._consume(sub, _msg_handler))
                logger.info("JetStream subscribed to %s", subject)
                return
            except Exception:
                logger.debug("JetStream subscribe failed for %s, falling back to core", subject)

        # Fallback to core NATS
        if self._nc is None:
            raise RuntimeError("Not connected. Call connect() first.")
        sub = await self._nc.subscribe(subject, cb=_msg_handler)
        self._subscriptions.append(sub)
        logger.info("Core NATS subscribed to %s", subject)

    async def _consume(self, sub: Any, handler: Callable[[Msg], Coroutine[Any, Any, None]]) -> None:
        """Consume messages from a JetStream pull/push subscription."""
        try:
            async for msg in sub.messages:
                await handler(msg)
        except Exception:
            logger.debug("Subscription consumer stopped")

    async def close(self) -> None:
        """Unsubscribe from all topics and disconnect."""
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subscriptions.clear()

        if self._nc is not None:
            await self._nc.drain()
            self._nc = None
            self._js = None
        logger.info("Disconnected from NATS")

    async def _on_reconnect(self, _: Any = None) -> None:
        logger.info("Reconnected to NATS at %s", self._url)

    async def _on_disconnect(self, _: Any = None) -> None:
        logger.warning("Disconnected from NATS")

    async def _on_error(self, e: Exception) -> None:
        logger.error("NATS error: %s", e)
