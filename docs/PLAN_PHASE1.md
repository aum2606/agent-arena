# Phase 1 plan (MVP) — DRAFT, not approved

Source: `docs/PRODUCT_SPEC.md` (Phase 1 checklist and architecture). Phase 0 closed without its gate
(D-026). No Phase 1 code exists; nothing below starts until this plan is approved.
Sizes are relative (S = days, M = 1-2 weeks, L = 2+ weeks, part-time), not dates.

## What the spec asks for

Auth, fighter editor with bring-your-own (BYO) API keys, code domain in a gVisor sandbox, Redis
job queue and workers, difficulty scorer (3-model reference panel), PixiJS renderer, replay page
with timeline and reveal panel, ranked matchmaking with Elo, and a launch to a small group.
Out of MVP: live spectating, tournaments, remote agents, 3D avatars, paid plans.
Gate to Phase 2: 20 outside fighters.

## Proposed order (riskiest and cheapest-to-prove first)

The UI comes early because it needs no LLM calls: the replay viewer can be built from the battle
logs we already have (`runs/logs*/`), so free-tier limits do not block it.

| # | Slice | Size | Done when |
|---|---|---|---|
| 1 | **Foundation.** `api/` (FastAPI) and `web/` (Next.js) beside `src/arena/`; Postgres and Redis in `docker compose`; CI running the existing checks plus the new ones. | S | `docker compose up` starts all services; existing 163 tests still pass |
| 2 | **Replay viewer, text first.** Web page that loads a battle log and shows the timeline and the reveal panel (problem, both answers, test result, damage math). No animation yet. | M | A past `sim_*.json` replays in the browser, turn by turn |
| 3 | **Log schema v2.** Add what the viewer needs and the engine lacks (see below). Engine change, with tests. | S | Old logs still load; new logs carry the added fields |
| 4 | **PixiJS renderer.** Animate the events: idle, attack, block, hit, backfire, KO; compress a turn to 3-6 s. | L | A replay plays as an animated fight |
| 5 | **Persistence and workers.** Store matches, turns and problems in Postgres (bodies in object storage); run `run_match` as a Redis-queue worker (Arq). | M | A match queued through the API finishes and appears in the replay list |
| 6 | **Auth, fighters, BYO keys.** GitHub/Google sign-in; fighter editor with versions; keys encrypted at rest, never logged; per-fighter spend cap; Sparring vs a house bot. | L | A new user can enroll a fighter and spar without touching code |
| 7 | **Difficulty scorer.** Reference panel scores each verified problem; difficulty (0.5-2.0) feeds `damage`. Replaces Phase 0's fixed 1.0. | M | Damage varies with difficulty; panel cost per problem is known |
| 8 | **Balance re-check (blocking).** Re-run the 100-match gate with the D-025 retry and the scorer, using BYO or house keys. | S | Neither role above 70% of turns, or rules are changed and logged |
| 9 | **Ranked and Elo.** Matchmaking by rating and class; leaderboard; collusion rule (same-owner fighters never matched). | M | Two fighters are paired and rated automatically |
| 10 | **Code domain and sandbox.** Hidden-test checking in Docker + gVisor; no network, CPU/memory caps, hard timeout. | L | A code-strike turn is verified safely end to end |
| 11 | **Launch hardening.** Moderation filter on problems, rate limits, prompt-injection delimiters, error pages, deploy, invite a small group. | M | A small group runs real fights without operator help |

Slice 8 is a hard gate before slice 9: ranking fighters when one role wins 95% of turns would rank
the rules, not the fighters.

## Why this order

- Slices 2-4 show the product early and cost nothing in API usage.
- Slice 7 attacks the root cause Phase 0 found (problems pitched too easy, nothing tells the
  attacker where the defender's limit is). The spec's own damage formula already has the difficulty
  term; Phase 0 pinned it to 1.0.
- Slice 10 is last because gVisor is Linux-only (needs WSL2 or Docker Desktop on this machine) and it
  is the largest security surface. The math-only MVP is playable without it.

## What the engine needs for the viewer (slice 3)

Gaps between our log and the spec's example (`PRODUCT_SPEC.md`, Battle log event):
- `hp` event uses `a`/`b` keys; the spec uses `A`/`B`. Pick one and log it as a decision.
- No `fx`, `domain`, `problem_id` or `difficulty` on events. Backfired problems are not stored, only
  the failure reason, so the reveal panel cannot show them (add the problem, code and answer).
- `attack_retry` (D-025) is ours, not in the spec's event list; the viewer must render it.
- Persona is hidden in play and shown after the fight, so the log or match record must carry it.
- Spec has `counter`, partial block and energy; Phase 0 has none. Leave out of the MVP unless wanted.

## New dependencies (each needs a DECISIONS entry before use)

FastAPI, SQLAlchemy/Alembic (or similar), Arq, a Postgres driver, an auth library, a crypto library
for key storage; on the web side Next.js, TypeScript, PixiJS. Runtime deps today: openai, sympy,
python-dotenv.

## Risks

- **Free tiers do not scale to ranked play** (the reason Phase 0 stalled). BYO keys move cost to
  users, but house bots, the difficulty panel and balance checks still need model access.
- **Provider terms** may restrict benchmarking or competitive use; check each before adding it.
- **Small-model results do not establish balance for stronger models**, so slice 8 must use the
  models people will actually enroll.
- **Retry unmeasured:** D-025 has never been run live; slice 8 is its first real test.
- **Scope:** the spec estimates weeks 4-10 for a part-time developer; slices 4, 6 and 10 are the big
  ones. Cutting the code domain (slice 10) is the safest way to shorten it.

## Decisions needed from the owner before starting

1. Approve the order above, or move slice 10 (code domain) earlier or out of the MVP.
2. Hosting target (local-only, a VPS, or a managed platform).
3. Sign-in provider: GitHub, Google, or both (spec says both).
4. House-bot and reference-panel models: which providers, and who pays.
5. 2D sprites (spec default) confirmed for the renderer.
6. Repo shape: keep one repo with `api/` and `web/` beside `src/arena/` (proposed), or split.

## Process

Each slice follows `CLAUDE.md`: short plan, tests first, checks, docs, one branch, merge only when
green. `CLAUDE.md` still says "do not build beyond the current phase", so on approval its current
phase becomes 1 and its scope and layout sections are rewritten with a DECISIONS entry.
