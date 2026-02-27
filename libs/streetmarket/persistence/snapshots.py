"""State snapshot — serialize and restore all in-memory state.

Enables crash recovery by periodically writing state to disk as JSON.
On restart, the latest snapshot is loaded to resume from where we left off.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from streetmarket.ledger.interfaces import InventoryBatch, InventorySlot, Transaction, Wallet
from streetmarket.ledger.memory import InMemoryLedger
from streetmarket.ranking.engine import RankingEngine
from streetmarket.registry.registry import (
    AgentRecord,
    AgentRegistry,
    AgentState,
    DeathInfo,
    Profile,
)
from streetmarket.season.manager import SeasonManager, SeasonPhase
from streetmarket.world_state.store import (
    Building,
    Field,
    FieldStatus,
    Resource,
    Weather,
    WeatherEffect,
    WorldStateStore,
)

logger = logging.getLogger(__name__)

# Keep this many recent snapshots, delete older ones
MAX_SNAPSHOTS = 3


class _SnapshotEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal, datetime, and enum types."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "value"):  # enum
            return o.value
        return super().default(o)


class StateSnapshot:
    """Serialize and restore all in-memory infrastructure state."""

    @staticmethod
    def save(
        path: str | Path,
        tick: int,
        *,
        ledger: InMemoryLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
        season_manager: SeasonManager,
        ranking_engine: RankingEngine,
    ) -> Path:
        """Save all state to a JSON snapshot file.

        Returns the path to the saved file.
        """
        snapshot_dir = Path(path)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": 1,
            "tick": tick,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "ledger": _serialize_ledger(ledger),
            "registry": _serialize_registry(registry),
            "world_state": _serialize_world_state(world_state),
            "season": _serialize_season(season_manager),
            "ranking": _serialize_ranking(ranking_engine),
        }

        filename = f"snapshot-tick-{tick}.json"
        filepath = snapshot_dir / filename

        filepath.write_text(
            json.dumps(data, cls=_SnapshotEncoder, indent=2),
            encoding="utf-8",
        )
        logger.info("Snapshot saved: %s", filepath)

        # Cleanup old snapshots
        _cleanup_old_snapshots(snapshot_dir)

        return filepath

    @staticmethod
    def find_latest(path: str | Path) -> Path | None:
        """Find the most recent snapshot file in the directory.

        Returns None if no snapshots exist.
        """
        snapshot_dir = Path(path)
        if not snapshot_dir.exists():
            return None

        snapshots = sorted(
            snapshot_dir.glob("snapshot-tick-*.json"),
            key=_extract_tick_from_filename,
        )
        return snapshots[-1] if snapshots else None

    @staticmethod
    def restore(path: str | Path) -> dict[str, Any]:
        """Load a snapshot file and return the raw state dict."""
        filepath = Path(path)
        data = json.loads(filepath.read_text(encoding="utf-8"))
        logger.info("Snapshot loaded: %s (tick %d)", filepath, data.get("tick", -1))
        return data

    @staticmethod
    def apply(
        state: dict[str, Any],
        *,
        ledger: InMemoryLedger,
        registry: AgentRegistry,
        world_state: WorldStateStore,
        season_manager: SeasonManager,
        ranking_engine: RankingEngine,
    ) -> int:
        """Apply a restored snapshot to infrastructure components.

        Returns the tick number from the snapshot.
        """
        _apply_ledger(state.get("ledger", {}), ledger)
        _apply_registry(state.get("registry", {}), registry)
        _apply_world_state(state.get("world_state", {}), world_state)
        _apply_season(state.get("season", {}), season_manager)
        _apply_ranking(state.get("ranking", {}), ranking_engine)

        tick = state.get("tick", 0)
        logger.info("Snapshot applied — restored to tick %d", tick)
        return tick


# -- Serialization helpers --


def _serialize_ledger(ledger: InMemoryLedger) -> dict[str, Any]:
    wallets = {}
    for agent_id, wallet in ledger._wallets.items():
        wallets[agent_id] = asdict(wallet)

    inventory = {}
    for agent_id, slots in ledger._inventory.items():
        inventory[agent_id] = {item: asdict(slot) for item, slot in slots.items()}

    transactions = {}
    for agent_id, txns in ledger._transactions.items():
        transactions[agent_id] = [asdict(t) for t in txns]

    return {
        "wallets": wallets,
        "inventory": inventory,
        "transactions": transactions,
    }


def _serialize_registry(registry: AgentRegistry) -> dict[str, Any]:
    agents = {}
    for agent_id, record in registry._agents.items():
        d = asdict(record)
        # Convert state enum to string (asdict handles this via our encoder)
        d["state"] = record.state.value
        agents[agent_id] = d
    return {"agents": agents}


def _serialize_world_state(world_state: WorldStateStore) -> dict[str, Any]:
    fields = {}
    for fid, f in world_state._fields.items():
        d = asdict(f)
        d["status"] = f.status.value
        fields[fid] = d

    buildings = {bid: asdict(b) for bid, b in world_state._buildings.items()}
    resources = {rid: asdict(r) for rid, r in world_state._resources.items()}
    weather = asdict(world_state._weather)
    properties = dict(world_state._properties)

    return {
        "fields": fields,
        "buildings": buildings,
        "resources": resources,
        "weather": weather,
        "properties": properties,
    }


def _serialize_season(season_manager: SeasonManager) -> dict[str, Any]:
    state = season_manager._state
    return {
        "phase": state.phase.value,
        "current_tick": state.current_tick,
        "announced_at": state.announced_at.isoformat() if state.announced_at else None,
        "preparation_at": state.preparation_at.isoformat() if state.preparation_at else None,
        "opened_at": state.opened_at.isoformat() if state.opened_at else None,
        "closing_at": state.closing_at.isoformat() if state.closing_at else None,
        "ended_at": state.ended_at.isoformat() if state.ended_at else None,
    }


def _serialize_ranking(ranking_engine: RankingEngine) -> dict[str, Any]:
    return {
        "community_scores": dict(ranking_engine._community_scores),
    }


# -- Deserialization / Apply helpers --


def _apply_ledger(data: dict[str, Any], ledger: InMemoryLedger) -> None:
    ledger._wallets.clear()
    ledger._inventory.clear()
    ledger._transactions.clear()

    for agent_id, wd in data.get("wallets", {}).items():
        ledger._wallets[agent_id] = Wallet(
            agent_id=wd["agent_id"],
            balance=Decimal(str(wd["balance"])),
            total_earned=Decimal(str(wd["total_earned"])),
            total_spent=Decimal(str(wd["total_spent"])),
            consecutive_zero_ticks=wd.get("consecutive_zero_ticks", 0),
        )

    for agent_id, slots_data in data.get("inventory", {}).items():
        ledger._inventory[agent_id] = {}
        for item_name, slot_data in slots_data.items():
            batches = [
                InventoryBatch(quantity=b["quantity"], created_tick=b["created_tick"])
                for b in slot_data.get("batches", [])
            ]
            ledger._inventory[agent_id][item_name] = InventorySlot(
                item=slot_data["item"],
                quantity=slot_data["quantity"],
                batches=batches,
            )

    for agent_id, txns_data in data.get("transactions", {}).items():
        ledger._transactions[agent_id] = [
            Transaction(
                id=t["id"],
                tick=t["tick"],
                type=t["type"],
                agent_id=t["agent_id"],
                counterparty=t.get("counterparty", ""),
                item=t.get("item", ""),
                quantity=t.get("quantity", 0),
                amount=Decimal(str(t["amount"])),
                details=t.get("details", {}),
            )
            for t in txns_data
        ]


def _apply_registry(data: dict[str, Any], registry: AgentRegistry) -> None:
    registry._agents.clear()

    for agent_id, ad in data.get("agents", {}).items():
        death = None
        if ad.get("death"):
            dd = ad["death"]
            death = DeathInfo(
                reason=dd["reason"],
                tick=dd["tick"],
                final_message=dd.get("final_message", ""),
                final_score=dd.get("final_score", 0.0),
            )

        profile_data = ad.get("profile", {})
        profile = Profile(
            description=profile_data.get("description", ""),
            capabilities=profile_data.get("capabilities", []),
            objectives=profile_data.get("objectives", ""),
        )

        joined_at = ad.get("joined_at")
        if isinstance(joined_at, str):
            joined_at = datetime.fromisoformat(joined_at)
        elif joined_at is None:
            joined_at = datetime.now(timezone.utc)

        registry._agents[agent_id] = AgentRecord(
            id=ad["id"],
            owner=ad["owner"],
            display_name=ad["display_name"],
            state=AgentState(ad["state"]),
            joined_tick=ad.get("joined_tick", 0),
            joined_at=joined_at,
            profile=profile,
            energy=ad.get("energy", 100.0),
            last_active_tick=ad.get("last_active_tick", 0),
            last_message=ad.get("last_message", ""),
            death=death,
        )


def _apply_world_state(data: dict[str, Any], world_state: WorldStateStore) -> None:
    world_state._fields.clear()
    world_state._buildings.clear()
    world_state._resources.clear()
    world_state._properties.clear()

    for fid, fd in data.get("fields", {}).items():
        world_state._fields[fid] = Field(
            id=fd["id"],
            type=fd["type"],
            location=fd["location"],
            status=FieldStatus(fd["status"]),
            crop=fd.get("crop"),
            planted_tick=fd.get("planted_tick"),
            ready_tick=fd.get("ready_tick"),
            quantity_available=fd.get("quantity_available", 0),
            owner=fd.get("owner"),
            conditions=fd.get("conditions", {}),
        )

    for bid, bd in data.get("buildings", {}).items():
        world_state._buildings[bid] = Building(
            id=bd["id"],
            type=bd["type"],
            owner=bd.get("owner"),
            location=bd.get("location", ""),
            built_tick=bd.get("built_tick", 0),
            condition=bd.get("condition", "good"),
            features=bd.get("features", []),
            occupants=bd.get("occupants", []),
        )

    for rid, rd in data.get("resources", {}).items():
        world_state._resources[rid] = Resource(
            id=rd["id"],
            type=rd["type"],
            location=rd["location"],
            quantity=rd.get("quantity", 0),
            replenish_rate=rd.get("replenish_rate", 0),
            conditions=rd.get("conditions", {}),
        )

    weather_data = data.get("weather")
    if weather_data:
        effects = [
            WeatherEffect(
                type=e["type"],
                target=e["target"],
                modifier=e.get("modifier", 1.0),
                until_tick=e.get("until_tick"),
                reason=e.get("reason", ""),
            )
            for e in weather_data.get("effects", [])
        ]
        world_state._weather = Weather(
            condition=weather_data.get("condition", "sunny"),
            temperature=weather_data.get("temperature", "mild"),
            wind=weather_data.get("wind", "calm"),
            started_tick=weather_data.get("started_tick", 0),
            effects=effects,
            forecast=weather_data.get("forecast", []),
        )

    for pid, pdata in data.get("properties", {}).items():
        world_state._properties[pid] = pdata


def _apply_season(data: dict[str, Any], season_manager: SeasonManager) -> None:
    if not data:
        return

    state = season_manager._state
    state.phase = SeasonPhase(data["phase"])
    state.current_tick = data.get("current_tick", 0)

    for field_name in ("announced_at", "preparation_at", "opened_at", "closing_at", "ended_at"):
        val = data.get(field_name)
        if isinstance(val, str):
            setattr(state, field_name, datetime.fromisoformat(val))
        elif val is None:
            setattr(state, field_name, None)


def _apply_ranking(data: dict[str, Any], ranking_engine: RankingEngine) -> None:
    ranking_engine._community_scores.clear()
    for agent_id, score in data.get("community_scores", {}).items():
        ranking_engine._community_scores[agent_id] = float(score)


# -- File management --


def _extract_tick_from_filename(filepath: Path) -> int:
    """Extract tick number from snapshot filename."""
    match = re.search(r"snapshot-tick-(\d+)\.json", filepath.name)
    return int(match.group(1)) if match else 0


def _cleanup_old_snapshots(snapshot_dir: Path) -> None:
    """Keep only the most recent MAX_SNAPSHOTS files."""
    snapshots = sorted(
        snapshot_dir.glob("snapshot-tick-*.json"),
        key=_extract_tick_from_filename,
    )
    while len(snapshots) > MAX_SNAPSHOTS:
        oldest = snapshots.pop(0)
        oldest.unlink()
        logger.debug("Deleted old snapshot: %s", oldest)
