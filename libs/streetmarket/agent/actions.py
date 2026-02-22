"""Action model — decouples strategy decisions from I/O execution."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActionKind(StrEnum):
    """All action types an agent strategy can emit."""

    GATHER = "gather"
    OFFER = "offer"
    BID = "bid"
    ACCEPT = "accept"
    CRAFT_START = "craft_start"
    CRAFT_COMPLETE = "craft_complete"
    HEARTBEAT = "heartbeat"
    JOIN = "join"


@dataclass(frozen=True)
class Action:
    """A single action returned by a strategy's decide() function.

    The strategy returns a list of Actions; the base class executes them.
    """

    kind: ActionKind
    params: dict[str, Any] = field(default_factory=dict)
