"""Ranking engine — computes season and overall rankings.

Rankings are deterministic — computed from ledger + registry data.
No LLM needed. Metrics and weights come from season config.
"""

from __future__ import annotations

from dataclasses import dataclass

from streetmarket.ledger.interfaces import LedgerInterface
from streetmarket.policy.engine import SeasonConfig
from streetmarket.registry.registry import AgentRecord, AgentRegistry


@dataclass
class RankingEntry:
    """A single agent's ranking in a season."""

    rank: int
    agent_id: str
    owner: str
    scores: dict[str, float]
    total_score: float
    state: str
    death_reason: str = ""


@dataclass
class OverallRankingEntry:
    """A user/owner's overall ranking across seasons."""

    rank: int
    owner: str
    seasons_played: int = 0
    total_score: float = 0.0
    best_season: int = 0
    agents_deployed: int = 0
    wins: int = 0


class RankingEngine:
    """Computes rankings from ledger and registry data.

    Uses scoring metrics and weights from the season config.
    """

    def __init__(
        self,
        config: SeasonConfig,
        ledger: InMemoryLedgerType,
        registry: AgentRegistry,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._registry = registry
        self._season_history: dict[int, list[RankingEntry]] = {}
        self._community_scores: dict[str, float] = {}  # agent_id -> score

    def record_community_contribution(self, agent_id: str, points: float) -> None:
        """Record community contribution points for an agent."""
        self._community_scores[agent_id] = self._community_scores.get(agent_id, 0.0) + points

    async def calculate_rankings(self, tick: int) -> list[RankingEntry]:
        """Calculate current season rankings."""
        agents = await self._registry.list_agents()
        entries: list[RankingEntry] = []

        for agent in agents:
            scores = await self._compute_scores(agent, tick)
            total = self._weighted_total(scores)
            death_reason = ""
            if agent.death:
                death_reason = agent.death.reason

            entries.append(
                RankingEntry(
                    rank=0,  # Set after sorting
                    agent_id=agent.id,
                    owner=agent.owner,
                    scores=scores,
                    total_score=total,
                    state=agent.state.value,
                    death_reason=death_reason,
                )
            )

        # Sort by total score descending
        entries.sort(key=lambda e: e.total_score, reverse=True)
        for i, entry in enumerate(entries):
            entry.rank = i + 1

        # Store for history
        self._season_history[self._config.number] = entries
        return entries

    async def get_season_rankings(self, season: int) -> list[RankingEntry]:
        """Get stored rankings for a season."""
        return self._season_history.get(season, [])

    def get_overall_rankings(self) -> list[OverallRankingEntry]:
        """Compute overall rankings across all recorded seasons."""
        owner_data: dict[str, OverallRankingEntry] = {}

        for season_num, entries in self._season_history.items():
            winner = entries[0] if entries else None
            for entry in entries:
                owner = entry.owner
                if owner not in owner_data:
                    owner_data[owner] = OverallRankingEntry(rank=0, owner=owner)
                od = owner_data[owner]
                od.total_score += entry.total_score
                od.agents_deployed += 1
                od.seasons_played = len(
                    {
                        s
                        for s, es in self._season_history.items()
                        if any(e.owner == owner for e in es)
                    }
                )
                if entry.total_score > owner_data[owner].total_score - entry.total_score:
                    od.best_season = season_num
                if winner and entry.agent_id == winner.agent_id:
                    od.wins += 1

        result = sorted(owner_data.values(), key=lambda o: o.total_score, reverse=True)
        for i, oe in enumerate(result):
            oe.rank = i + 1
        return result

    async def _compute_scores(self, agent: AgentRecord, tick: int) -> dict[str, float]:
        """Compute individual metric scores for an agent."""
        scores: dict[str, float] = {}

        for criterion in self._config.winning_criteria:
            metric = criterion.metric
            if metric == "net_worth":
                scores[metric] = await self._net_worth(agent)
            elif metric == "survival_ticks":
                scores[metric] = self._survival_ticks(agent, tick)
            elif metric == "community_contribution":
                scores[metric] = self._community_scores.get(agent.id, 0.0)
            else:
                scores[metric] = 0.0

        return scores

    async def _net_worth(self, agent: AgentRecord) -> float:
        """Calculate net worth: wallet balance + inventory value."""
        wallet = await self._ledger.get_wallet(agent.id)
        balance = float(wallet.balance) if wallet else 0.0
        # Inventory value — simple count-based for now
        # Phase 2 can add price-based valuation
        inv = await self._ledger.get_inventory(agent.id)
        inv_value = sum(inv.values()) * 1.0  # 1 coin per item baseline
        return balance + inv_value

    def _survival_ticks(self, agent: AgentRecord, current_tick: int) -> float:
        """Calculate survival ticks."""
        if agent.death:
            return float(agent.death.tick - agent.joined_tick)
        return float(current_tick - agent.joined_tick)

    def _weighted_total(self, scores: dict[str, float]) -> float:
        """Compute weighted total score."""
        total = 0.0
        for criterion in self._config.winning_criteria:
            value = scores.get(criterion.metric, 0.0)
            total += value * criterion.weight
        return round(total, 2)


# Type alias for the ledger (accept any object with the right methods)
InMemoryLedgerType = LedgerInterface
