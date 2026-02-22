/**
 * AgentState — local state mirror for the Lumberjack agent.
 * TypeScript equivalent of Python SDK's AgentState.
 */

export interface CraftingJob {
  recipe: string;
  startedTick: number;
  durationTicks: number;
}

export interface ObservedOffer {
  msgId: string;
  fromAgent: string;
  item: string;
  quantity: number;
  pricePerUnit: number;
  isSell: boolean;
}

export interface AgentState {
  agentId: string;
  joined: boolean;
  wallet: number;
  inventory: Record<string, number>;
  currentTick: number;
  lastHeartbeatTick: number;
  currentSpawnId: string | null;
  currentSpawnItems: Record<string, number>;
  activeCraft: CraftingJob | null;
  observedOffers: ObservedOffer[];
  actionsThisTick: number;
}

export function createInitialState(agentId: string): AgentState {
  return {
    agentId,
    joined: false,
    wallet: 0,
    inventory: {},
    currentTick: 0,
    lastHeartbeatTick: 0,
    currentSpawnId: null,
    currentSpawnItems: {},
    activeCraft: null,
    observedOffers: [],
    actionsThisTick: 0,
  };
}

export function inventoryCount(state: AgentState, item: string): number {
  return state.inventory[item] ?? 0;
}

export function hasItems(
  state: AgentState,
  requirements: Record<string, number>
): boolean {
  return Object.entries(requirements).every(
    ([item, qty]) => inventoryCount(state, item) >= qty
  );
}

export function isCrafting(state: AgentState): boolean {
  return state.activeCraft !== null;
}

export function craftIsDone(job: CraftingJob, currentTick: number): boolean {
  return currentTick >= job.startedTick + job.durationTicks;
}

export function needsHeartbeat(
  state: AgentState,
  interval: number = 5
): boolean {
  return state.currentTick - state.lastHeartbeatTick >= interval;
}

export function remainingActions(
  state: AgentState,
  maxActions: number = 5
): number {
  return Math.max(0, maxActions - state.actionsThisTick);
}

export function advanceTick(state: AgentState, tick: number): void {
  state.currentTick = tick;
  state.actionsThisTick = 0;
  state.observedOffers = [];
}

export function addInventory(
  state: AgentState,
  item: string,
  quantity: number
): void {
  state.inventory[item] = (state.inventory[item] ?? 0) + quantity;
}

export function removeInventory(
  state: AgentState,
  item: string,
  quantity: number
): boolean {
  const current = state.inventory[item] ?? 0;
  if (current < quantity) return false;
  state.inventory[item] = current - quantity;
  if (state.inventory[item] === 0) delete state.inventory[item];
  return true;
}
