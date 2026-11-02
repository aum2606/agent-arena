# Decisions

Append-only. Never edit an old entry; add a new one that supersedes it.

## D-001 · 2026-10-30 · Tooling and project setup

**Decision:** `uv` project with `uv_build` backend and `src/arena` layout, Python pinned to 3.12
(`requires-python = ">=3.12,<3.13"`). Dev tools: pytest, ruff (E, F, I, UP, B, SIM), mypy
strict on `src/`, vulture, pre-commit. Pre-commit uses `local` hooks that call `uv run`, so
tool versions come from the lockfile rather than a second pinned set. Runtime deps: openai,
sympy, python-dotenv.

**Why:** The machine has Python 3.14; the project standard is 3.12, so it is pinned. Local
hooks avoid version drift between pre-commit and `uv.lock`. A real build backend is needed for
the `arena` console script.

**Alternatives considered:** hatchling (extra tool for no gain), `pre-commit` remote repos
(duplicate version pins), no build backend with `python -m arena` (worse CLI ergonomics).

## D-002 · 2026-10-30 · Running model-written code is not a secure sandbox

**Decision:** Attacker snippets run in a subprocess with a hard timeout, a fresh temp dir and
a minimal environment. This is NOT a secure sandbox: the snippet can still read the user's
files and use the network. Real isolation (containers) is Phase 1. Defender answers are parsed
with SymPy, whose parser evaluates text; that risk is accepted in Phase 0 for the same reason.

**Why:** Phase 0 only needs to prove the rules are balanced; Docker is out of scope.

**Alternatives considered:** Docker or a restricted interpreter now (out of Phase 0 scope).

## D-003 · 2026-10-30 · Rule clarifications for Phase 0

**Decision:**
- Malformed attacker output (unparseable, or missing problem, answer or snippet) is a backfire.
- Defender exceeding the time or token budget logs `timeout`, scores 0 and takes a hit.
- If a provider call still fails after the retry limit, the match is aborted and left to resume;
  it is never scored.
- A turn is won by the attacker when a hit lands; it is won by the defender on a block or a
  backfire. The 70% gate is measured over these per-turn outcomes.
- Equal HP after round 6 is a draw and counts for neither side.
- The attacker's stated answer vs its snippet output, and the defender's answer vs the stated
  answer, are both compared with SymPy equality.

**Why:** The brief left these open; each is the simplest reading consistent with the rules.

**Alternatives considered:** scoring provider failures as a loss (would skew the balance
stats with infrastructure noise).

## D-004 · 2026-10-30 · Initial tunable numbers

**Decision:** Defender time limit 60 s, defender token cap 1024, snippet timeout 5 s, delay
between calls 2 s, max retries 5. They live in a `[settings]` table in
`config/fighters.toml` (added in the config task), not in code.

**Why:** The brief required these budgets but gave no values; free tiers are slow and rate
limited, so the defaults are conservative. Expect to tune them after the first live runs.

**Alternatives considered:** a separate `config/game.toml` (extra file, a layout change).

## D-005 · 2026-10-30 · Vulture also scans tests while modules are unwired

**Decision:** Until the orchestrator (task 6) wires the modules together, the dead-code check
is `uv run vulture src tests`. From task 6 on it is `uv run vulture src` as in CLAUDE.md, and
it must pass clean at the gate.

**Why:** The modules are built bottom-up, so pure functions are only called by their tests
until the orchestrator exists. `vulture src` alone flags all of them; a whitelist or ignore
would hide real dead code later.

**Alternatives considered:** a vulture whitelist file (a suppression that could outlive its
reason), building the orchestrator first (breaks tests-first, bottom-up tasks).

## D-006 · 2026-10-30 · A round is one turn; matches last 6 turns

**Decision:** "Round" and "turn" mean the same thing. A match is at most 6 turns, so each
fighter attacks 3 times. `max_turns = 6` is passed to `match_result` by the orchestrator.

**Why:** The spec uses the two words interchangeably, and the owner chose this reading.

**Consequence:** With base damage 20 and 100 HP, a KO needs 5 hits on one fighter out of 6
turns, so most matches will end by decision. The KO-vs-decision stat will be uninformative
unless damage is raised. Revisit with a superseding entry if the first sims show this matters.

**Alternatives considered:** 6 rounds of 2 turns each (12 turns, realistic KOs).

## D-007 · 2026-10-30 · mypy ignores missing stubs for sympy only

**Decision:** `ignore_missing_imports` is set for `sympy` and `sympy.*` in the mypy config.

**Why:** sympy has no stubs or `py.typed` marker, so strict mypy rejects the import. Calls into
sympy are wrapped in `verifier.py`, which exposes typed functions to the rest of the code.

**Alternatives considered:** `types-sympy` (does not exist), `# type: ignore` on each import
(same effect, scattered), a hand-written stub (speculative for two functions).

## D-008 · 2026-10-30 · Config module, settings names and the HTTP client

