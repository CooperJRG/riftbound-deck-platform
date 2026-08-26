-- Smart Decks wizard sessions.
--
-- A session is resumable: the answers a player gives are the expensive part (marking
-- gaps across three decks pins down ~75 cards), so losing them to a closed tab would
-- be the single most annoying failure this feature could have.
--
-- Knowledge is stored one row per card rather than as a JSON blob, for the same reason
-- deck_cards is: "which sessions learned something about this card" has to be
-- answerable, and the opt-in collection write-back is exactly that query.

CREATE TABLE wizard_sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    legend_id  TEXT NOT NULL,
    phase      TEXT NOT NULL DEFAULT 'propose'
               CHECK (phase IN ('propose', 'checklist', 'done')),
    checklists INTEGER NOT NULL DEFAULT 0 CHECK (checklists >= 0),
    -- Set when the player accepts a deck, so a finished session is distinguishable
    -- from one that was abandoned mid-run.
    saved_deck_id TEXT REFERENCES decks(deck_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_wizard_sessions_user ON wizard_sessions(user_id, updated_at DESC);

-- state='exact' is a count we were told; state='at_least' is a lower bound, which is
-- what "I have all of them" actually means. Conflating the two was the defect that
-- capped a player's twelve runes at six and then told them they were one short.
CREATE TABLE wizard_knowledge (
    session_id TEXT NOT NULL REFERENCES wizard_sessions(session_id) ON DELETE CASCADE,
    card_id    TEXT NOT NULL,
    state      TEXT NOT NULL CHECK (state IN ('exact', 'at_least')),
    qty        INTEGER NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (session_id, card_id)
);

CREATE INDEX idx_wizard_knowledge_card ON wizard_knowledge(card_id);

-- The audit trail: what we showed, and what came back. Not needed to resume a session
-- (wizard_knowledge is sufficient) but it is what lets us answer "why did it ask that"
-- when a player says the wizard behaved oddly.
CREATE TABLE wizard_rounds (
    session_id TEXT NOT NULL REFERENCES wizard_sessions(session_id) ON DELETE CASCADE,
    round_no   INTEGER NOT NULL CHECK (round_no > 0),
    kind       TEXT NOT NULL CHECK (kind IN ('deck', 'checklist')),
    deck_id    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, round_no)
);

CREATE TABLE wizard_round_answers (
    session_id TEXT NOT NULL REFERENCES wizard_sessions(session_id) ON DELETE CASCADE,
    round_no   INTEGER NOT NULL,
    card_id    TEXT NOT NULL,
    qty        INTEGER NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (session_id, round_no, card_id)
);
