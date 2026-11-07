# CLAUDE.md — Agent Arena

Read this file at the start of every session. It is the source of truth for how we work.
If anything here conflicts with a request, ask before acting.

## What we're building
Agent Arena: AI agents "fight" by posing problems (attacks) and solving them (defenses).
Full product vision: `docs/PRODUCT_SPEC.md`. **Do not build beyond the current phase.**

## Current phase: 1 — MVP (plan: `docs/PLAN_PHASE1.md`)
Phase 0 (balance prototype) was closed without its gate (D-026); the engine in `src/arena/` is the base.
- Slice order approved 2026-11-02 (D-027): 11 slices, one at a time. Do not start a later slice.
- In scope: only the current slice, after its short plan is approved (see Workflow).
- Out of MVP scope: live spectating, tournaments, remote agents, 3D avatars, paid plans.
- Slice 8 (100-match balance re-check) was waived by the owner on 2026-11-07 (D-042); slice 9 is built.
- New dependencies need a DECISIONS entry first. "Runtime deps today" below is the engine's.

## Game rules (Phase 0)
- 2 fighters, 100 HP each. Fighter = {name, provider, model, persona} from `config/fighters.toml`.
- Attacker returns: math problem + its answer + a Python snippet that computes the answer.
- Self-verify: run the snippet (subprocess, timeout, temp dir). Output ≠ stated answer, error,
  or timeout → one retry that shows the attacker the real result (D-025). A reply with no usable
  problem/answer/code tags (often one cut off at the token cap) gets that same single retry (D-040).
  Failing again → **backfire**: attacker takes half the damage (D-013).
- Defender answers within time/token budget. Checked with SymPy equality. score = 1 or 0.
- `damage = base × difficulty × (1 − score)`, base = 20. Difficulty is 0.5 to 2.0 from the reference panel
  (`[[panel]]` in `config/fighters.toml`; the share of members that fail the problem, D-036), or 1.0 when no
  panel is used (backfires, sparring, `--no-panel`).
- Code strike (D-045): with `code_share` > 0 (default 0) a turn can be a code problem instead: the attacker gives a
  `solve` problem, a reference solution, hidden test inputs and expected outputs (JSON); the reference must print the
  stated outputs (same retry and backfire); the defender's function must pass every hidden test to score 1. The
  panel scores math only (code difficulty is 1.0).
- Roles swap each turn. End: HP ≤ 0 (KO) or after 6 rounds (higher HP wins).
- Battle log events: attack_start, attack_retry, attack_verified, difficulty, backfire, defend_start, defend_result,
  hit, block, timeout, hp, knockout, match_end. Each has `t` (ms since turn start); an `attack_retry` for an unreadable reply carries `reason` and `truncated` (D-040); a defender's `defend_result` and
  cut-off `timeout` carry `output_tokens` (D-037). The log has a
  header (`schema: 2`, `fighters`); verified, retried and backfired attacks carry problem, answer, code (D-030), and for code strikes `domain` and `tests` (D-045).
- Sparring (D-035): a user's fighter vs the `house_bot` from `config/fighters.toml`, 3 turns, with the user's
  own key for their side; the engine's `run_match(max_turns=...)` takes the length.
- Rule or number changes must be logged in `docs/DECISIONS.md`.

## Commands
```bash
uv sync                                   # install deps
uv run arena match --a <fighter> --b <fighter>   # add --no-panel to skip difficulty scoring (D-036)
uv run arena sim --n 100                  # resumable; appends to runs/*.jsonl; --no-panel too; waits out
                                          # an overloaded provider and replays the match (D-038)
uv run arena synth --matches 100          # balance sweep with scripted fighters, no network (D-020)
uv run arena synth --compare-rules        # answer-rule comparison by difficulty (D-021)
uv run arena synth --adaptive             # closed-loop attacker by step and start (D-022)
docker compose up -d postgres redis      # needed by the database tests, which skip without it
export DATABASE_URL=postgresql://arena:arena-dev@127.0.0.1:5442/arena   # local-only default (D-028)
uv run uvicorn arena_api.app:app --reload # API on :8000 (D-028); POST /fighters/{id}/spar queues a spar
uv run arq arena_api.jobs.WorkerSettings  # the match worker; needs the provider keys in the environment, and
                                          # Docker with gVisor (runsc) unless ARENA_SANDBOX=off (D-044)
uv run python -m arena_api.import_logs runs/logs_gate48 --prefix gate48-   # load old logs (D-032)
cd web && npm install && npm run dev      # web app on :3000; `npm run typecheck`, `npm test`, `npm run build`
docker compose up --build                 # postgres :5442, redis, api :8100, web :3100 (localhost)
uv run pytest                             # tests
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run vulture src
uv run pre-commit run --all-files         # everything above that runs on commit
```
Update this section if commands change.

