"""Energy system constants for the AI Street Market."""

from streetmarket.models.messages import MessageType

STARTING_ENERGY = 100.0
MAX_ENERGY = 100.0
REGEN_PER_TICK = 5.0
SHELTER_BONUS_REGEN = 3.0

# Energy cost per action type. Actions not listed here cost 0.
ACTION_ENERGY_COSTS: dict[str, float] = {
    MessageType.GATHER: 10.0,
    MessageType.CRAFT_START: 15.0,
    MessageType.OFFER: 5.0,
    MessageType.BID: 5.0,
    MessageType.ACCEPT: 5.0,
}

# These actions are always free (even at zero energy):
# consume, join, heartbeat, craft_complete
FREE_AT_ZERO_ENERGY: set[str] = {
    MessageType.CONSUME,
    MessageType.JOIN,
    MessageType.HEARTBEAT,
    MessageType.CRAFT_COMPLETE,
    MessageType.ACCEPT,
}