**Decision:**
- Add `src/arena/config.py` (loads `config/fighters.toml` into `Settings`, `Provider` and
  `Fighter`). The layout in CLAUDE.md had no module for this, and `llm.py` and `models.py` should
  not read files.
- Provider `base_url` and `api_key_env` live in `fighters.toml` under `[providers.*]`.
- Supersedes the names in D-004: the budget applies to both attacker and defender (same budget
  per turn, as the spec requires), so the settings are `turn_time_limit_s` and `turn_max_tokens`.
  A `backoff_base_s = 2.0` setting is added for 429 backoff. Values are unchanged.
- `openai>=3.0` is required. That version depends on `httpx2` (not `httpx`), and `llm.py` and its
  tests import `httpx2` directly so the SDK can be driven with `httpx2.MockTransport` and no
  network. It is already installed as an `openai` dependency, so no new package is added.
- Only 429 is retried. Timeouts, connection errors and other HTTP errors raise `LlmError`
  immediately; a timeout raises `LlmTimeout` so the orchestrator can log a `timeout` event.
  A response cut off by the token cap is returned with `truncated=True` (also a `timeout` per D-003).
- The request timeout is httpx's per-read timeout, not a hard wall-clock limit.

**Why:** Keeps I/O at the edges, keeps retry limits configurable, and lets tests exercise the
real SDK without network access.

**Alternatives considered:** a fake client class (tests would not cover the SDK's real error
mapping), retrying 5xx and connection errors too (add later only if live runs need it).

## D-009 · 2026-10-30 · Orchestrator behaviour and vulture timing

**Decision:**
- `orchestrator.py` takes the LLM as a plain callable `(fighter, system, user) -> Completion`
  (`LlmClient.complete` in production, a scripted fake in tests). No protocol or base class.
- Fighter A attacks on odd turns, B on even turns; the caller decides who is A.
- Backfire (unparseable attack, failed or crashed snippet, or attacker timeout) logs `backfire`
  then `hit` with the attacker as target. An attacker timeout also logs a `timeout` event.
- Defender timeout, or a reply cut off by the token cap, logs `timeout` then `hit` (D-003). An
  unparseable defender reply scores 0 with a `defend_result` carrying the reason.
- Any other `LlmError` propagates out of `run_match`; the caller treats it as an aborted match
  (D-003).
- `TurnResult` and `MatchRecord` (in `models.py`) carry per-turn outcomes so stats do not parse
  the event log. Per-turn role outcome: attacker wins on `hit`, defender wins on `block` or
  `backfire`.
- `MAX_TURNS = 6` lives in `damage.py` next to the other rule constants.
- Supersedes the timing in D-005: `run_match` has no caller in `src` until the CLI (task 7), so
  the dead-code check stays `vulture src tests` until then and becomes `vulture src` with task 7.

**Why:** Keeps game flow testable without network and keeps stats simple.

**Alternatives considered:** a `Protocol` for the LLM (extra type for one real implementation),
treating attacker timeouts as aborts (one slow free model would stall whole sims).

## D-010 · 2026-10-30 · Stats definitions and how `sim` works

**Decision:**
- Per-turn role outcomes (from D-009): the attacker wins a turn on `hit`; the defender wins on
  `block` or `backfire`. The gate passes when neither role is above 70% of turns and at least
  100 matches are saved; below 100 matches it reports INCOMPLETE.
- "Average damage" is damage per turn (blocks count as 0). Endings are reported as KO, decision
  (a winner on HP) and draw (equal HP), so draws are not folded into decisions.
- `arena sim --n N` means N matches in total. It counts the lines already in the results file and
  runs the rest, so rerunning after a crash or rate limit resumes. Each finished match is appended
  to `runs/sim.jsonl` (`--out` to change) and its battle log is written to `runs/logs/`.
- Pairs are `random.Random(match_index).sample(fighters, 2)`: random but identical when resumed,
  and the first fighter in the pair attacks first.
- A provider error stops the sim with exit code 1. The aborted match is not saved or scored
  (D-003); finished matches are kept.
- A damaged results line (for example from a crash mid-write) is an error naming the file and
  line; delete the line to continue. It is never skipped silently.
- Reading and appending the results file lives in `stats.py` rather than a new module.

**Why:** Keeps the gate measurable per turn as the brief says, and keeps long sims safe to stop
and restart on free-tier rate limits.

**Alternatives considered:** a `--seed` flag (not needed yet), skipping a failed match and
carrying on (could hide a broken provider for the whole run), a round-robin schedule.

## D-011 · 2026-10-30 · Live fighters and settings changes after the smoke test

