-- Cards the player does not want to play.
--
-- A different claim from anything wizard_knowledge can hold. That table answers "how
-- many of this do you own", and every state in it -- exact, at_least -- is a fact about
-- a collection. "I own this and I do not want to play it" is a fact about a person, and
-- folding it in as `exact 0` would be a lie the app then repeats back: the feasibility
-- line would say the player cannot build a deck they own every card for, and the opt-in
-- collection write-back would record them as not owning cards they do.
--
-- Kept in its own table rather than as a third `state` value because SQLite cannot alter
-- a CHECK constraint without rebuilding the table, and because the two are genuinely
-- separate concerns with separate lifetimes -- a collection fact survives the session,
-- a playstyle preference is about this build.
CREATE TABLE wizard_declined (
    session_id TEXT NOT NULL REFERENCES wizard_sessions(session_id) ON DELETE CASCADE,
    card_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, card_id)
);

CREATE INDEX idx_wizard_declined_card ON wizard_declined(card_id);
