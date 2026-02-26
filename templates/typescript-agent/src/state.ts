/**
 * Agent state — local mirror of wallet, inventory, energy.
 */

export interface ObservedOffer {
  msgId: string;
  fromAgent: string;
  item: string;
  quantity: number;
  pricePerUnit: number;
  isSell: boolean;
  tick: number;
}

export interface AgentState {
  agentId: string;
  joined: boolean;
  wallet: number;
  inventory: Record<string, number>;
  energy: number;
  currentTick: number;
  lastHeartbeatTick: number;
  currentSpawnId: string | null;
  currentSpawnItems: Record<string, number>;
  observedOffers: ObservedOffer[];
  actionsThisTick: number;
}

export function createInitialState(agentId: string): AgentState {
  return {
    agentId,
    joined: false,
    wallet: 0,
    inventory: {},
    energy: 100,
    currentTick: 0,
    lastHeartbeatTick: 0,
    currentSpawnId: null,
    currentSpawnItems: {},
    observedOffers: [],
    actionsThisTick: 0,
  };
}

export function inventoryCount(state: AgentState, item: string): number {
  return state.inventory[item] ?? 0;
}

export function needsHeartbeat(state: AgentState, interval = 5): boolean {
  return state.currentTick - state.lastHeartbeatTick >= interval;
}

export function remainingActions(state: AgentState, max = 5): number {
  return Math.max(0, max - state.actionsThisTick);
}

export function advanceTick(state: AgentState, tick: number): void {
  state.currentTick = tick;
  state.actionsThisTick = 0;
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