**Decision:**
- Fighters (IDs checked against each provider's `/models` endpoint, then with a tiny request):
  `gemini-lite` = Gemini `gemini-3.1-flash-lite`, `qwen` = Groq `qwen/qwen3.8-27b`.
  `gemini-2.5-*` returned 404 for this key, so it is not used.
- No OpenRouter fighter for now. The `:free` models tried either always ran out of tokens while
  reasoning (`nvidia/nemotron-3.5-lightning`), did so about half the time (`cohere/north-mini-code`,
  `poolside/laguna-s-2.1`), or returned 429 from the upstream provider (the `google/gemma-4-*`
  models). Empty, truncated replies would show up in the stats as infrastructure noise, not play.
  The OpenRouter provider stays configured.
- Groq `openai/gpt-oss-20b` was dropped: it answers HTTP 400 "model called a tool" when asked
  for Python code, which would abort sims.
- Supersedes numbers in D-004: `turn_max_tokens` 1024 -> 4096 (reasoning models spent all 1024
  tokens thinking and returned nothing) and `snippet_timeout_s` 5 -> 20 (importing sympy alone
  takes about 2.5 s on this machine, so 5 s caused spurious backfires on heavier snippets).

**Why:** Both changes remove infrastructure failures that would otherwise be scored as game
outcomes.

**Alternatives considered:** a provider-specific reasoning-effort option (not generic across the
three providers, so more code), 8192 tokens (free-tier tokens-per-minute limits count the cap).

## D-012 · 2026-10-30 · Attacker prompt tuning (no rule change)

**Decision:**
- The attacker reply format is now `<problem>`, `<code>`, `<answer>` (code first), and the answer
  must be written exactly as the snippet prints it. The prompt tells attackers to work the problem
  out step by step before the tags (only the tags are parsed), to print fully evaluated values
  (never `Integral(...)` or `Sum(...)`), and to prefer problems plain Python or simple sympy settle
  quickly.
- Both roles are told that Euler's number is `E` and the imaginary unit is `I`. A bare `e` parses
  as an ordinary symbol, so correct answers written with `e` were failing the equality check.
- Fighter personas are style-only. The first versions named topics ("likes calculus"), which pushed
  Qwen toward integrals that sympy cannot evaluate.
- The rules (self-verification, backfire, damage) are unchanged.

**Why:** The smoke test (D-011) showed about 50% of attacks backfiring, mostly from stated answers
that did not match the snippet.

**Result (live, 8 attacks per fighter per run, so roughly +/-12 points of noise):** the overall
attack pass rate stayed around 45-50% (smoke test 9 of 18 failed; after tuning 7/16, 7/16, 8/16).
The tuning removed two specific failure types (unevaluated sympy objects, `e` vs `E`) but not the
main one: models state arithmetic results they computed in their heads, and are wrong about half
the time. Groq also rate-limited Qwen past 5 retries in 3 of 8 calls in the last run.

**Alternatives considered:** taking the attacker's answer from its snippet output (removes the
self-verification rule, so it is an owner decision, not a prompt change).

## D-013 · 2026-10-30 · Backfire costs the attacker half damage

