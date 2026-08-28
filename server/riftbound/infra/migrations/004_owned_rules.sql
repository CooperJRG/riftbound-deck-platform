-- Classes of card the player says they *do* have.
--
-- The other half of availability_exclusions, and the half that was missing. Exclusion is
-- the right polarity for somebody who owns nearly everything and is naming their gaps.
-- It is the wrong one for a casual player, who would have to name thousands of cards to
-- say something true about a collection of a few hundred -- and until now the only way
-- to record a collection at all was the wizard's opt-in write-back, which could only
-- ever contain cards some session happened to ask about.
--
-- Its own table rather than a namespaced `kind` in availability_exclusions, because the
-- loader there reads every non-`card` row as an exclusion rule; sharing the table would
-- make one player's "every Common" another query's "no Common". The two are read in
-- different modes and mean opposite things, which is exactly when a separate table is
-- cheaper than a convention everybody has to remember.
CREATE TABLE availability_owned_rules (
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    value      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, value)
);
