-- Sparring matches belong to the user who asked for them and to one version of one fighter.
-- Matches from before this (imported logs, config fighters) are mode 'sim'.
ALTER TABLE matches
    ADD COLUMN mode text NOT NULL DEFAULT 'sim' CHECK (mode IN ('sim', 'sparring')),
    ADD COLUMN requested_by bigint REFERENCES users (id) ON DELETE SET NULL,
    ADD COLUMN fighter_id bigint REFERENCES fighters (id) ON DELETE SET NULL,
    ADD COLUMN fighter_version integer;

CREATE INDEX matches_fighter_idx ON matches (fighter_id, created_at);
CREATE INDEX matches_requester_idx ON matches (requested_by, created_at);