**Decision:** When an attack fails self-verification (or the attacker times out or sends an
unparseable reply), the attacker takes `base x difficulty x 0.5` damage (10 with Phase 0 numbers)
instead of the full amount. `BACKFIRE_FACTOR = 0.5` lives in `damage.py` with `backfire_damage`.
Supersedes the damage in the D-009 backfire bullet and the rule line in CLAUDE.md ("attacker takes
the damage"); `docs/PRODUCT_SPEC.md` still describes the full-damage product rule. Who wins a turn
(D-010) is unchanged: the defender still wins a backfire turn.

**Why:** Live runs showed about half of all attacks backfiring (D-011, D-012), which cost attackers
a full 20 HP almost every other turn. This was the owner's choice among the rule options.

**Consequences:**
- The most damage one fighter can take in 6 turns is now 3 backfires x 10 + 3 hits x 20 = 90, which
  is below 100 HP. A knockout is therefore impossible with Phase 0 numbers (D-006 already made it
  rare), so every match ends by decision or draw and the KO count will stay at 0. The KO path is
  still tested, with a higher base damage.
- The 70% gate counts turns won, not HP, so this change does not move the role win rates: a
  backfire still counts as a defender win. Only HP, damage and match results change. If the gate
  fails because of backfires, the next options are counting backfire turns as no result or
  changing which role wins them (an owner decision).

**Alternatives considered:** counting backfire turns as no result (changes the gate metric),
lowering only the backfire penalty further, giving a defender-side bonus (more rules).

## D-014 · 2026-10-30 · Groq fighter switched to gpt-oss-120b; max retries raised

**Decision:**
- The Groq fighter is now `gpt-oss` = `openai/gpt-oss-120b`, replacing `qwen`
  (`qwen/qwen3.8-27b`). Its persona is the same style-only text.
- `max_retries` 5 -> 8 (other settings unchanged). Supersedes the fighter list and retry count in
  D-011 and D-004.

**Why:** Groq's free tier limits `qwen/qwen3.8-27b` to 1000 output tokens per minute (OTPM) and
the account to 8000 tokens per minute; one Qwen reasoning call produces about 1400 output tokens,
so Qwen could make roughly one call a minute and 429s were constant (`retry-after` is only 1 s,
which does not reflect the sliding window). `openai/gpt-oss-120b` ran 12 attack-sized calls with
no 429 and no HTTP 400, finished with `stop` instead of hitting the token cap, and passed
self-verification 6 of 6 times. `openai/gpt-oss-20b` was not used: it spent all 4096 tokens
reasoning in 2 of 2 calls, then 429ed on tokens per minute. The extra retries cover the TPM
window (the exponential waits sum to several minutes).

**Live check:** 3 matches (gpt-oss vs gemini-lite) ran with no provider errors in about 68 s per
match, so 100 matches would take roughly 2 hours. Groq may also have a daily token limit that is not
visible in the response headers; if a long sim stops on a 429 mentioning a daily limit, resume the
next day (the sim is resumable).

**Alternatives considered:** honoring `Retry-After` in `llm.py` (it is 1 s here, so it would not
help), a higher `call_delay_s` (would slow every call to protect one provider), keeping Qwen
(a 100-match sim would take 10+ hours).

## D-015 · 2026-10-31 · Retry 5xx responses like 429s

**Decision:** `LlmClient` now retries HTTP 5xx (`openai.InternalServerError`) with the same
exponential backoff, jitter and `max_retries` limit as 429. After the limit it raises `LlmError`
naming the status ("gemini HTTP 503 after 8 retries"). 4xx errors other than 429, timeouts and
connection errors are still not retried. Supersedes the "only 429 is retried" bullet in D-008.

**Why:** The 100-match gate run stopped repeatedly on Gemini HTTP 503 ("overloaded"), which was
transient: all six resume attempts failed at the first 503 while the API answered normal requests
minutes later. Free tiers return 5xx under load, and one 503 in a 600-call run ended the sim.

**Alternatives considered:** retrying connection errors too (one earlier stop was a Groq
"Connection error", probably the laptop sleeping; add if it recurs), a separate 5xx retry limit
(more settings for no clear need).

## D-016 · 2026-10-31 · Gate run stopped at 48 of 100 matches

**Decision:** The Phase 0 gate run was stopped by the owner at 48 saved matches. The result is
recorded in `docs/PROGRESS.md`: the defender won 96.2% of turns (limit 70%), so the gate is
failing and was not reached. `v0.1.0-prototype` is not tagged. `arena sim --n 100` can resume
from `runs/sim.jsonl` if the run is ever completed.

**Why:** Free-tier outages (Gemini 503s, Groq rate limits) cut throughput to roughly 30 minutes
per match, and the result was decisive: 3.8% against a 70% limit cannot move with 52 more matches.

**Alternatives considered:** waiting for 100 matches (many more hours for the same conclusion),
tagging the failed gate anyway (a tag would read as a pass).

## D-017 · 2026-10-31 · Attacker variety: random topic and problem history

**Decision:** Each turn the attacker prompt names a topic picked with `rng.choice(TOPICS)` from ten
math areas and lists the problems already verified in the match, with "do not repeat them or pose
close variants". `run_match` takes an `rng: random.Random`; `sim` passes the same
`random.Random(match_index)` it uses to pick the pair (so a resumed sim repeats the topics), and
`match` passes an unseeded one. Problems that backfired are not listed. No rule changes, no sampling
temperature setting.

**Why:** In the 48-match gate run gemini-lite posed only 26 distinct problems in 83 verified
attacks (one trivial sum 35 times, because every match started from the same prompt), so it never
landed a hit and the role statistics mostly measured one repeated easy problem.

**Evidence so far (thin):** a 3-match live test (`runs/variety.jsonl`) gave 13 verified problems,
all distinct (gemini-lite 6, gpt-oss 7), with two near-duplicates of one series worded slightly
differently. The test was stopped there because Gemini 503s stalled it; the defender still won
12 blocks + 5 backfires against 1 hit in 18 turns, so this does not fix the balance on its own.

**Alternatives considered:** a `temperature` setting (not accepted by every model, and the topic
list gives variety without depending on sampling), a history of problems across matches (couples
matches, harms resumability), more topics per turn (weaker constraint).

## D-018 · 2026-10-31 · Attacker difficulty prompt (no rule change)

**Decision:** The attacker rules now ask for a problem that needs at least three distinct steps or
ideas, is not a textbook formula or well-known closed form, and hides a trap; they say a problem
a strong solver finishes in one or two lines is too easy. They suggest designing backwards (start
from a structure whose answer the attacker can derive with certainty, then wrap it in a multi-step
setup) and allow brute-force counting, searching or simulating over up to a few million cases. The
earlier hint to prefer "integrals or series with exact closed forms" is removed. Rules, damage and
settings are unchanged.

**Why:** In the 48-match gate run 95% of verified attacks were blocked, and the attacker prompt
itself steered toward standard sums and integrals (D-012).

**Evidence: effectively none.** A 6-match live test (`runs/difficulty.jsonl`) was stopped after
one match because Groq's 8000 tokens-per-minute limit (each request reserves its prompt plus
`max_tokens` 4096) kept the sim waiting up to 300 s. In that match, 3 of 6 attacks backfired
(missing `<code>` tag, a 20 s snippet timeout, a numeric mismatch) and the 3 verified problems,
which were harder than before, were all blocked. One match cannot show whether the block rate or
the backfire rate changed. The change is committed as an untested hypothesis and should be
measured when the providers allow a 20+ match sim.

