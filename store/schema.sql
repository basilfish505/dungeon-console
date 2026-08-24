-- PermaQuest world persistence schema (applied idempotently at boot).

CREATE TABLE IF NOT EXISTS worlds (
    world_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    town_features JSONB NOT NULL DEFAULT '{}'::jsonb,
    battles JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_worlds_is_current ON worlds (is_current) WHERE is_current = TRUE;

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
