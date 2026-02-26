"""LLM configuration — loaded from environment, strict per-agent isolation.

ARCHITECTURAL RULE: Every agent is an independent participant. Each agent MUST
have its own API key and model — no shared fallbacks for credentials.

Required per-agent env vars (e.g., for an agent with prefix BAKER):
  - {PREFIX}_API_KEY     — the agent's own LLM API key
  - {PREFIX}_MODEL       — the agent's own model name

Optional per-agent env vars (have safe defaults):
  - {PREFIX}_API_BASE    — defaults to OPENROUTER_API_BASE or openrouter.ai
  - {PREFIX}_MAX_TOKENS  — defaults to 400
  - {PREFIX}_TEMPERATURE — defaults to 0.7

Services (Governor, Banker, Nature, Meteo, etc.) are market infrastructure,
not external agents. They use for_service() which allows shared defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """All LLM configuration for an agent or service.

    Every parameter comes from environment variables.
    Agents are strictly isolated — each must have its own API key and model.
    """

    api_key: str
    api_base: str
    model: str
    max_tokens: int
    temperature: float

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("LLM API key is empty.")
        if not self.model:
            raise ValueError("LLM model is empty.")

    @classmethod
    def for_agent(cls, agent_id: str) -> LLMConfig:
        """Load config for a specific agent from environment.

        STRICT ISOLATION: Each agent must have its own API key and model.
        No shared fallbacks — {PREFIX}_API_KEY and {PREFIX}_MODEL are required.

        The prefix is derived from the agent_id by taking the first segment
        before the first hyphen and uppercasing it (e.g., "baker-hugo" -> "BAKER").

        Raises KeyError if the agent's API key is not set.
        Raises ValueError if the agent's model is not set.
        """
        prefix = agent_id.split("-")[0].upper()

        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        if not api_key:
            raise KeyError(
                f"{prefix}_API_KEY is required. Each agent must have its own "
                f"API key — set {prefix}_API_KEY in your environment."
            )

        model = os.environ.get(f"{prefix}_MODEL", "")
        if not model:
            raise ValueError(
                f"{prefix}_MODEL is required. Each agent must declare its own "
                f"model — set {prefix}_MODEL in your environment."
            )

        api_base = os.environ.get(f"{prefix}_API_BASE", "")
        if not api_base:
            api_base = os.environ.get("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

        return cls(
            api_key=api_key,
            api_base=api_base,
            model=model,
            max_tokens=int(os.environ.get(f"{prefix}_MAX_TOKENS", "400")),
            temperature=float(os.environ.get(f"{prefix}_TEMPERATURE", "0.7")),
        )

    @classmethod
    def for_service(cls, service_name: str) -> LLMConfig:
        """Load config for a market infrastructure service.

        Services (Governor, Banker, Nature, Meteo, etc.) are part of the market,
        not external agents. They may use shared defaults for convenience.
        """
        prefix = service_name.upper().replace("-", "_")

        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        if not api_key:
            api_key = os.environ.get("OPENROUTER_API_KEY", "")

        api_base = os.environ.get(f"{prefix}_API_BASE", "")
        if not api_base:
            api_base = os.environ.get("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")

        model = os.environ.get(f"{prefix}_MODEL", os.environ.get("DEFAULT_MODEL", ""))

        return cls(
            api_key=api_key,
            api_base=api_base,
            model=model,
            max_tokens=int(
                os.environ.get(
                    f"{prefix}_MAX_TOKENS",
                    os.environ.get("DEFAULT_MAX_TOKENS", "400"),
                )
            ),
            temperature=float(
                os.environ.get(
                    f"{prefix}_TEMPERATURE",
                    os.environ.get("DEFAULT_TEMPERATURE", "0.7"),
                )
            ),
        )