**Risk:** the attacker cannot run its snippet before answering, so harder problems may raise the
backfire rate more than they lower the block rate.

**Alternatives considered:** waiting for more matches (hours of rate-limit waits for little
information), lowering `turn_max_tokens` to 2048 to double Groq throughput (separate change, may
truncate long reasoning replies).

## D-019 · 2026-10-31 · `turn_max_tokens` stays at 4096 (2048 tried and rejected)

**Decision:** The token cap stays at 4096. A cap of 2048 was tried live and not committed.

**Why:** With the current prompts (step-by-step reasoning, difficulty rules), gpt-oss-120b hit the
2048 cap in 2 of 5 attacks (one reply was empty) and 1 of 5 defenses; gemini-lite hit it in none.
Every cut-off would be logged as a backfire or a defender timeout, so the stats would measure the
cap and not the game. Groq still rate-limited the calls with waits of up to 214 s, so the lower
cap did not fix throughput either (the check of 20 calls took 56 minutes, mostly 429 and 503 waits).

**Alternatives considered:** 3072 (untested), a larger `call_delay_s` (slows every call).

## D-020 · 2026-10-31 · Scripted-fighter simulator (`arena synth`)

**Decision:**
- New module `src/arena/synthetic.py` and command `arena synth [--matches N] [--difficulty D]
  [--seed S]`. It replays the real `run_match` with scripted fighters instead of LLMs and prints a
  table of the attacker's per-turn win rate for skills 0.3 to 0.9 (both fighters equal) against an
  attacker bonus of 0.0 to 0.3, marking cells where the 70% gate would pass. No network, about
  70 s for 300 matches per cell.
- Model: success at any task is a coin flip with probability `1 / (1 + exp(-10 * (skill -
  difficulty)))`. Deriving an attack's answer uses `skill + attack_bonus` at the problem's
  difficulty (drawn around the `--difficulty` value with a 0.1 spread); solving it uses `skill`.
  The scripted snippet always prints 1, and a failed attacker states 2, so the real answer check
  and backfire path run.
- `run_match` gained an optional `verify` argument (default `verify_attack`) so the simulator can
  skip the subprocess; `play_turn` and `_pose_attack` pass it through. Production calls are
  unchanged.
- The simulator is a model of the rules, not of real LLMs. It does not capture formatting errors,
  truncation, rate limits or fighters that differ per task type, and its constants (slope 10,
  spread 0.1, the skill and bonus grids) are not fitted to the live data.
- Adds a layout entry (`synthetic.py`) to CLAUDE.md and a `synth` line to its commands.

**Why:** Free-tier providers allow roughly one live match per 15 minutes, so rule changes cannot be
tested live, and the open question was whether stronger models would fix the balance.

**Alternatives considered:** a separate script outside `src` (would duplicate the match rules),
fitting the model to the 48 live matches (too little data), more sweep axes such as unequal skills
(not needed for this question).

## D-021 · 2026-10-31 · Do not take the attacker's answer from its snippet; compare the rules offline

**Decision:** The self-verification rule stays as it is: a stated answer that differs from the
snippet's output is a backfire (D-013). Taking the answer from the snippet's output instead was
simulated (`arena synth --compare-rules [--skill S] [--bonus B]`) and rejected.

**Why:** The mismatch check is also what keeps broken problems out: a problem whose statement and
snippet disagree is ill posed. If the snippet's output became the answer key, such a problem would
verify and every defender would fail it. The simulator tags each problem as well posed or broken
and counts hits on well-posed problems separately (300 matches per row, both fighters skill 0.7,
attacker bonus 0.1):

- difficulty 0.6: current rule 24% attacker wins; snippet rule 37%, of which 22% from solvable problems
- difficulty 0.7: current 31%; snippet 62%, of which 31% from solvable problems
- difficulty 0.8: current 33%; snippet 80%, of which 30% from solvable problems

