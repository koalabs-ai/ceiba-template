-- ceiba-template — base schema (compliance Level 1)
-- Adapt entity to your domain.

PRAGMA foreign_keys = ON;

-- Primary entity table — RENAME / EXTEND for your domain.
CREATE TABLE IF NOT EXISTS entitys (
  id                TEXT PRIMARY KEY,                -- e.g. "ent_abc123"
  slug              TEXT UNIQUE NOT NULL,            -- URL-friendly: kebab-case from name
  name              TEXT NOT NULL,
  description       TEXT,                            -- one-line summary (≤200 chars)
  description_long  TEXT,                            -- bio/long-form (markdown OK)
  image_url         TEXT,                            -- primary image (for cards + detail)
  city              TEXT,                            -- common filter field
  tags              TEXT,                            -- JSON array of strings
  data              TEXT,                            -- JSON blob for flexible domain fields
  source            TEXT NOT NULL,                   -- §4.2: manual|api_sync|scrape|import|community|claim
  source_url        TEXT,
  trust_level       INTEGER NOT NULL DEFAULT 1,      -- §4.2: 1-5
  status            TEXT NOT NULL DEFAULT 'unclaimed', -- §4.1: unclaimed|pending|verified|claimed
  claimed_by        TEXT,                            -- email or phone of owner once claimed
  claimed_at        TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entitys_slug      ON entitys(slug);
CREATE INDEX IF NOT EXISTS idx_entitys_name      ON entitys(name);
CREATE INDEX IF NOT EXISTS idx_entitys_city      ON entitys(city);
CREATE INDEX IF NOT EXISTS idx_entitys_status    ON entitys(status);
CREATE INDEX IF NOT EXISTS idx_entitys_created   ON entitys(created_at DESC);

-- §4.1: claim flow (Level 2 ready)
CREATE TABLE IF NOT EXISTS profile_claim (
  id            TEXT PRIMARY KEY,
  entity_type   TEXT NOT NULL,
  entity_id     TEXT NOT NULL,
  claimant      TEXT NOT NULL,
  evidence      TEXT,
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
  reviewed_by   TEXT,
  reviewed_at   TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_profile_claim_entity ON profile_claim(entity_type, entity_id);

-- §4.3: edit history (Level 1 mandatory; append-only)
CREATE TABLE IF NOT EXISTS edit_history (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type   TEXT NOT NULL,
  entity_id     TEXT NOT NULL,
  field_changes TEXT NOT NULL,                   -- JSON: {"field": ["old", "new"], ...}
  reason        TEXT,
  edited_by     TEXT,
  edited_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_edit_history_entity ON edit_history(entity_type, entity_id, edited_at DESC);

-- §4.4: federation discovery cache (Level 3 prep)
CREATE TABLE IF NOT EXISTS federation_link (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  remote_ceiba  TEXT NOT NULL,                   -- e.g. "cartelera"
  remote_url    TEXT NOT NULL,
  protocol      TEXT NOT NULL,                   -- payment|identity|data|event|cross_listing
  description   TEXT,
  last_synced_at TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fed_remote ON federation_link(remote_ceiba, protocol);

-- §6.5: karma ledger (only used if karma.enabled=true in ceiba.json; spec'd, opt-in)
CREATE TABLE IF NOT EXISTS karma_ledger (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  contributor   TEXT NOT NULL,                   -- pseudo-anon handle
  entity_type   TEXT NOT NULL,
  entity_id     TEXT NOT NULL,
  karma_amount  REAL NOT NULL,                   -- positive = earned, negative = redeemed
  reason        TEXT NOT NULL,                   -- e.g. "edit_validated", "redeemed_to_usdc"
  validated_by  TEXT,
  validated_at  TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_karma_contrib ON karma_ledger(contributor, created_at DESC);
