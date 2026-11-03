-- A fighter belongs to a user; every edit is a new numbered version (the spec's fighter_versions), so
-- results stay tied to what actually fought. The API key is stored encrypted, never in plain text.
CREATE TABLE fighters (
    id bigserial PRIMARY KEY,
    owner_id bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name text NOT NULL,
    daily_match_cap integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, name)
);

CREATE TABLE fighter_versions (
    id bigserial PRIMARY KEY,
    fighter_id bigint NOT NULL REFERENCES fighters (id) ON DELETE CASCADE,
    version integer NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    persona text NOT NULL,
    api_key_encrypted text NOT NULL,
    key_hint text NOT NULL, -- last four characters, so the owner can tell which key is saved
    verified_at timestamptz, -- set when a sparring match with this version finished
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fighter_id, version)
);
