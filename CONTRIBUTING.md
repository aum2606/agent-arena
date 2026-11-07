# Contributing to Agent Arena

Thanks for helping. This is a small project with strict habits, so please read this page once.

## Ways to help

- **Try it and report what broke** (open an issue with the template).
- **Run experiments.** Rule and balance changes are the heart of the project: pose a hypothesis, run
  `arena sim` or `arena synth`, and share the numbers.
- **Pick up an open item** from [`docs/PROGRESS.md`](docs/PROGRESS.md) or an issue labelled
  `good first issue`. Say you are on it in the issue first, so two people do not build the same thing.
- **Improve docs and tests.**

Before building anything large, open an issue to agree on it. The project builds in small slices
(`docs/PLAN_PHASE1.md`), one at a time, and features from later phases are out of scope until their turn.

## Set up

Python 3.12 and [uv](https://docs.astral.sh/uv/); Node 20+ and Docker for the web app and database tests.

```bash
uv sync
docker compose up -d postgres redis
cd web && npm install
uv run pre-commit install       # runs the checks below on every commit
```

Models run on free tiers only (OpenRouter `:free`, Gemini, Groq). Copy `.env.example` to `.env` and add
your own keys. **Never commit keys**, and never put them in logs, tests or issues.

## The rules we work by

[`CLAUDE.md`](CLAUDE.md) is the source of truth for how the project is built (it is also what our AI
assistants read). The short version:

- **YAGNI and no dead code.** Write only what the current slice needs. No unused code, no commented-out
  code, no speculative abstractions.
- **Tests first,** then the minimum code to pass them. Tests make no network calls.
- **All checks green before you open a PR:**

  ```bash
  uv run ruff check . && uv run ruff format --check .
  uv run mypy src
  uv run vulture src
  uv run pytest
  cd web && npm run typecheck && npm test && npm run build
  ```

- **Python 3.12, full type hints** (mypy is strict on `src/`), dataclasses for domain objects. Game logic
  is pure functions; I/O stays at the edges.
- **Decisions are logged.** A change to a rule, a number, a dependency or the layout needs an entry in
  [`docs/DECISIONS.md`](docs/DECISIONS.md). It is append-only: supersede an old entry, never edit it.
  New dependencies need an entry before you add them.
- **Docs move with the code:** update `docs/PROGRESS.md`, and `docs/FLOW.md` if the match flow changes.
- **Do not silence a linter or type error** without a justification in the decision log.

## Pull requests

1. Fork, then branch from `main`: `feat/…`, `fix/…`, `chore/…`, `docs/…` or `test/…`.
2. Make small, working commits in [Conventional Commits](https://www.conventionalcommits.org/) style, for
   example `feat(verifier): add sympy answer check`.
3. Open a PR against `main` and fill in the template. CI must pass, and a maintainer must review it.
4. Keep the PR to one thing. Say what you ran and what you did **not** verify.

## Security

Do not open a public issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).

## Conduct

Everyone is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

By contributing you agree that your work is released under the project's [MIT license](LICENSE).
