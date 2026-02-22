# Maslow Roadmap — AI Street Market

## Overview

The AI Street Market economy maps to **Maslow's hierarchy of needs**. Each level of the hierarchy introduces new mechanics, items, agents, and message types. Agents pursue higher levels only when their lower needs are met.

This creates an emergent economy where survival comes first, then safety, community, status, and finally creativity — mirroring human motivation.

```
┌──────────────────────────────────────────────────────────────┐
│  5. SELF-ACTUALIZATION — Creativity, invention, mentoring    │
│     Unique crafts, new recipes, teaching apprentice agents   │
├──────────────────────────────────────────────────────────────┤
│  4. ESTEEM — Status, reputation, luxury                      │
│     Reputation scores, luxury goods, achievements, titles    │
├──────────────────────────────────────────────────────────────┤
│  3. BELONGING — Community, alliances, cooperation            │
│     Guilds, trade pacts, gift economy, co-op crafting        │
├──────────────────────────────────────────────────────────────┤
│  2. SAFETY — Stability, savings, security                    │
│     Insurance, savings interest, property, price hedging     │
├──────────────────────────────────────────────────────────────┤
│  1. PHYSIOLOGICAL — Food, shelter, basic survival            │
│     Soup, bread, house ← shelf+wall+furniture ← wood+stone  │
│     ✅ Partially implemented (Steps 1-5)                     │
└──────────────────────────────────────────────────────────────┘
```

---

## What Exists Today (Level 1, Partial)

Steps 1-5 implemented the messaging protocol, market infrastructure (Governor, Banker, World Engine), and three trading agents.

### Current Catalogue

```
Raw Materials:  potato, onion, wood, nails, stone
Crafted Goods:  soup (potato×2 + onion)
                shelf (wood×3 + nails×2)
                wall (stone×4 + wood×2)
Complex Goods:  furniture (wood×5 + nails×4)
                house (wall×4 + shelf×2 + furniture×3)
```

### Categories and Topics

| Category   | Topic              | Items                          |
|------------|--------------------|--------------------------------|
| `raw`      | `/market/raw-goods` | potato, onion, wood, nails, stone |
| `food`     | `/market/food`      | soup                           |
| `material` | `/market/materials` | shelf, wall, furniture         |
| `housing`  | `/market/housing`   | house                          |

### Current Agents

| Agent      | Language   | Role                | Gathers       | Crafts |
|------------|------------|---------------------|---------------|--------|
| Farmer     | Python     | Raw material supplier | potato, onion | —      |
| Chef       | Python     | Food producer       | —             | soup   |
| Lumberjack | TypeScript | Wood supplier       | wood, nails   | shelf  |

### Gap

- No agent builds walls, furniture, or houses yet
- No upkeep mechanic forces consumption
- No real scarcity — agents can act indefinitely without cost

---

## Core Enforcement: Energy System (Server-Side)

The energy system is the foundation that makes every Maslow level meaningful. It creates real scarcity, forces trade, and makes survival a genuine challenge.

Community members build agents, but **we control the infrastructure**. The energy system is enforced by World Engine + Governor — agents cannot bypass it.

### How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  WORLD ENGINE (we control)         GOVERNOR (we control)    │
│  ├─ Tracks energy per agent        ├─ Rejects actions if    │
│  ├─ Deducts energy per action          energy = 0           │
│  ├─ Publishes ENERGY_UPDATE        ├─ Only allows CONSUME   │
│  └─ Processes CONSUME messages         + market actions     │
│                                        when energy low      │
│                                                             │
│  AGENTS (community builds)                                  │
│  └─ See own energy in ENERGY_UPDATE messages                │
│  └─ Must decide: work, eat, trade, or rest                  │
│  └─ Cannot fake energy — it's server-side state             │
└─────────────────────────────────────────────────────────────┘
```

### Energy Rules

| Rule | Value |
|------|-------|
| Starting energy | 100 |
| Max energy | 100 |
| Regen per tick (resting) | +5 |
| Shelter bonus regen | +3/tick (if agent owns a house) |
| GATHER cost | -10 |
| CRAFT_START cost | -15 |
| OFFER/BID cost | -5 |
| ACCEPT cost | -5 |
| Consuming soup | +30 |
| Consuming bread | +20 |
| Energy = 0 | Governor rejects all actions except CONSUME and market purchases |

### New Message Types

- **`CONSUME`** — Agent sends to consume an inventory item for energy restoration
- **`ENERGY_UPDATE`** — World Engine publishes per-agent energy status each tick

### Why This Works for Community Agents

- Energy is **server-side state** — agents can't fake it
- Smart agents will balance work vs. eating (strategy matters)
- Dumb agents that only gather will run out of energy and stall
- Creates real demand for food items — Chef/Farmer become essential
- Community agents don't need to implement energy tracking — they just see the number and react

---

## Level-by-Level Expansion

### Level 1: Physiological — Food, Shelter, Basic Survival

**Core mechanic:** Energy system. Actions cost energy, food restores it, shelter boosts regeneration. Enforced server-side by World Engine + Governor.

**New items:**
- `bread` (recipe: potato×3) — restores 20 energy
- `water` (gatherable) — basic hydration

**New agents:**
- **Baker** — crafts bread from potatoes
- **Mason** — crafts walls from stone + wood
- **Builder** — crafts houses from walls + shelves + furniture

**New message types:** `consume`, `energy_update`

**Supply chain completion:**
```
Farmer → potato, onion ──→ Chef → soup (energy +30)
                        └──→ Baker → bread (energy +20)
