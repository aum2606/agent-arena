#!/usr/bin/env bash
# Runs the match worker on this host, next to Docker and gVisor (D-072). Model-written code runs in the
# sandbox; this script refuses to start without it. It reads ENV_FILE (default: .env in the repository).
set -euo pipefail
cd "$(dirname "$0")/.."

die() { echo "run-worker: $*" >&2; exit 1; }

env_file="${ENV_FILE:-.env}"
[ -f "$env_file" ] || die "$env_file not found (copy .env.example and fill it in)"
# A file edited on Windows has carriage returns that end up inside the values.
if grep -q $'\r' "$env_file"; then die "$env_file has Windows line endings; save it with Unix (LF) line endings"; fi

set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

for name in APP_DB_PASSWORD REDIS_PASSWORD KEY_PRIVATE_KEY PUBLIC_URL; do
  [ -n "${!name:-}" ] || die "$name is not set in $env_file"
done
case "$PUBLIC_URL" in https://*) ;; *) die "PUBLIC_URL must be an https:// address, not '$PUBLIC_URL'" ;; esac
[ "${ARENA_SANDBOX:-gvisor}" = "gvisor" ] || die "ARENA_SANDBOX must not be set to '${ARENA_SANDBOX}' on a public deployment"
docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q runsc \
  || die "Docker has no 'runsc' (gVisor) runtime; see docs/SELF_HOSTING.md"

# The compose file publishes Postgres and Redis on the host's loopback address only.
# The limited role, never the owner (D-079); the compose stack migrated the database already.
export DATABASE_URL="${DATABASE_URL:-postgresql://arena_app:${APP_DB_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT:-5442}/arena}"
export ARENA_AUTO_MIGRATE=0
export REDIS_URL="${REDIS_URL:-redis://:${REDIS_PASSWORD}@127.0.0.1:${REDIS_HOST_PORT:-6379}}"
# Only what the worker needs, not the whole env file: the GitHub client secret has no business here,
# and model-written code is a neighbour of this process (D-068, D-078).
pass=()
for name in PATH HOME USER LANG LC_ALL TMPDIR XDG_CACHE_HOME UV_PROJECT_ENVIRONMENT UV_CACHE_DIR \
  DOCKER_HOST DOCKER_CONFIG DATABASE_URL ARENA_AUTO_MIGRATE REDIS_URL KEY_PRIVATE_KEY \
  KEY_OLD_PRIVATE_KEYS KEY_ENCRYPTION_SECRET KEY_ENCRYPTION_OLD_SECRETS PUBLIC_URL \
  FIGHTERS_CONFIG ARENA_DB_POOL OPENROUTER_API_KEY GEMINI_API_KEY GROQ_API_KEY; do
  if [ -n "${!name+x}" ]; then pass+=("$name=${!name}"); fi
done
exec env -i "${pass[@]}" uv run --no-dev arq arena_api.jobs.WorkerSettings
