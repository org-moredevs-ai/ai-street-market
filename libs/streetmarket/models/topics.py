"""Topic path constants and NATS subject conversion.

v2 topics — simplified "streets" of the market.
The spec uses `/` separators (e.g., `/market/square`),
while NATS uses `.` separators (e.g., `market.square`).
This module handles the conversion transparently.
"""


class Topics:
    """Topic path constants for the v2 protocol."""

    # Market (public — trading agents can read and write)
    SQUARE = "/market/square"
    TRADES = "/market/trades"
    BANK = "/market/bank"
    WEATHER = "/market/weather"
    PROPERTY = "/market/property"
    NEWS = "/market/news"
    THOUGHTS = "/market/thoughts"

    # System (infrastructure only — trading agents cannot access)
    TICK = "/system/tick"
    LEDGER = "/system/ledger"
    REGISTRY = "/system/registry"

    @classmethod
    def agent_inbox(cls, agent_id: str) -> str:
        """Return the inbox topic for a specific agent."""
        return f"/agent/{agent_id}/inbox"

    @classmethod
    def all_market_topics(cls) -> list[str]:
        """Return all public market topic paths."""
        return [
            cls.SQUARE,
            cls.TRADES,
            cls.BANK,
            cls.WEATHER,
            cls.PROPERTY,
            cls.NEWS,
            cls.THOUGHTS,
        ]

    @classmethod
    def all_system_topics(cls) -> list[str]:
        """Return all system topic paths."""
        return [
            cls.TICK,
            cls.LEDGER,
            cls.REGISTRY,
        ]

    @classmethod
    def all_topics(cls) -> list[str]:
        """Return all topic paths."""
        return cls.all_market_topics() + cls.all_system_topics()


def to_nats_subject(topic: str) -> str:
    """Convert a topic path to a NATS subject.

    `/market/square` -> `market.square`
    """
    return topic.lstrip("/").replace("/", ".")


def from_nats_subject(subject: str) -> str:
    """Convert a NATS subject back to a topic path.

    `market.square` -> `/market/square`
    """
    return "/" + subject.replace(".", "/")
