#!/bin/bash
# Runs once, when the database is first created (the postgres image runs everything in
# /docker-entrypoint-initdb.d). Makes the role the API and the worker connect as: it can read and
# write rows and nothing else, so a bug or a break-in in either cannot change the schema, create
# roles or run programs on the database host (D-079). The owner role (POSTGRES_USER) only migrates.
set -euo pipefail
: "${APP_DB_PASSWORD:?set APP_DB_PASSWORD in .env}"

psql -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE arena_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
GRANT CONNECT ON DATABASE arena TO arena_app;
GRANT USAGE ON SCHEMA public TO arena_app;
-- Tables and sequences the owner creates later (the migrations) are covered too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO arena_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO arena_app;
SQL
