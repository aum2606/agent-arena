# Progress

The project is in Phase 1 (MVP). The Phase 0 record comes first, then the Phase 1 slice list.

## Phase 0 (balance prototype)

Gate: over 100+ simulated matches, neither role wins more than 70% of turns.

**Status: CLOSED by owner override on 2026-11-02 without passing the gate (D-026). Best live
result: attacker 16.7% / defender 83.3% of turns (8 matches); 48-match gate run: 3.8% / 96.2%. The
D-025 retry was never measured live. No `v0.1.0-prototype` tag.**

## Phase 1 slices (D-027, details in `docs/PLAN_PHASE1.md`)
- [x] 1 foundation (compose verified: api :8100, web :3100 shows API ok)  - [x] 2 text replay viewer (48 logs listed and replayed in the browser; names and backfired problems wait for slice 3)  - [x] 3 log schema v2 (names, personas, code and attempts in logs; old logs still load)  - [x] 4 PixiJS renderer (drawn shapes; retry, windup, projectile, think, hit, backfire seen live; block, timeout, KO not yet seen)
- [x] 5 persistence + workers (a real match queued through the API finished: first live run with the D-025 retry; 48 gate logs imported)  - [x] 6 auth, fighters, BYO keys (sign-in, versioned fighters, encrypted keys, sparring, pages; a real spar with a real key is untried)  - [x] 7 difficulty scorer (panel of three; one live match: ~4,300 tokens and 3 calls per scored problem, difficulties 0.5 to 1.5; D-036)
- [x] 8 balance re-check (CLOSED: waived by the owner on 2026-11-07, D-042, and the gate retired on 2026-11-14, D-065; history follows; the run continues in the background, 14 matches in `runs/gate4.jsonl`: attacker 31.0% of turns, interval 22.1-41.5%, not a pass): method fixed (D-037), 100-match run restarted with a Groq-only pool (D-039); 22 matches in `runs/gate3.jsonl` showed 33 of 49 backfires were attacker replies cut off at the token cap and 26 of the 32 hits were defenders cut off at their cap (the other 6 finished), so the attacker now retries an unreadable reply (D-040) and the gate restarts in `runs/gate4.jsonl`; the 14 gemini-lite matches in `runs/gate2.jsonl` (attacker 20.2% of turns, 95% interval 13.0-30.0%) are a partial record, stopped by a long Gemini 503 outage  - [x] 9 ranked + Elo (D-043: closest-rating pairing across owners, Elo K 32, leaderboard; no real ranked match has been played yet, only scripted ones in tests)  - [~] 10 code domain + sandbox: 10a sandbox built (D-044, gVisor via docker; the worker now refuses to start without `runsc` unless `ARENA_SANDBOX=off`); checked live on 2026-11-07 in WSL2 Ubuntu 24.04 with gVisor `runsc` (15 sandbox tests pass; probes: network unreachable, disk read-only, no host files, user 65534, 2 GB allocation killed, fork bomb contained, no containers left behind, about 1 s per snippet); run them there with `UV_PROJECT_ENVIRONMENT=~/.venvs/arena uv run pytest tests/test_sandbox.py`, since Windows has no `runsc` and skips them; 10b code strike built (D-045; off unless `code_share` is set; harness checked on real gVisor; two 4-turn live matches on Groq as a spot check: no first draft verified, 4 of 8 attacks backfired, so it stays off; no balance measurement)
- [~] 11 launch hardening: safe answer parsing (D-047), compose worker (D-048), delimited problems and fouls (D-049), rate limits, error pages and headers (D-050) are done and on GitHub with CI green; the self-hosting kit and guide are written (D-072, 2026-11-15); inviting a group is NOT done (no hosted instance: the owner plans a home PC with a tunnel, others run their own)

## Phase 0 checklist
- [x] 0. Bootstrap (git, uv, tooling, pre-commit, docs skeleton)
- [x] 1. models + damage
- [x] 2. verifier
- [x] 3. battle_log
- [x] 4. llm + config
- [x] 5. prompts + parsing
- [x] 6. orchestrator
- [x] 7. cli `match`
- [x] 8. stats + cli `sim`
- [x] 9. live smoke test
- [ ] 10. gate run: not passed; Phase 0 closed without it (D-026), no tag

## Current task
None in progress.

