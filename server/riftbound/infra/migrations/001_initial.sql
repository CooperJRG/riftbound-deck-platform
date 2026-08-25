-- Initial schema.
--
-- Every card reference is a card_id (gameplay identity) or a print_id (a specific
-- printing). No table stores a display name as a key.
--
-- user_id exists from the first migration even though local mode has a single
-- implicit user, so adding multi-user hosting later is a configuration change
-- rather than a data migration.

CREATE TABLE users (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE decks (
    deck_id     TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    format      TEXT NOT NULL DEFAULT 'constructed',
    legend_id   TEXT NOT NULL DEFAULT '',
    champion_id TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX idx_decks_user_updated ON decks(user_id, updated_at DESC);

-- One row per (deck, zone, card). Not a JSON blob: v2 stored decks as
-- {"Honest Broker": 3} and could not answer "which decks use this card".
CREATE TABLE deck_cards (
    deck_id TEXT NOT NULL REFERENCES decks(deck_id) ON DELETE CASCADE,
    zone    TEXT NOT NULL CHECK (zone IN ('main', 'runes', 'battlefields', 'sideboard')),
    card_id TEXT NOT NULL,
    qty     INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (deck_id, zone, card_id)
);

CREATE INDEX idx_deck_cards_card ON deck_cards(card_id);

-- Collections track printings, so a player can record owning the Showcase version.
CREATE TABLE collection_items (
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    print_id   TEXT NOT NULL,
    card_id    TEXT NOT NULL,
    qty        INTEGER NOT NULL CHECK (qty >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, print_id)
);

CREATE INDEX idx_collection_card ON collection_items(user_id, card_id);

-- The availability profile: one active profile per user.
CREATE TABLE availability_profiles (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    mode       TEXT NOT NULL DEFAULT 'open'
               CHECK (mode IN ('open', 'collection', 'exclusion')),
    strict     INTEGER NOT NULL DEFAULT 0 CHECK (strict IN (0, 1)),
    penalty    REAL NOT NULL DEFAULT 0.15 CHECK (penalty >= 0.0 AND penalty <= 1.0),
    updated_at TEXT NOT NULL
);

-- Exclusion mode's contents. kind='card' stores a card_id in value; every other
-- kind is a rule ('rarity' -> 'Epic', 'set' -> 'UNL', ...).
CREATE TABLE availability_exclusions (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind    TEXT NOT NULL,
    value   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, kind, value)
);
