-- Ranked matches pair two users' fighters. The opponent's version and owner are pinned when the match is
-- queued, like the requester's (requested_by, fighter_id, fighter_version); fighter_a is the requester.
ALTER TABLE matches DROP CONSTRAINT matches_mode_check;
ALTER TABLE matches
    ADD CONSTRAINT matches_mode_check CHECK (mode IN ('sim', 'sparring', 'ranked')),
    ADD COLUMN opponent_id bigint REFERENCES fighters (id) ON DELETE SET NULL,
    ADD COLUMN opponent_version integer,
    ADD COLUMN opponent_owner bigint REFERENCES users (id) ON DELETE SET NULL,
    ADD COLUMN rating_delta_a double precision; -- how fighter A's rating moved; B's moved by the opposite

CREATE INDEX matches_opponent_idx ON matches (opponent_id, created_at);

-- One rating per fighter (not per version), created by its first ranked game.
CREATE TABLE ratings (
    fighter_id bigint PRIMARY KEY REFERENCES fighters (id) ON DELETE CASCADE,
    rating double precision NOT NULL,
    games integer NOT NULL DEFAULT 0,
    wins integer NOT NULL DEFAULT 0,
    draws integer NOT NULL DEFAULT 0,
    losses integer NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ratings_rating_idx ON ratings (rating DESC);
