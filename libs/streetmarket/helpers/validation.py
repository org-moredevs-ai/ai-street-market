"""Message validation utilities."""

from pydantic import ValidationError

from streetmarket.models.envelope import Envelope
from streetmarket.models.messages import PAYLOAD_REGISTRY, MessageType


def validate_message(envelope: Envelope) -> list[str]:
    """Validate an envelope for correctness.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # from_agent must be non-empty
    if not envelope.from_agent or not envelope.from_agent.strip():
        errors.append("'from' field must not be empty")

    # topic must be non-empty
    if not envelope.topic or not envelope.topic.strip():
        errors.append("'topic' field must not be empty")

    # type must be a known MessageType
    try:
        msg_type = MessageType(envelope.type)
    except ValueError:
        errors.append(f"Unknown message type: {envelope.type}")
        return errors

    # payload must match the schema for this message type
    model_class = PAYLOAD_REGISTRY.get(msg_type)
    if model_class is None:
        errors.append(f"No payload schema registered for type: {msg_type}")
        return errors

    try:
        model_class.model_validate(envelope.payload)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            errors.append(f"payload.{loc}: {err['msg']}")

    return errors
