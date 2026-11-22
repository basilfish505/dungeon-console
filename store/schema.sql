-- PermaQuest world persistence schema (applied idempotently at boot).

CREATE TABLE IF NOT EXISTS worlds (
    world_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    town_features JSONB NOT NULL DEFAULT '{}'::jsonb,
    battles JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_worlds_is_current ON worlds (is_current) WHERE is_current = TRUE;

ALTER TABLE worlds ADD COLUMN IF NOT EXISTS epoch INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS world_levels (
    world_id TEXT NOT NULL REFERENCES worlds(world_id) ON DELETE CASCADE,
    level_number INTEGER NOT NULL,
    map_data JSONB NOT NULL DEFAULT '[]'::jsonb,
    monsters JSONB NOT NULL DEFAULT '[]'::jsonb,
    turn_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    ground_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (world_id, level_number)
);

CREATE TABLE IF NOT EXISTS characters (
    world_id TEXT NOT NULL REFERENCES worlds(world_id) ON DELETE CASCADE,
    player_id TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'alive',
    death JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (world_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_characters_status ON characters (world_id, status);

ALTER TABLE characters ADD COLUMN IF NOT EXISTS name_key TEXT;
ALTER TABLE characters ADD COLUMN IF NOT EXISTS password_hash TEXT;

-- Case-insensitive unique character names within a world.
CREATE UNIQUE INDEX IF NOT EXISTS idx_characters_name_key
    ON characters (world_id, name_key)
    WHERE name_key IS NOT NULL;

-- Link characters to a durable account that survives world resets.
ALTER TABLE characters ADD COLUMN IF NOT EXISTS account_id TEXT;

-- ----------------------------------------------------------------- PQG economy
-- These tables are intentionally NOT referenced from worlds with ON DELETE
-- CASCADE. A world wipe must never destroy PQG balances.

CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pqg_balances (
    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id) ON DELETE RESTRICT,
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pqg_ledger (
    event_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE RESTRICT,
    amount BIGINT NOT NULL,
    entry_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_instance_id TEXT,
    world_id TEXT,
    character_id TEXT,
    dungeon_level INTEGER,
    monster_type_id TEXT,
    monster_elo DOUBLE PRECISION,
    chest_slot_id TEXT,
    idempotency_key TEXT NOT NULL,
    balance_after BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'committed',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pqg_ledger_idempotency
    ON pqg_ledger (idempotency_key);

CREATE INDEX IF NOT EXISTS idx_pqg_ledger_account_created
    ON pqg_ledger (account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pqg_ledger_source_instance
    ON pqg_ledger (source, source_instance_id);
