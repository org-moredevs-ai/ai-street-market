"""Topic path constants and NATS subject conversion.

The spec uses `/` separators (e.g., `/market/raw-goods`),
while NATS uses `.` separators (e.g., `market.raw-goods`).
This module handles the conversion transparently.
"""


class Topics:
    """Topic path constants matching the spec."""

    # World
    NATURE = "/world/nature"

    # Market
    SQUARE = "/market/square"
    GOVERNANCE = "/market/governance"
    BANK = "/market/bank"
    RAW_GOODS = "/market/raw-goods"
    FOOD = "/market/food"
    MATERIALS = "/market/materials"
    HOUSING = "/market/housing"
    GENERAL = "/market/general"

    # System
    TICK = "/system/tick"

    @classmethod
    def agent_inbox(cls, agent_id: str) -> str:
        """Return the inbox topic for a specific agent."""
        return f"/agent/{agent_id}/inbox"

    @classmethod
    def all_topics(cls) -> list[str]:
        """Return all static topic paths."""
        return [
            cls.NATURE,
            cls.SQUARE,
            cls.GOVERNANCE,
            cls.BANK,
            cls.RAW_GOODS,
            cls.FOOD,
            cls.MATERIALS,
            cls.HOUSING,
            cls.GENERAL,
            cls.TICK,
        ]


def to_nats_subject(topic: str) -> str:
    """Convert a topic path to a NATS subject.

    `/market/raw-goods` → `market.raw-goods`
    """
    return topic.lstrip("/").replace("/", ".")


def from_nats_subject(subject: str) -> str:
    """Convert a NATS subject back to a topic path.

    `market.raw-goods` → `/market/raw-goods`
    """
    return "/" + subject.replace(".", "/")
