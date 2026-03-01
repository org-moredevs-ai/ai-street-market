"""World state store — the physical reality of the market world.

Tracks fields, buildings, weather, and natural resources.
LLM agents read from this; they write to it through ledger events.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class FieldStatus(str, enum.Enum):
    """Status of a field."""

    EMPTY = "empty"
    PLANTED = "planted"
    GROWING = "growing"
    READY = "ready"
    FLOODED = "flooded"
    DEPLETED = "depleted"


@dataclass
class Field:
    """A plot of land where resources grow."""

    id: str
    type: str  # farmland | quarry | forest | water
    location: str
    status: FieldStatus = FieldStatus.EMPTY
    crop: str | None = None
    planted_tick: int | None = None
    ready_tick: int | None = None
    quantity_available: int = 0
    owner: str | None = None
    conditions: dict[str, str] = field(default_factory=dict)


@dataclass
class Building:
    """A structure in the world."""

    id: str
    type: str  # bakery | house | warehouse | shop | well
    owner: str | None = None
    location: str = ""
    built_tick: int = 0
    condition: str = "good"  # good | worn | damaged | ruined
    features: list[str] = field(default_factory=list)
    occupants: list[str] = field(default_factory=list)


@dataclass
class WeatherEffect:
    """An active weather effect on the world."""

    type: str  # crop_boost | area_blocked | gather_modifier
    target: str
    modifier: float = 1.0
    until_tick: int | None = None
    reason: str = ""


@dataclass
class Weather:
    """Current weather state."""

    condition: str = "sunny"  # sunny | cloudy | rainy | stormy | snowy | foggy
    temperature: str = "mild"  # cold | cool | mild | warm | hot
    temperature_celsius: int | None = None  # numeric °C (LLM-decided)
    wind: str = "calm"  # calm | light | moderate | strong | gale
    started_tick: int = 0
    effects: list[WeatherEffect] = field(default_factory=list)
    forecast: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Resource:
    """A natural resource deposit."""

    id: str
    type: str  # wood | stone | fish | herbs
    location: str
    quantity: int = 0
    replenish_rate: int = 0
    conditions: dict[str, float] = field(default_factory=dict)


class WorldStateStore:
    """In-memory world state store.

    Tracks the physical reality: fields, buildings, weather, resources.
    """

    def __init__(self) -> None:
        self._fields: dict[str, Field] = {}
        self._buildings: dict[str, Building] = {}
        self._resources: dict[str, Resource] = {}
        self._weather = Weather()
        self._properties: dict[str, dict[str, Any]] = {}  # property records

    # --- Fields ---

    async def add_field(self, f: Field) -> None:
        """Add a field to the world."""
        self._fields[f.id] = f

    async def get_field(self, field_id: str) -> Field | None:
        """Get a field by ID."""
        return self._fields.get(field_id)

    async def update_field(self, field_id: str, **kwargs: Any) -> Field:
        """Update field attributes."""
        f = self._fields.get(field_id)
        if f is None:
            raise KeyError(f"Field not found: {field_id}")
        for k, v in kwargs.items():
            if hasattr(f, k):
                setattr(f, k, v)
        return f

    async def list_fields(
        self, status: FieldStatus | None = None, field_type: str | None = None
    ) -> list[Field]:
        """List fields, optionally filtered."""
        result = list(self._fields.values())
        if status is not None:
            result = [f for f in result if f.status == status]
        if field_type is not None:
            result = [f for f in result if f.type == field_type]
        return result

    # --- Buildings ---

    async def add_building(self, b: Building) -> None:
        """Add a building."""
        self._buildings[b.id] = b

    async def get_building(self, building_id: str) -> Building | None:
        """Get a building by ID."""
        return self._buildings.get(building_id)

    async def list_buildings(self, owner: str | None = None) -> list[Building]:
        """List buildings, optionally filtered by owner."""
        result = list(self._buildings.values())
        if owner is not None:
            result = [b for b in result if b.owner == owner]
        return result

    async def update_building(self, building_id: str, **kwargs: Any) -> Building:
        """Update building attributes."""
        b = self._buildings.get(building_id)
        if b is None:
            raise KeyError(f"Building not found: {building_id}")
        for k, v in kwargs.items():
            if hasattr(b, k):
                setattr(b, k, v)
        return b

    # --- Weather ---

    async def get_weather(self) -> Weather:
        """Get current weather."""
        return self._weather

    async def set_weather(self, weather: Weather) -> None:
        """Set weather state."""
        self._weather = weather

    # --- Resources ---

    async def add_resource(self, r: Resource) -> None:
        """Add a natural resource."""
        self._resources[r.id] = r

    async def get_resource(self, resource_id: str) -> Resource | None:
        """Get a resource by ID."""
        return self._resources.get(resource_id)

    async def list_resources(self, resource_type: str | None = None) -> list[Resource]:
        """List resources, optionally filtered by type."""
        result = list(self._resources.values())
        if resource_type is not None:
            result = [r for r in result if r.type == resource_type]
        return result

    async def update_resource(self, resource_id: str, **kwargs: Any) -> Resource:
        """Update resource attributes."""
        r = self._resources.get(resource_id)
        if r is None:
            raise KeyError(f"Resource not found: {resource_id}")
        for k, v in kwargs.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r

    # --- Properties ---

    async def set_property(self, property_id: str, data: dict[str, Any]) -> None:
        """Set a property record."""
        self._properties[property_id] = data

    async def get_property(self, property_id: str) -> dict[str, Any] | None:
        """Get a property record."""
        return self._properties.get(property_id)

    async def list_properties(self, owner: str | None = None) -> list[dict[str, Any]]:
        """List properties, optionally filtered by owner."""
        result = list(self._properties.values())
        if owner is not None:
            result = [p for p in result if p.get("owner") == owner]
        return result
