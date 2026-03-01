"""Prompt generator — builds system prompts from archetype + personality + strategy.

Generates the system prompt that a ManagedAgent uses for LLM reasoning.
"""

from __future__ import annotations

from services.agent_manager.archetypes import get_archetype


def generate_system_prompt(
    *,
    archetype_id: str,
    display_name: str,
    personality: str = "",
    strategy: str = "",
) -> str:
    """Generate a system prompt for a managed agent.

    Args:
        archetype_id: The archetype ID (e.g., "baker", "farmer", "custom").
        display_name: The agent's display name.
        personality: User-defined personality traits.
        strategy: User-defined trading strategy.

    Returns:
        Complete system prompt string for LLM reasoning.
    """
    archetype = get_archetype(archetype_id)

    # Base role
    if archetype and archetype_id != "custom":
        role = archetype.role_description
    else:
        role = (
            "You are a participant in a medieval market economy. "
            "You trade goods, interact with other agents, and try to prosper."
        )

    # Personality
    effective_personality = personality
    if not effective_personality and archetype:
        effective_personality = archetype.default_personality

    # Strategy
    effective_strategy = strategy
    if not effective_strategy and archetype:
        effective_strategy = archetype.default_strategy

    # Specialization hints
    hints_text = ""
    if archetype and archetype.specialization_hints:
        items = ", ".join(archetype.specialization_hints)
        hints_text = f"\nYour specializations: {items}."

    parts = [
        f"Your name is {display_name}.",
        "",
        role,
        hints_text,
    ]

    if effective_personality:
        parts.extend(["", f"Personality: {effective_personality}"])

    if effective_strategy:
        parts.extend(["", f"Strategy: {effective_strategy}"])

    parts.extend(
        [
            "",
            "RULES:",
            "- Communicate in natural language only.",
            "- You can: offer (sell), bid (buy), say (chat), think (share reasoning), or rest.",
            "- Watch market messages to understand prices and opportunities.",
            "- Manage your coins wisely — don't overspend.",
            "- Respond with a JSON decision:",
            '  {"action": "offer|bid|say|think|rest", "topic": "/market/trades", '
            '"message": "...", "item": "...", "quantity": 1, "price": 10.0}',
        ]
    )

    return "\n".join(parts)
