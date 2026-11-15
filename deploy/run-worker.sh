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

for name in POSTGRES_PASSWORD REDIS_PASSWORD KEY_ENCRYPTION_SECRET PUBLIC_URL; do
  [ -n "${!name:-}" ] || die "$name is not set in $env_file"
done
case "$PUBLIC_URL" in https://*) ;; *) die "PUBLIC_URL must be an https:// address, not '$PUBLIC_URL'" ;; esac
[ "${ARENA_SANDBOX:-gvisor}" = "gvisor" ] || die "ARENA_SANDBOX must not be set to '${ARENA_SANDBOX}' on a public deployment"
docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q runsc \
  || die "Docker has no 'runsc' (gVisor) runtime; see docs/SELF_HOSTING.md"

# The compose file publishes Postgres and Redis on the host's loopback address only.
export DATABASE_URL="${DATABASE_URL:-postgresql://arena:${POSTGRES_PASSWORD}@127.0.0.1:5442/arena}"
export REDIS_URL="${REDIS_URL:-redis://:${REDIS_PASSWORD}@127.0.0.1:6379}"
exec uv run --no-dev arq arena_api.jobs.WorkerSettings