## Next task
Open-source release (D-046): files and CI are written; the first push to GitHub waits for the owner's OK, and the
GitHub settings listed in D-046 are the owner's. Then:
Phase 1 slice 11 (launch hardening), plan approved 2026-11-07: parser fix done (D-047), compose worker fixed (D-048), prompt-injection delimiters and problem filter done (D-049); rate limits, error pages and response headers done (D-050); ranked matches with a silent fighter are void (D-051); answer comparison has a time limit (D-052, D-053); CI has a gVisor job (D-054) that passed on GitHub on 2026-11-08 (commit e69ad57; it fails if a sandbox test is skipped, so the tests really ran under gVisor). Checked on 2026-11-08: a live spot check of 8 math turns on Groq with the new prompts, parser and helper (5 blocks, 2 backfires, 1 cut-off hit; every defender answer parsed and scored right; no false foul), and a browser smoke test of the whole stack with a stub model (two users: sign-in, fighters, spar under gVisor, ranked, -16 rating shown, leaderboard 1216 and 1184, ranked replay private, API-down pages). Not yet: a real ranked match between two real users and real GitHub sign-in. The fighter page now lists its latest ranked matches (`GET /fighters/{id}/ranked`), checked in the browser with three seeded matches. Left in slice 11: deploy files, a runbook and inviting a group, which need a hosting choice (home PC with a tunnel, or a small Linux VPS). Also open: real GitHub sign-in has never been tried; `KEY_ENCRYPTION_SECRET` must be set and backed up; the slice 8 gate run (waived) and a balance measurement of code strikes. Open: the slice 8 gate run (waived, D-042) stopped at 14 of 100 matches and can be resumed.

## Token cut-offs (D-055, 2026-11-12)
In `runs/gate4.jsonl` the token cap decided 27 of 84 turns (16 of 26 hits were cut-off defenders, 11 of 27
backfires were cut-off attackers). Fighters can now set `reasoning_effort`; the gate pool sets `low` for
gpt-oss only. Spot check, 3 real attack calls per setting: gpt-oss default 1 of 3 cut off, `low` 0 of 3;
qwen default 0 of 3, `low` 2 of 3 (so qwen stays at the default). Not measured: the cut-off share over
whole matches with these settings (a 10-match run managed one match in two hours under Groq's 8,000
tokens-per-minute limit and was stopped). qwen: 90 real calls (15 attack + 15 defence at default, `none`, `low`, D-057) found no setting near a 10% cut-off rate (default 3 and 4 of 15, `none` 2 and 4, `low` 13 and 4), so qwen stays at the default; D-058 read its replies: no hidden thinking at all; the cut-offs are visible working-out (attacks 8,700 to 10,600 characters before any tag, defences re-verifying a solved problem), despite prompts that say keep it short. Chosen (D-059): balance runs use `config/gate-mixed.toml`, gpt-oss (`low`) against gemini-lite; in a 12-call test gemini-lite had no cut-offs and 11 of 11 defences correct, gpt-oss-20b failed 8 of 12 attacks with a Groq tool-call 400, and one smoke match on the new pool finished with no cut-offs (Gemini returned 503 nine times and one Gemini defence timed out and counted as a hit). Not measured: how often Gemini's attacks verify, and how hard its problems are. Open: the panel's
cost (about 4,300 tokens per scored problem); pacing requests by tokens instead of waiting out 429s.

