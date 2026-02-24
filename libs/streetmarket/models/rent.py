"""Rent, bankruptcy, and storage constants for the AI Street Market."""

# Rent: deducted from wallet each tick after grace period
RENT_PER_TICK = 2.0
RENT_GRACE_PERIOD = 20  # ticks before rent starts

# Bankruptcy: declared after N consecutive ticks with zero wallet + zero inventory value
BANKRUPTCY_GRACE_PERIOD = 5  # ticks at zero before bankruptcy

# Storage: limits on total inventory items
STORAGE_BASE_LIMIT = 50  # max items without shelves
STORAGE_PER_SHELF = 10  # extra capacity per shelf consumed
STORAGE_MAX_SHELVES = 3  # max shelves that can boost storage
