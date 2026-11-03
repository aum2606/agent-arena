-- Who can sign in, and their sessions. A session row holds only a hash of the cookie's token.
CREATE TABLE users (
    id bigserial PRIMARY KEY,
    provider text NOT NULL,
    provider_user_id text NOT NULL,
    handle text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_user_id)
);

CREATE TABLE sessions (
    token_hash text PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