## Balance on the mixed pool (D-060, 2026-11-13)
29 matches (174 turns) of `config/gate-mixed.toml`, gpt-oss (`low`) against gemini-lite, no panel: attacker
22.4% of turns (interval 16.9-29.2%), defender 77.6% (70.8-83.1%), so the 70% gate cannot pass; backfires
28.7% of turns (gemini-lite 36% of its attacks, gpt-oss 22%); token cut-offs 1 of 174 turns (27 of 84 before);
1 real defender timeout. The 30th match was rate limited by Groq and the sim stopped (resumable). The
attacker's share matches the D-020 ceiling (about 22-25% with no attacker advantage): the remaining skew
is the rules, not tokens. Options (an attacker bonus, problems pitched near the defender's skill) are the
owner's design decision; the slice 8 gate stays waived.

## gpt-oss-20b tool-call errors (D-061, 2026-11-13)
On Groq, gpt-oss-20b answers 400 `tool_use_failed` on 5 of 8 attacks at the default effort (what web users get;
the 120b: 0 of 8). That used to fail the whole match; now it is an unreadable reply (one retry, then a
backfire). A live match with the 20b on both sides finished, 5 of 6 attacks backfired. The 20b stays a poor
attacker (its OK replies are mostly cut off at the default). Not probed: its defences at the default effort.

## Balance question closed (D-065, 2026-11-14)
The owner approved closing it: the 70%-of-turns gate is retired. The defender wins about 75% of turns with the
rules as they are (the D-020 ceiling); tokens, the unparsed-reply failure and backfires were the fixable parts and
are fixed. Balance is to be judged by whether stronger fighters beat weaker ones once ranked matches exist. Not
built: a panel-based "too easy" retry. Not measured: how often real matches (with the panel's difficulty) end by KO.

## Pre-deploy security work (D-068 to D-071, 2026-11-15)
A read-only audit of the API, the engine and the web side, then a plan the owner approved. Done and on local `main`:
exposure guardrails (dev login and an unsandboxed worker refused on a public `PUBLIC_URL`, a smaller worker environment, non-root
images, no API docs pages; the API image build, broken since the open-source release, fixed); engine integrity (a snippet's exit
code 125 can no longer void a match, output floods capped, a SymPy sandbox image, deep JSON no longer aborts a match, a reference-
panel review on ranked hits that overturns deliberately wrong answers, more moderation); accounts and data (delete a fighter and its
keys, ranked-pool opt-in, a new provider needs a new key, handle clashes, a match stops at its time limit, no internals in errors,
a cross-site write and body-size guard, a bounded connection pool); pins and CI (images by digest, actions by commit, images built
in CI, Dependabot, ignore files). 750 tests pass on Linux with Postgres and gVisor; checked live on the local stack in a browser.
Not yet seen on GitHub: the new CI `images` job and Dependabot. What it left, and the deploy checklist, are in `SECURITY.md`.

## The open items from the security pass, closed (D-082 to D-084, 2026-11-21)
Stored API keys are now sealed to a public key: the API cannot open them, only the worker holds the private key (D-082). GitHub: private
vulnerability reporting, Dependabot alerts and security updates are on, and `main` requires the four CI jobs (D-083). The self-hosting kit was run
for real in WSL (the real worker script, limited database role, sealed keys, a spar under gVisor, a worker restart after `kill -9`, a service
manager), which found the PATH gap in the guide's unit and a Redis port clash, now a setting. Eleven Dependabot updates were taken as one tested
batch (TypeScript 7, setup-uv 10 and others); `python:3.15-slim` and `node:26-alpine` are held (D-084). 29 local branches deleted (all merged).
Not done: the Cloudflare and Tailscale sections (no accounts), the unit as a system unit (no sudo in WSL), compose itself in WSL (no plugin), a
content classifier. CI has not yet run on the batch.

## Security hardening, second pass (D-077 to D-081, 2026-11-18)
An audit of every route, the sign-in and sessions, the prompts and model boundary, the web app, the self-hosting kit and the GitHub settings found the
core guards holding (owner checks, cross-site and size guards, CSP, no HTML sinks, keys never in prompts) and 12 gaps, fixed in four branches: a shared
daily budget for server-paid matches, a per-user ranked cap, a pair limit and a session-check limit (D-077); key-secret rotation, sign out everywhere,
account deletion and a narrower worker environment (D-078); a limited database role with a one-shot migration (D-079); a stricter problem filter with
look-alike letters, the deployer's blocked terms, hidden characters out of logs, dev sign-in refused through tunnels (D-080); a security event log, no
server banner and a threat model (D-081). Checked: 850+ tests on Linux with Postgres and gVisor, and the limited role against a real Postgres (it cannot
create tables or roles, run programs or add extensions). Found and left: the API holds the key secret, so a break-in there could decrypt stored keys.
Not done: content moderation beyond a word list, GitHub repository settings (the owner's).

## A readable web UI (D-073 to D-075, 2026-11-18)
The first walkthrough found bare pages, no explanation of the game, raw match ids and an empty home page on a new install. Redone in
five small branches (owner-approved plan): the dev overlay's grey box fixed (a development-only style policy) with `next` and `vitest`
bumped and CI's audit gate narrowed to production dependencies (D-073); API fields the pages need (`mode` and `ended_at` on replays,
`GET /matches/mine`, rating and record on fighters, provider key links and model suggestions; D-074); a dark arena theme in plain CSS
with shared components, an explained home page and sign-in (D-075); fighter cards, a guided form and a next-step callout; the replay
page as "A vs B" with health bars, a readable reveal panel and a legend, and a styled leaderboard. Checked live on the local stub stack
in the browser: sign-in, create a fighter, spar, a ranked match between two users, the replay, the leaderboard, a 375 px width (no
sideways scroll), and a production build (strict CSP, no inline styles). 773 Python tests pass on Linux; 44 web tests pass.
Not done: component tests, avatars or sprites, a light theme, public ranked replays. The two tunnels in the self-hosting guide are
still untested.

## Self-hosting kit (D-072, 2026-11-15)
The project is open source with no hosted instance, so deployment became a kit for anyone: `docker-compose.prod.yml` (refuses to start without
its secrets, no dev login, Redis password, no container worker), `deploy/run-worker.sh` (the worker on a host with Docker and gVisor, refusing
an unsafe setup) and `docs/SELF_HOSTING.md` (local try-out, public setup, Caddy / Cloudflare Tunnel / Tailscale Funnel, backups, updates,
troubleshooting). Checked in WSL: the override refuses and starts, Redis needs its password, and the guide's header test separates an unsafe
setup (all 200) from a real Caddy in front (59 x 200, 21 x 429). Not checked: the two tunnels (no accounts), the worker script end to end,
the systemd unit. Next: the owner follows the guide on their own PC (Tailscale Funnel), which is also the first real test of the guide.

## A second attack retry (D-062, 2026-11-14)
`attack_retries` (default 1; 2 in `config/gate-mixed.toml`). 28 matches (168 turns): backfires 28.7% -> 12.5%,
verified attacks 71% -> 87.5%, but the attacker's share of turns only 22.4% -> 24.4% (intervals overlap) and the
hit rate of verified attacks fell 31.5% -> 27.9%; draws 1 -> 8 of the matches. The defender's interval is now
68.6-81.5%, so the gate is not ruled out, but 75.6% is above it and the formal gate (100 matches) is waived.
What is left is how hard verified problems are: the owner's design decision.

## Launch hardening, 2026-11-14 (D-063, D-064)
Visitors are rate limited per address on replays, the leaderboard and GitHub sign-in (60 and 20 a minute;
needs `CLIENT_IP_HEADER` behind a proxy that overwrites it; checked through the web server, not through a
real proxy). A nonce-based Content-Security-Policy is on every page (no eval in production; Pixi uses its
eval-free build), checked page by page in a browser on a local production build, not on Firefox/Safari,
HTTPS or the Docker standalone server. Left in slice 11: deploy files, a runbook, inviting a group (need a
hosting choice), content moderation, real GitHub sign-in (checked locally on 2026-11-14, D-067: it works; Cancel on GitHub now returns to
the login page; production needs its own OAuth app and an https PUBLIC_URL), `KEY_ENCRYPTION_SECRET` setup (the API and the worker now refuse to start
without a valid one, D-066).

## Last Phase 0 experiments
Rolling outcome feedback is implemented (D-023). Live trial, 10 matches (`runs/feedback.jsonl`):
attacker 6.7% of turns (4 hits), backfires 48.3% (baseline 3.8% and 26.4%). Per attacker, gemini-lite
backfires 21 of 30, gpt-oss 8 of 30. Matches 6-10 backfire less than 1-5 (11 vs 18 of 30), but 10
matches cannot separate that from noise. The gate is still failing; feedback alone does not fix it.
Defender token budget cut to 2048 (D-024). Live trial (`runs/defender.jsonl`) stopped at 8 of 10
matches when Groq returned 429 after 8 retries: attacker 16.7% of turns (8 hits of 48), backfires
52%. None of the 8 hits was a `timeout`, so the cap never bit; the rise over 6.7% is not caused by
it and 8 hits cannot separate it from noise. Gate still failing.
Backfire diagnosis: 78-83% of backfires are a stated answer that differs from the snippet's output
(the attacker guesses without seeing the snippet run). A failed check now gets one retry that shows
the real result (D-025). Next: a 10-match live trial into `runs/retry.jsonl`; compare backfire rate
(52% before) and count `attack_retry` events that ended verified.

## Blockers
- The rules/prompts as they stand give the defender about 96% of turns. Needs a design change.
- Groq's 8000 tokens-per-minute limit counts prompt + `max_tokens` (4096) per request, so two
  close calls hit it and the sim waits up to 300 s. Lowering `turn_max_tokens` to 2048 was tried and
  rejected (D-019): gpt-oss got cut off in 40% of attacks.
- Infra is slow and flaky on free tiers: Gemini 503s, Groq 429s, connection errors (not
  retried). The last 14 matches took about 4 hours of wall time.
- Only two fighters of unequal strength; the OpenRouter free models tried were unreliable (D-011).

## Latest sim stats
48 matches, 288 turns (`runs/sim.jsonl`, gemini-lite vs gpt-oss-120b, random order):
- Attacker wins 3.8% of turns (11 hits); defender wins 96.2% (201 blocks, 76 backfires).
- Backfire rate 26.4%. Average damage per turn 3.4. Average match length 6.0 turns.
- Endings: 40 decisions, 8 draws, 0 KOs. Match wins: gpt-oss 38, gemini-lite 2, draws 8.
- Per fighter as attacker: gpt-oss 10% backfire, 129 verified attacks (118 blocked, 11 hit);
  gemini-lite 42% backfire, 83 verified attacks (all blocked).
- Per fighter as defender vs verified attacks: gpt-oss blocked 100% (83/83), gemini-lite 91%.
- Defender failures in the logs: 11 wrong answers, 4 timeouts.
- gemini-lite posed only 26 distinct problems in 83 verified attacks; one trivial sum came up 35
  times. gpt-oss posed 126 distinct problems in 129 attacks.

## Scripted-fighter sweep (`arena synth`, D-020)
A model of the rules, not of LLMs (see D-020). Results depend only on skill minus difficulty:
- With no attacker advantage the attacker's best case is about 22-25% of turns (skill equal to
  problem difficulty), so the 70% gate cannot pass however strong the models are.
- When skill exceeds difficulty by 0.2 or more, the attacker wins 0-3% of turns whatever its bonus.
  The live result (3.8%) matches this regime: strong models, problems that are too easy.
- Stronger models alone make it worse (skill 0.9, difficulty 0.5: 2-3%) unless problems get harder
  with skill.
- Correction (D-021): taking the attacker's answer from its snippet looked like the fix but is not.
  `arena synth --compare-rules` shows its extra attacker wins come from broken problems (about half
  the hits at the sweet spot); wins on solvable problems equal the current rule's. Keep backfire on
  mismatch.
- The current rule can pass the gate offline: with attacker bonus 0.1, difficulty near skill gives
  31-33% attacker wins (skill 0.7, difficulty 0.7-0.8; skill 0.9, difficulty 0.9), at the cost of
  30-48% backfires. With no bonus the attacker peaks at about 22%.
- So the lever is difficulty targeting. A closed-loop attacker (D-022) does not converge inside one
  6-turn match (2 feedback events: 3% -> 14% from a start that is too easy), but converges to
  difficulty 0.7-0.8 and passes the gate (29-31%, 35% backfires) if its calibration persists
  across matches.

## Suggested next steps
1. DONE (D-017): attacker variety. Each turn has a random topic and the attacker sees the problems
   already posed. Not yet measured at scale (3 live matches: 13 verified problems, all distinct).
2. DONE (D-018): difficulty prompt (multi-step, no textbook formula, trap, design backwards).
   Untested: the live sim was stopped after 1 match because of Groq rate limits.
3. Change the gate metric (an owner decision): measure verified attacks only, and report results
   per fighter pair, because role effects are confounded with fighter strength.
4. If still above 70%: give the defender a smaller token/time budget than the attacker, or raise
   base damage, or use 12 turns so KOs are possible (D-006, D-013).
5. Infra: retry connection errors, flush CLI output, add a third comparable fighter, and iterate
   with 30-match sims before any 100-match run.

## Notes
- `runs/logs_gate48/` holds the battle logs of the 48 gate-run matches (the new sims reuse the
  `sim_000N` names in `runs/logs/`). `runs/variety.jsonl` has 3 matches from the variety test.
- With backfire at half damage a knockout cannot happen in 6 turns (max 90 damage); every match
  ends by decision or draw (D-013).
- Vulture is `uv run vulture src` and passes.

## First live match with the retry (Phase 1, slice 5 check)
One match queued through `POST /matches`, gemini-lite vs gpt-oss (`m_20261102T130929_0b7d`): 6 attacks
= 2 hits, 3 blocks, 1 backfire (33% / 50% / 17%). 5 of 6 first attempts failed their check and were
retried, 4 of those 5 then verified. Backfires were 48-52% of turns before the retry. One match is
anecdote, not a measurement; the real test is slice 8.
