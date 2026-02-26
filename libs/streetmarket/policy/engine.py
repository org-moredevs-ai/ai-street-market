"""Policy engine — loads YAML world and season configurations.

Policies define the WORLD, not the rules. LLM agents interpret them.
The engine parses YAML into typed structures for use by the deterministic
layer and for injection into LLM prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WinningCriterion:
    """A single scoring metric with its weight."""

    metric: str
    weight: float
    description: str = ""


@dataclass(frozen=True)
class Award:
    """A season award."""

    name: str
    criteria: str
    description: str = ""


@dataclass(frozen=True)
class CharacterConfig:
    """Configuration for a market agent character."""

    character: str
    personality: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeasonConfig:
    """Parsed season configuration from YAML."""

    name: str
    number: int
    description: str
    starts_at: datetime
    ends_at: datetime
    tick_interval_seconds: int
    world_policy_file: str
    biases: dict[str, Any]
    agent_defaults: dict[str, Any]
    winning_criteria: list[WinningCriterion]
    awards: list[Award]
    closing_percent: int
    preparation_hours: int
    next_season_hint: str
    characters: dict[str, CharacterConfig]

    @property
    def duration_seconds(self) -> float:
        """Total season duration in seconds."""
        return (self.ends_at - self.starts_at).total_seconds()

    @property
    def total_ticks(self) -> int:
        """Total number of ticks in the season."""
        return int(self.duration_seconds / self.tick_interval_seconds)

    @property
    def closing_tick(self) -> int:
        """Tick number when closing phase begins."""
        return int(self.total_ticks * (100 - self.closing_percent) / 100)


@dataclass(frozen=True)
class RegionConfig:
    """A geographic region in the world."""

    name: str
    type: str
    description: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldPolicy:
    """Parsed world policy from YAML."""

    name: str
    era: str
    climate: str
    description: str
    regions: list[RegionConfig]
    resources: dict[str, Any]
    crafting: dict[str, Any]
    energy: dict[str, Any]
    economy: dict[str, Any]
    weather: dict[str, Any]
    social: dict[str, Any]

    @property
    def raw_text(self) -> str:
        """Return the full policy as formatted text for LLM prompt injection."""
        lines = [
            f"# World: {self.name}",
            f"Era: {self.era}, Climate: {self.climate}",
            f"\n{self.description}",
            "\n## Regions",
        ]
        for r in self.regions:
            lines.append(f"- {r.name} ({r.type}): {r.description}")
        return "\n".join(lines)


class PolicyEngine:
    """Loads and parses YAML policy files.

    Usage:
        engine = PolicyEngine("policies/")
        season = engine.load_season("season-1.yaml")
        world = engine.load_world(season.world_policy_file)
    """

    def __init__(self, policy_dir: str | Path) -> None:
        self._dir = Path(policy_dir)

    def load_season(self, filename: str) -> SeasonConfig:
        """Load and parse a season configuration YAML."""
        path = self._dir / filename
        with open(path) as f:
            raw = yaml.safe_load(f)

        s = raw["season"]

        winning = [
            WinningCriterion(
                metric=w["metric"],
                weight=w["weight"],
                description=w.get("description", ""),
            )
            for w in s.get("winning_criteria", [])
        ]

        awards = [
            Award(
                name=a["name"],
                criteria=a["criteria"],
                description=a.get("description", ""),
            )
            for a in s.get("awards", [])
        ]

        characters: dict[str, CharacterConfig] = {}
        for role in ("governor", "nature", "meteo", "town_crier", "landlord", "banker"):
            cfg = raw.get(role)
            if cfg:
                characters[role] = CharacterConfig(
                    character=cfg.get("character", role.title()),
                    personality=cfg.get("personality", ""),
                    extra={k: v for k, v in cfg.items() if k not in ("character", "personality")},
                )

        phases = s.get("phases", {})

        return SeasonConfig(
            name=s["name"],
            number=s["number"],
            description=s.get("description", ""),
            starts_at=_parse_datetime(s["starts_at"]),
            ends_at=_parse_datetime(s["ends_at"]),
            tick_interval_seconds=s["tick_interval_seconds"],
            world_policy_file=s["world_policy"],
            biases=s.get("biases", {}),
            agent_defaults=s.get("agent_defaults", {}),
            winning_criteria=winning,
            awards=awards,
            closing_percent=phases.get(
                "closing_percent", s.get("next_season_announce_percent", 20)
            ),
            preparation_hours=phases.get("preparation_hours", 24),
            next_season_hint=s.get("next_season_hint", ""),
            characters=characters,
        )

    def load_world(self, filename: str) -> WorldPolicy:
        """Load and parse a world policy YAML."""
        path = self._dir / filename
        with open(path) as f:
            raw = yaml.safe_load(f)

        w = raw.get("world", {})
        geo = raw.get("geography", {})

        regions = [
            RegionConfig(
                name=r["name"],
                type=r["type"],
                description=r.get("description", ""),
                extra={k: v for k, v in r.items() if k not in ("name", "type", "description")},
            )
            for r in geo.get("regions", [])
        ]

        return WorldPolicy(
            name=w.get("name", "Unknown World"),
            era=w.get("era", "unknown"),
            climate=w.get("climate", "unknown"),
            description=w.get("description", ""),
            regions=regions,
            resources=raw.get("resources", {}),
            crafting=raw.get("crafting", {}),
            energy=raw.get("energy", {}),
            economy=raw.get("economy", {}),
            weather=raw.get("weather", {}),
            social=raw.get("social", {}),
        )


def _parse_datetime(value: str | datetime) -> datetime:
    """Parse a datetime string or pass through a datetime object."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # Handle ISO format with Z suffix
    if isinstance(value, str):
        value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    raise ValueError(f"Cannot parse datetime: {value!r}")