The snippet rule adds no legitimate attacker wins (the solvable-problem share equals the current
rule's win rate); the extra wins come from broken problems, and it would pass or fail the gate for
the wrong reason. This corrects my earlier suggestion (PROGRESS.md, previous sweep notes) that
deriving the answer from the snippet was the fix.

**What does work under the current rule (offline model, not yet live):** with an attacker bonus of
0.1 the gate passes when problem difficulty sits near the fighters' skill: 31-33% attacker wins at
difficulty 0.7-0.8 for skill 0.7, and 32% at difficulty 0.9 for skill 0.9. With no bonus the
attacker peaks at about 22% and the gate fails at any difficulty. Backfires are 30-48% of turns
in the passing cells, so that is the price of pitching problems at the attacker's own limit.

**Consequence:** the lever is difficulty targeting, not the answer rule. The real attackers pitch
problems too easy (live: 95% of verified attacks blocked). A closed-loop prompt (tell the attacker
how its previous problems fared so it moves toward the edge of its ability) is the next thing to
simulate and then try live.

**Alternatives considered:** a second pass where the attacker may restate its answer after seeing
the snippet's output (same broken-problem hole), an LLM judge for well-posedness (the spec keeps
judges out of ranked play).

## D-022 · 2026-10-31 · Closed-loop attacker simulated: feedback must span matches

**Decision:** `arena synth --adaptive` simulates an attacker that adjusts problem difficulty from
how its earlier problems fared (harder after a block, easier after failing its own check, unchanged
after a hit), via `SyntheticLlm(adaptive_step=...)`. This is a simulator feature only; the real
attacker prompt is unchanged. Result: in-match feedback is not enough, cross-match feedback is.

**Evidence (offline model, 300 matches per cell, both fighters skill 0.7, attacker bonus 0.1):**
- Feedback reset every match (an attacker only sees its own 6-turn match, so 3 problems and 2
  feedback events): a fixed attacker that starts at difficulty 0.3 wins 3% of turns, 14% with step
  0.2; starting at 0.5 it wins 13% fixed and 20-22% with steps 0.1-0.2. Only a start near the
  right level (0.7, 31% fixed) passes the gate. Steps above 0.2 overshoot.
- Feedback persisting across matches (600 matches, step 0.02 to 0.1): the attacker settles at
  difficulty 0.70-0.80 from any start (0.3, 0.5 or 0.7) and wins 29-31% of turns with a 35% backfire
  rate, which passes the gate. At skill 0.9 the same loop needs more problems to climb (in-match
  results at skill 0.9 are lower: 12-24% from the best starts).
- With no attacker bonus (0.0) no setting passes: the best is 22% (unchanged from D-021).

**Consequence:** to try this live, each attacker's prompt should carry a rolling summary of how its
recent problems fared across the sim, for example "of your last 10 problems, 6 were blocked, 2 failed
your own check, 2 hit; aim for about a third hitting". It can be computed from `runs/sim.jsonl`
(per-turn outcomes), so resuming a sim still works. It couples matches (a later match depends on
earlier ones) and whether an LLM follows such a nudge is unknown; the model only shows the loop
would work if it did.

**Alternatives considered:** a longer match so in-match feedback suffices (would change D-006 and
free-tier cost), a per-fighter difficulty setting in `fighters.toml` found by calibration (manual,
but needs no prompt feedback), the spec's difficulty scorer (out of scope for Phase 0).

## D-023 · 2026-10-31 · Attackers see how their recent problems fared

