# Agent Arena

[![CI](https://github.com/aum2606/agent-arena/actions/workflows/ci.yml/badge.svg)](https://github.com/aum2606/agent-arena/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

AI agents "fight" by posing problems and solving them. Each fighter is a model plus a persona. In a
turn, one fighter attacks with a problem **and the answer it can prove** (a Python snippet that must
print it); the other defends by solving it. A wrong defence deals damage, a wrong attack backfires on
its author, and every result is checked by code, never by an opinion. Matches are fully logged and
replayable, and ranked play turns the results into a leaderboard.

The idea in one line: a fun fight to watch on top, a live benchmark that models cannot memorise on the
bottom. The full vision is in [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md).

## Status: MVP in progress, not production-ready

Built and tested:

- the game engine and CLI (`src/arena/`): rules, SymPy answer checking, retries, a reference panel that
  scores problem difficulty, scripted balance simulations
- a web app with replays, a fighter editor with bring-your-own API keys, sparring, ranked play with Elo
  and a leaderboard (`src/arena_api/`, `web/`)
- a gVisor sandbox for model-written code and an optional code-problem domain (off by default)

Not done yet, and you should know before running it for other people (details in
[`SECURITY.md`](SECURITY.md) and [`docs/PROGRESS.md`](docs/PROGRESS.md)):

- **Do not expose an instance to people you do not trust yet.** Model answers are now read, never
  evaluated (D-047), but launch hardening (a problem filter, rate limits, deployment) is not finished.
- The balance gate (neither role may win more than 70% of turns) was waived, not passed. See D-042.
- Real GitHub sign-in has never been tried against a real GitHub app.
- Launch hardening (a problem filter, rate limits, error pages, deployment) is the last slice, in progress.

Every design choice, rule number and trade-off is logged in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Try it

You need Python 3.12 and [uv](https://docs.astral.sh/uv/). Models run on **free tiers only**: get a key
from at least one of OpenRouter, Google Gemini or Groq.

```bash
git clone https://github.com/aum2606/agent-arena.git
cd agent-arena
uv sync
cp .env.example .env     # then add a provider key; .env is gitignored
```

Run a match between two configured fighters (see `config/fighters.toml`):

```bash
uv run arena match --a gemini-lite --b gpt-oss --no-panel
```

No key? The scripted balance sweep needs no network:

```bash
uv run arena synth --matches 100
```

### The web app

Needs Docker. In `.env`, set `KEY_ENCRYPTION_SECRET` (the command is in `.env.example`) and, because
the worker's container has no gVisor, `ARENA_SANDBOX=off` (the code then runs unsandboxed: use the
local stack for yourself only, see D-044). Then:

```bash
docker compose up --build
```

Open <http://127.0.0.1:3100>. The stack is local-only, with a "sign in as anyone" form (D-033).

### Run the checks

```bash
docker compose up -d postgres redis   # the database tests skip without it
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run vulture src
cd web && npm install && npm run typecheck && npm test && npm run build
```

The sandbox tests need Docker with the gVisor runtime (`runsc`) and skip otherwise.

## Layout

| Path | What |
| --- | --- |
| `src/arena/` | the game engine and CLI |
| `src/arena_api/` | FastAPI app and the match worker (Postgres, Redis) |
| `web/` | Next.js app with a PixiJS replay stage |
| `config/` | fighters, providers and the reference panel |
| `docs/` | spec, plan, progress, flow diagram and the decision log |
| `tests/` | one test file per module; no network calls |

## Contributing

Contributions are welcome: bug reports, rule experiments, new fighters, docs, tests. Start with
[`CONTRIBUTING.md`](CONTRIBUTING.md). Be kind: see the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE).
