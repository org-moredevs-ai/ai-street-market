"""LLM configuration — loaded from environment, zero hardcoded values."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """All LLM configuration for an agent or service.

    Every parameter comes from environment variables. Nothing is hardcoded.
    """

    api_key: str
    api_base: str
    model: str
    max_tokens: int
    temperature: float

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError(
                "LLM model is empty. Set DEFAULT_MODEL or a per-agent "
                "model env var (e.g. FARMER_MODEL)."
            )

    @classmethod
    def for_agent(cls, agent_id: str) -> LLMConfig:
        """Load config for a specific agent from environment.

        Looks for per-agent overrides first (e.g. FARMER_MODEL), then
        falls back to DEFAULT_* values.
        """
        prefix = agent_id.split("-")[0].upper()
        return cls(
            api_key=os.environ["OPENROUTER_API_KEY"],
            api_base=os.environ.get(
                "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"
            ),
            model=os.environ.get(
                f"{prefix}_MODEL", os.environ.get("DEFAULT_MODEL", "")
            ),
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

    @classmethod
    def for_service(cls, service_name: str) -> LLMConfig:
        """Load config for a service (town_crier, world, etc.)."""
        prefix = service_name.upper().replace("-", "_")
        return cls(
            api_key=os.environ["OPENROUTER_API_KEY"],
            api_base=os.environ.get(
                "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"
            ),
            model=os.environ.get(
                f"{prefix}_MODEL", os.environ.get("DEFAULT_MODEL", "")
            ),
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