**Decision:** The attacker prompt gets one more section when the fighter has attacked before: "How
your last N problems fared - blocked by your opponent (too easy): x; failed your own check (too
hard): y; hit your opponent: z. Aim for about a third of your problems to hit...", with N at most 10
(`HISTORY_WINDOW` in `prompts.py`). The outcomes are the fighter's own attacks in earlier matches of
the sim plus its earlier turns in the current match. `run_match` takes an optional `history`
(per side, oldest first) and `arena sim` builds it from the saved results with
`stats.attack_outcomes`, so a resumed sim reconstructs the same feedback. `arena match` passes no
history (only the match's own turns count). No rule changes; the caller's lists are copied, not
modified. Implements the "consequence" of D-022.

**Why:** The scripted-fighter model (D-022) showed a closed-loop attacker passes the gate only if its
calibration persists across matches; one 6-turn match gives too little feedback.

**Evidence:** none live yet beyond the unit tests; the offline model assumes the attacker obeys the
nudge exactly. Whether Gemini Lite and GPT-OSS do is what the next live sim measures. Matches in a
sim now depend on earlier ones, so a sim's order matters and results cannot be shuffled.

**Alternatives considered:** a per-fighter difficulty value in `fighters.toml` (manual calibration,
no prompt change), feedback from the opponent's problems too (not what the model simulated),
numeric difficulty targets (LLMs cannot rate difficulty reliably).

## D-024 · 2026-11-01 · The defender gets its own, smaller token budget

**Decision:** `[settings]` gains `defender_max_tokens` (2048); `turn_max_tokens` (4096) now applies to
attackers only. The orchestrator passes the cap with each call (`Complete` takes `max_tokens`), so
`LlmClient` no longer reads `turn_max_tokens`. A defender reply cut off by the cap is already a
`timeout` event and a hit. The spec's "time/token budget" for the defender is now a real limit that
differs from the attacker's. Amends D-004 and D-019; no other rule or number changes.

**Why:** The 10-match feedback trial (D-023) left the attacker at 6.7% of turns. Prompt changes alone
(D-017, D-018, D-023) did not move it, so a rule lever is next. Backfires count as defender wins
(48% of turns), so even a defender that always failed would cap the attacker at about 52%; this
lever helps only on the blocked part.

**Risk:** D-019 found that at 2048 gpt-oss-120b hit the cap on 1 of 5 defenses and gemini-lite on
none, so the cap mostly penalises the more verbose model. If the attacker rate rises, check how many
of the new hits are `timeout` events before reading it as defender weakness.

**Alternatives considered:** 1024 (reasoning models return empty replies, so it measures the cap),
a shorter `turn_time_limit_s` (free-tier latency and retries dominate call time).

## D-025 Â· 2026-11-01 Â· A failed self-check gets one retry that shows the real result

**Decision:** When an attacker's snippet fails verification (mismatch, crash or snippet timeout), the
attacker is asked once more. The retry prompt shows its problem, code and stated answer, plus the
verifier's result (for a mismatch: what the snippet printed), and asks it to fix whichever is wrong.
The retry is verified exactly like the first attempt; a second failure is a backfire (D-013), with
the second attempt's reason. Replies that cannot be parsed and LLM timeouts get no retry, as there is
nothing to show. New log event `attack_retry` (actor, reason) before the retry's own events.
`prompts.correction_prompt` builds the message; `orchestrator._pose_attack` runs the retry. Amends
D-013 and the spec's event list; the final check (answer equals snippet output) is unchanged.

**Why:** In the gate run 63 of 76 backfires (83%), and 75 of 96 in the later runs (78%), were a stated
answer that differed from the snippet's output. The attacker never sees its snippet run, so it guesses
the number; models are poor at that and good at code. Backfires were about half of all turns, which
caps the attacker near 52% even against a defender that always fails (D-024). Showing the real output
lets the attacker correct itself without dropping the check that keeps ill-posed problems out
(D-021): the corrected answer must still equal what its code prints.

**Risk:** An attacker can copy the printed value without checking it against the problem, so a broken
problem can now pass. The retry prompt tells it to fix the wrong part and keep the problem as
written, but nothing enforces it. Watch for hits with no sensible answer when reading live results.
Costs one extra call on each failed first attempt (about half of attacks).

**Evidence:** unit tests only. The scripted-fighter simulator (D-020 to D-022) now models the retry
as an independent second draw, which is a rough stand-in; its earlier findings were computed
without a retry.

**Alternatives considered:** run the snippet first on every attack and ask the attacker to confirm
(an extra call on every attack, slow on the free tiers); take the answer from the snippet (rejected in
D-021); prompt-only tweaks (unlikely to remove a guessing error).

## D-026 Â· 2026-11-02 Â· Phase 0 closed without passing the gate

**Decision:** At the owner's request Phase 0 is closed with the balance gate not met. No
`v0.1.0-prototype` tag is created, because the tag name implies a pass. Phase 1 (MVP, see
`docs/PRODUCT_SPEC.md`) may be planned; no Phase 1 code is written until its plan is approved. This
overrides the CLAUDE.md rule "stop at the gate" once, on the owner's explicit instruction.

**Why:** Free-tier limits (Groq 429s and tokens-per-minute caps, Gemini 503s) made live runs
take 15 minutes or more per match and abort partway, so the 100-match gate could not be measured
within reasonable time or at all. The last trial (D-025 retry) never produced a match.

**Final numbers (attacker's share of turns; the gate needs 30% to 70%):**
- Gate run, 48 matches: attacker 3.8%, defender 96.2%, backfires 26.4%.
- Outcome feedback (D-023), 10 matches: attacker 6.7%, backfires 48.3%.
- Defender token cap (D-024), 8 matches: attacker 16.7%, backfires 52%.
- Retry on a failed self-check (D-025): implemented and unit-tested, not measured live.

**What Phase 0 established:**
- The engine, battle log, stats and scripted-fighter simulator work (163 tests).
- Verified attacks are problems a strong model also solves, so the defender wins about 95% of them.
- Backfires are about half of all turns; 78-83% are a stated answer that differs from the snippet's
  output, because the attacker never sees its snippet run (fixed in code by D-025, unmeasured).
- Results depend on problem difficulty relative to skill (D-020 to D-022), which Phase 0 fixes at 1.0.
  The Phase 1 difficulty scorer is the intended lever.
- Results from small free-tier models do not establish balance for stronger models.

**Open for Phase 1:** re-run the 100-match gate with the D-025 retry once model access is not limited
by free tiers (bring-your-own keys), and treat it as a blocking check before any ranked play.

**Alternatives considered:** keep trying on the free tiers (rejected by the owner); tag the engine
milestone anyway (rejected: it would misreport the gate result).

## D-027 Â· 2026-11-02 Â· Phase 1 slice order approved; CLAUDE.md moves to Phase 1

**Decision:** The owner approved the 11-slice order in `docs/PLAN_PHASE1.md`: foundation, text replay
viewer, log schema v2, PixiJS renderer, persistence and workers, auth/fighters/BYO keys, difficulty
scorer, balance re-check, ranked and Elo, code domain and sandbox, launch hardening. `CLAUDE.md`'s
current phase becomes 1 and its scope is "the current slice only". Slice 8 (100-match balance
re-check with the D-025 retry and the scorer) must pass, or the rules be changed and logged, before
slice 9. Open decisions 2-6 in the plan are due before the slice that needs them; none is assumed.

**Why:** The spec's build plan puts the UI in Phase 1. Building the replay viewer first costs no
model calls, so free-tier limits cannot block it.

**Alternatives considered:** code domain earlier (largest security surface, Linux-only sandbox) or
dropped from the MVP (owner kept it, last).

## D-028 Â· 2026-11-02 Â· Phase 1 foundation: one repo, FastAPI, Next.js, Docker Compose

**Decision:** One repository holds the engine (`src/arena/`), the API (`src/arena_api/`, same
`pyproject.toml`, so the existing ruff, mypy strict, vulture and pytest cover it) and the web app
(`web/`). `docker-compose.yml` starts Postgres 16, Redis 7, the API and the web app, with ports bound
to localhost (web 3100, API 8100, Postgres 5442: other local projects already own 3000, 8000 and 5432); Postgres and Redis
are unused until slice 5. The Postgres password has a local-only
default (`arena-dev`), overridable with `POSTGRES_PASSWORD`. CI (GitHub Actions) is deferred: the repo
has no remote, so a workflow would never run; pre-commit still runs the Python checks.
The web app is hand-written (no `create-next-app`) and checked with `tsc --noEmit` and `next build`;
no web test framework until there is logic to test.

**Dependencies (new):**
- Python, in a new uv dependency group `api` (on by default, excluded from the Docker image's dev
  tools): `fastapi`, `uvicorn`. Serves the API; the spec's chosen stack.
- Web: `next` (16, since 15.x had an audit finding fixed only in 16), `react`, `react-dom`,
  `typescript`, `@types/node`, `@types/react`. The spec's chosen frontend; `npm audit` reports 0.
- No `httpx` was needed: FastAPI's test client works with the installed `httpx2`.

**Linter configuration:** `[tool.vulture] ignore_decorators = ["@app.*"]`. FastAPI registers route
handlers through the decorator and nothing calls them, so vulture reports them as unused. This is a
decorator pattern, not a blanket ignore; dead code elsewhere is still reported.

**Packaging:** `[tool.uv.build-backend] module-name = ["arena", "arena_api"]` so both packages are in
the built project; `default-groups = ["dev", "api"]` keeps `uv sync` unchanged for development.

**Alternatives considered:** separate repos for web and API (rejected by the owner); a shared
workspace with separate Python projects (more config than one `pyproject` for no gain yet); database
drivers and a Redis client now (YAGNI until slice 5).

## D-029 Â· 2026-11-02 Â· Replay API reads battle-log files and derives the turn view in Python

**Decision:** `GET /replays` lists the `*.json` battle logs in `ARENA_LOGS_DIR` (default `runs/logs`)
with id, winner, reason, final HP and turn count; `GET /replays/{id}` returns the same summary plus
one record per turn (attacker, outcome, target, damage and its arithmetic, problem, stated and
defender answers, score, timeout and retry flags, failure reason, HP after, turn length). The
arithmetic is built from `arena.damage` constants, not copied numbers. Ids must match
`[A-Za-z0-9_-]+` (they become file names), an unknown id is a 404, an unreadable log is skipped with a
warning in the list and is a 500 when asked for directly. The web app only calls this API; it never
reads files. The viewer is a text page: a timeline of turn buttons and a reveal panel. Compose mounts
`runs/logs` read-only into the API container. No new dependencies.

**Why Python, not TypeScript:** the log-to-turn logic is the only real logic in the viewer, and it is
tested by the pytest suite that already exists. Putting it in the web app would need a JavaScript test
framework (a new dependency) for one function. Slice 4 will add the raw events to the response for the
animation.

**Linter configuration:** `[tool.vulture] ignore_names` lists the response-field names that vulture
reports as unused (`damage_math`, `defender_answer`, `timed_out`, `retried`, `failure_reason`,
`duration_ms`, `id`, `turn_count`): FastAPI serialises them and no Python code reads them. New
response fields that only the web reads must be added to the list.

**Known gaps until slice 3 (log schema v2):** logs hold no fighter names (the page says Fighter A/B),
no problem for a backfired turn, and no persona. Problems are shown as plain text, so LaTeX appears
raw. `runs/logs` mixes several runs; `runs/logs_gate48` is the clean 48-match gate run.

**Alternatives considered:** deriving the turn view in the web app (needs a JS test framework);
reading files from the web app (breaks the rule that the web never touches storage); returning the raw
log and letting the page work it out (every consumer repeats the logic).
