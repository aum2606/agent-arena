## What and why

<!-- One thing per PR. Link the issue it closes. -->

## How I checked it

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy src`
- [ ] `uv run vulture src`
- [ ] `uv run pytest` (tests written first; no network calls)
- [ ] `cd web && npm run typecheck && npm test && npm run build` (if the web app changed)

## Rules and docs

- [ ] A rule, number, dependency or layout change has a new entry in `docs/DECISIONS.md`
- [ ] `docs/PROGRESS.md` (and `docs/FLOW.md` if the match flow changed) are updated
- [ ] No keys, tokens or `.env` contents anywhere in the diff

## Not verified

<!-- Be honest: what did you not run or not test? -->