## Layout (planned — adjust only with a DECISIONS entry)
```
src/arena/      models.py  llm.py  prompts.py  verifier.py  sandbox.py  codestrike.py  damage.py
                orchestrator.py  battle_log.py  stats.py  scorer.py  cli.py   (the game engine)
src/arena_api/  app.py auth.py accounts.py fighters.py fighter_routes.py match_routes.py secret_box.py replays.py store.py ratings.py ranked_routes.py db.py jobs.py import_logs.py migrations/   (FastAPI + worker; Phase 1)
web/            Next.js + TypeScript app (Phase 1); lib/choreography.ts plans a turn's animation, lib/stage.ts draws it (Pixi)
docker/         api.Dockerfile  web.Dockerfile      docker-compose.yml at the root
tests/          one test file per module, no network calls
config/         fighters.toml
docs/           PRODUCT_SPEC.md  DECISIONS.md  PROGRESS.md  FLOW.md
runs/           match logs + sim results (gitignored)
```

## Models: free tiers only
- Providers: OpenRouter (`:free` models), Google Gemini API, Groq.
- One client: the `openai` SDK with per-provider `base_url` + key. No LiteLLM or wrappers.
- Model IDs live only in `config/fighters.toml`; check provider docs for current free models.
- Handle 429s with exponential backoff + jitter, a configurable delay between calls, and a
  max-retry limit. Never retry forever.
- Keys in `.env` (gitignored); `.env.example` lists names only. Never log or print keys.

## Code standards (non-negotiable)
- **YAGNI:** write only what the current phase needs. No speculative abstractions, single-child
  base classes, plugin systems, unused params, or "for later" code.
- **No dead code:** no unused imports/functions/variables, commented-out code, or duplicated
  logic. ruff, mypy, vulture and pytest must all pass before every commit.
- One responsibility per module. Game logic (damage, scoring, turn rules) = pure functions.
  I/O (LLM calls, subprocess, files) stays at the edges.
- Python 3.12, full type hints, dataclasses for domain objects, mypy strict on `src/`.
- `logging` for diagnostics; `print` only for CLI output.
- Errors handled at boundaries with clear messages. Never swallow exceptions.
- Comments explain *why*, not *what*. Short docstrings on public functions only.
- New dependency → justify in DECISIONS.md first. Runtime deps today: openai, sympy, python-dotenv.
- Running model-written code: the CLI uses a subprocess + hard timeout + temp dir + minimal env. That is
  NOT a secure sandbox; don't present it as one. The web worker runs it in gVisor (D-044, `ARENA_SANDBOX`).

## Tracking docs (update in the same commit as the code)
- `docs/DECISIONS.md`: append-only. `## D-NNN · YYYY-MM-DD · Title` → Decision, Why,
  Alternatives considered, (Supersedes D-xxx). Never edit old entries; supersede them.
- `docs/PROGRESS.md`: phase checklist, current task, next task, blockers, latest sim stats.
  Update after every task.
- `docs/FLOW.md`: Mermaid sequence diagram of a match through the modules + one line per
  module. Update whenever the flow changes.

## Git
- Default branch `main`. One short-lived branch per task: `feat/…`, `fix/…`, `chore/…`,
  `docs/…`, `test/…`. Merge to main only when all checks pass.
- Conventional Commits, small and working: `feat(verifier): add sympy answer check`.
- Never commit `.env`, keys, `runs/`, caches or virtualenvs.
- Tag phase gates (`v0.1.0-prototype`). **Ask before pushing** or rewriting history.

## Workflow for every task
1. State the task and a short plan (files touched, tests to add). Wait for OK on anything non-trivial.
2. Write or adjust tests first, then implement the minimum to pass.
3. Run all checks (ruff, mypy, vulture, pytest). Fix, don't suppress.
4. Update PROGRESS.md (+ DECISIONS.md / FLOW.md if relevant).
5. Commit, then give a 3-line summary: what changed, check results, what's next. Wait for "next".

## Never
- Build features from later phases or add "nice to have" extras.
- Hardcode model IDs, keys, or magic numbers outside config/constants.
- Silence linters or type errors with ignores unless justified in DECISIONS.md.
- Guess at unclear rules. Ask.
