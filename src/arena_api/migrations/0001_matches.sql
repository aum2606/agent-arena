-- One row per match. `log` is the whole battle log (schema 2, D-030); the columns beside it are the
-- summary the replay list shows, so listing never has to read the logs.
CREATE TABLE matches (
    id text PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'finished', 'failed')),
    fighter_a text,
    fighter_b text,
    winner text,
    reason text,
    hp_a double precision,
    hp_b double precision,
    turn_count integer,
    log jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    ended_at timestamptz
);

CREATE INDEX matches_status_idx ON matches (status);