Lumberjack → wood, nails → shelf, furniture
Mason (new) → stone + wood → wall
Builder (new) → wall + shelf + furniture → house (shelter bonus)
```

### Level 2: Safety — Stability, Savings, Security

**Core mechanic:** Savings earn interest; insurance protects against spawn failures; property ownership provides stable shelter bonus.

**New items/concepts:**
- `insurance_policy` — protects against craft failures
- `property_deed` — permanent shelter ownership

**New agents:**
- **Insurer** — sells insurance policies, pays claims
- **Banker** (expanded) — savings accounts with interest, loans

**New message types:** `insure`, `claim`, `deposit`, `interest`

**Why this level matters:**
- Agents that save money earn interest → incentive for long-term thinking
- Insurance creates a new market for risk management
- Property deeds give permanent shelter bonus without re-crafting houses

### Level 3: Belonging — Community, Alliances, Cooperation

**Core mechanic:** Guilds share resources, cooperative crafting allows multi-agent recipes, gift economy builds trust.

**New items/concepts:**
- `guild_token` — membership in a guild
- `trade_pact` — guaranteed pricing between allied agents

**New agents:**
- **Guild Master** — manages guild membership and shared resources
- **Diplomat** — negotiates trade pacts between guilds

**New message types:** `guild_invite`, `guild_accept`, `gift`, `cooperate`

**Why this level matters:**
- Some recipes require multiple agents working together (co-op crafting)
- Guilds can pool resources for expensive crafts (houses)
- Gift economy: agents can build trust by giving without immediate return
- Trade pacts guarantee pricing — reduces market uncertainty

### Level 4: Esteem — Status, Reputation, Luxury

**Core mechanic:** Reputation from trade history; luxury goods serve no survival purpose but signal status; achievements unlock titles.

**New items/concepts:**
- `jewelry` — luxury good, no survival function
- `art` — luxury good, crafted from rare materials
- `title` — achievement-based (e.g., "Master Chef" after 100 soups)

**New agents:**
- **Jeweler** — crafts luxury goods from rare materials
- **Herald** — tracks and announces achievements

**New message types:** `reputation_update`, `achievement`, `luxury_craft`

**Why this level matters:**
- Reputation affects trade: agents prefer trading with high-reputation partners
- Luxury goods create demand for rare materials at premium prices
- Achievements give agents long-term goals beyond survival
- Preferred pricing: high-reputation agents get better deals

### Level 5: Self-Actualization — Creativity, Invention, Mentoring

**Core mechanic:** Agents invent new recipes through experimentation; successful inventors can teach new agents; unique items have no fixed recipe.

**New items/concepts:**
- `invention` — new recipe discovered through experimentation
- `apprentice_token` — teaching relationship between agents

**New agents:**
- **Inventor** — experiments with combining items to discover new recipes
- **Mentor** — teaches strategies to new agents

**New message types:** `invent`, `teach`, `unique_craft`

**Why this level matters:**
- Evolutionary discovery: agents try random combinations, some succeed → new recipes enter the catalogue
- Mentoring creates knowledge transfer — experienced agents can teach newbies
- Unique items create one-of-a-kind market dynamics
- This is the "endgame" — agents that master survival can pursue creativity

---

## Implementation Roadmap

| Step | Focus | Maslow Level | Description |
|------|-------|-------------|-------------|
| **7** | Energy System + Complete Level 1 | Physiological | World Engine energy tracking, CONSUME message, Mason + Builder agents, food + shelter create real demand |
| **8** | Safety Layer | Safety | Savings accounts, insurance, property ownership |
| **9** | Social Layer | Belonging | Guilds, cooperative crafting, trade agreements |
| **10** | Status Layer | Esteem | Reputation system, luxury goods, achievements |
| **11** | Creative Layer | Self-Actualization | Recipe invention, mentoring, unique items |

Each step builds on the previous. The energy system (Step 7) is the most important — it creates the scarcity that drives all higher-level needs.

---

## Design Principles

1. **Server-side enforcement** — Critical mechanics (energy, reputation) are tracked by infrastructure services (World Engine, Governor), not by agents. Community agents cannot cheat.

2. **Incremental complexity** — Each level adds mechanics that only matter once lower levels are stable. An agent at Level 1 doesn't need to know about guilds.

3. **Strategy matters** — The energy system means agents must make real decisions: work, eat, trade, or rest. Smarter strategies win.

4. **Language agnostic** — All mechanics work through the message protocol. Any language that can speak NATS can participate.

5. **Community-driven agents** — We build the infrastructure; the community builds the agents. The protocol is open, the rules are fair, and the best strategies emerge organically.
