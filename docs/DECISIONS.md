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

## D-025 · 2026-11-01 · A failed self-check gets one retry that shows the real result

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

## D-026 · 2026-11-02 · Phase 0 closed without passing the gate

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

## D-027 · 2026-11-02 · Phase 1 slice order approved; CLAUDE.md moves to Phase 1

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

## D-028 · 2026-11-02 · Phase 1 foundation: one repo, FastAPI, Next.js, Docker Compose

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

## D-029 · 2026-11-02 · Replay API reads battle-log files and derives the turn view in Python

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

## D-030 · 2026-11-02 · Battle log schema 2: header, attempts on events, lowercase sides

**Decision:** The battle log gains `schema: 2` and a `fighters` header with `a` and `b`, each
`{name, provider, model, persona}` (`BattleLog.record_fighters`, called first by `run_match`). Events
now carry the attack itself: `attack_verified` has `problem`, `answer` and `code` (the snippet);
`attack_retry` (D-025) has the same three for the first attempt, next to its `reason`; `backfire`
has them for the last attempt whenever the reply parsed. A reply that could not be parsed or timed
out has nothing to show, so its `backfire` stays `actor` and `reason` only. Sides stay lowercase
`a`/`b`, including the `hp` event's keys. The API's replay response adds `code` and `first_attempt`
per turn, `fighter_a`/`fighter_b` on a replay and `name_a`/`name_b` on a summary; schema 1 logs
still load and give `null` for the new fields, and the page falls back to "Fighter A/B".

**Why:** The slice 2 viewer could not name the fighters, show a backfired problem or show what a
retry changed. The persona is hidden during a match and shown in the replay afterwards (spec), and a
log file only exists after the match.

**Sides stay `a`/`b`:** the spec's example uses `A`/`B`, but it is only an example. The engine, stats,
tests and every stored log use `a`/`b`; changing it would touch all of them for no gain.

**Not added yet, on purpose:** `fx` (renderer, slice 4), `problem_id` (persistence, slice 5),
`difficulty` (scorer, slice 7), `domain` (second domain, slice 10). Each is added by the slice that
uses it.

**Consequences:** logs are larger (the snippet is stored). The persona is in every log file, which is
fine for local files; before replays are public (later slices) the API must withhold it until the
match is over. New response fields that only the web reads (`code`, `first_attempt`, `name_a`,
`name_b`) were added to the `[tool.vulture] ignore_names` list.

**Alternatives considered:** uppercase sides to match the spec example (rejected, above); a separate
file for attempts (more files for no reader); storing attempts only for backfires (the viewer also
needs the first attempt of a retry that then succeeded).

## D-031 · 2026-11-03 · Replay renderer: Pixi with drawn shapes, planned in TypeScript

**Decision:** The replay page plays each turn on a Pixi canvas (720x320). 2D with fighters drawn from
shapes in code (no sprite art); real sprites can replace them later without touching the animation
logic. `web/lib/choreography.ts` (`planTurn`, `planMatch`) turns a turn into timed steps: retry
flash, windup, projectile, think or timeout, block or hit, health-bar move, KO; a backfire is windup,
rebound, hit on the attacker. Phases have fixed lengths, so a turn plays for 3 to 6 seconds at 1x
whatever the agents really took. `web/lib/stage.ts` draws the scene as a pure function of (plan,
time), so play, pause, replay and speed only move a clock. The API's replay response gains `max_hp`
(from `arena.damage.STARTING_HP`) so the web app has no hard-coded 100. The page has Play match,
Replay turn, Pause/Resume and 1x/2x; clicking a turn plays it; it honours `prefers-reduced-motion`
(shows each turn's final picture) and falls back to a message when WebGL is unavailable, leaving the
text viewer working.

**Dependencies (new):** `pixi.js` 8 (the spec's renderer; loaded only on the replay page, in the
browser) and `vitest` (dev only). `npm audit` reports 0.

**Why vitest now:** D-029 avoided a JavaScript test framework because the viewer had no logic of its
own. The planner does, so its 12 tests (step order per outcome, 3 to 6 s per turn, KO only at 0 HP,
health carried between turns) are worth one dev dependency.

**Revises D-029:** it said slice 4 would add raw events to the API. Not needed: the per-turn view
already holds everything the animation uses, so the API gets `max_hp` only.

**What was checked live:** in the built-in browser the canvas starts without console errors, and the
retry flash, windup, projectile, thinking, hit (flash, floating damage, health bar moving to 80%) and
backfire (projectile out and back, damage on the attacker) were seen. The pane throttles animation
frames (Pixi caps a frame at 0.1 s, so it ran at about a fifth of real speed), which is why checking
took long. Block (shield), defender timeout, KO and the whole-match mode were not seen.

**Known limits:** looks basic by design; no sound; the stage is not scrubbable; HP numbers are shown in
text below the stage, not on the bars. Pixi's `maxElapsedMS` makes the animation run slow, never
skip, on a slow device.

**Alternatives considered:** sprite art (none exists; replaceable later); deriving the steps from the
raw log events (more API surface for no extra information); a canvas-free CSS animation (the spec
chose Pixi and the later effects need it).

## D-032 · 2026-11-02 · Matches in Postgres, played by an arq worker

**Decision:** One `matches` table (migration `0001_matches.sql`) holds each match: id, status
(`queued`, `running`, `finished`, `failed`), the two fighter names, a summary (winner, reason, final
HP, turn count), the whole battle log as JSONB, an error message and timestamps. `POST /matches`
(two fighter names from `config/fighters.toml`) saves a queued row and enqueues `play_match`; it
answers 202, or 422 for an unknown or identical pair, 429 when `MAX_QUEUED` (5) matches already wait,
503 when the queue is down (the row is then failed, not left waiting). `GET /matches/{id}` reports
status and error. The worker (`arq arena_api.jobs.WorkerSettings`) plays one match at a time
(`max_jobs = 1`, so the free tiers are not hit harder) and never retries (`max_tries = 1`: a retry
would play and pay for the match twice). Provider and config errors fail the match with their message;
any other error fails it and is re-raised. A worker that starts first fails matches a dead worker left
`running`. `GET /replays` and `GET /replays/{id}` now read finished rows; the file-based replay source
(`ARENA_LOGS_DIR`) is gone, replaced by `python -m arena_api.import_logs FOLDER [--prefix P]`, which
validates each log and skips ids already present. Migrations are numbered `.sql` files applied by
`db.migrate()` (both API and worker run it on start, serialised by an advisory lock).

**Dependencies (new, in the `api` group):** `psycopg[binary]` 3 (Postgres driver) and `arq`, which
brings `redis` (the spec's queue; fits the async API). No ORM and no Alembic: one table, and Alembic
would pull in SQLAlchemy only to run a few `CREATE` statements. Move to Alembic when the schema grows.

**Deviations from the spec:** problem and answer bodies are not in object storage, the whole log is
in the `log` column (about 6 KB per match); revisit when size matters. The `turns` and `problems`
tables wait for ranking and the novelty check.

**Tests:** database tests use a throwaway database on the compose Postgres (`tests/conftest.py`) and
skip with a message when it is not running; set `TEST_DATABASE_URL` to use another server. The
worker job runs with a scripted LLM, the queue is a stub (FastAPI dependency override); no network.

**Security note:** there is no sign-in until slice 6, so anyone who can reach the API can start
matches that spend the provider keys. The compose ports are bound to localhost and the queue is
capped; do not expose the API beyond localhost before slice 6.

**Linter configuration:** `[tool.vulture] ignore_names` gains `WorkerSettings` and its attributes
(`functions`, `on_startup`, `redis_settings`, `max_jobs`, `max_tries`, `job_timeout`): arq finds them
by name.

**Alternatives considered:** keeping file logs as a second source (two stores for good, and the
file tests stayed file-bound); SQLAlchemy and Alembic now (too much for one table); Celery (heavier,
not async); storing logs in object storage now (a new service for 6 KB rows).

## D-033 · 2026-11-03 · Sign-in: GitHub OAuth, database sessions, same-origin proxy

**Decision:** Users sign in with GitHub (OAuth web flow written against the existing `httpx2` client,
no auth library). `GET /auth/github/login` redirects to GitHub with a random `state` that is also
set in a short-lived HttpOnly cookie; `GET /auth/github/callback` refuses the request unless the two
match, exchanges the code, reads the GitHub id and login, creates or finds the user (the handle follows
GitHub's current login) and starts a session. A session is a random token in an HttpOnly,
SameSite=Lax cookie (`Secure` when `PUBLIC_URL` is https); the database keeps only its SHA-256, so a
leaked table hands out no sessions, and logout deletes the row (14-day expiry). `GET /auth/me`,
`POST /auth/logout`, `GET /auth/config` and the `current_user` dependency (401 when signed out) are
the surface later routes use. Tables `users` and `sessions` (migration 0002). The web app forwards
`/api/*` to the API (a Next.js rewrite whose target `API_URL` is baked in at build), so the browser
talks to one origin and the cookie is same-site; server components forward the cookie themselves
(`web/lib/server-api.ts`). New env: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `PUBLIC_URL`. No new
dependencies.

**Local dev sign-in (hazard):** `POST /auth/dev {handle}` signs in as any handle, with no password.
It answers 404 unless `ARENA_DEV_LOGIN=1`. Only `docker-compose.yml` turns it on (default 1 there)
so the whole flow can be tried without registering an OAuth app. Running the API anywhere reachable
with this flag on lets anyone sign in as anyone; it must be 0 or unset outside a local machine.

**Why database sessions and a proxy:** sessions can be revoked, need no signing library, and keep
the secret server-side; the proxy avoids cross-origin cookies and CORS entirely.

**Not done:** Google sign-in (the spec's second provider; add when someone needs it); CSRF tokens
(state-changing routes take JSON bodies, which a cross-site form cannot send, and the cookie is
SameSite=Lax); sign-in rate limiting; deleting expired session rows.

**Needs you for real sign-in:** register a GitHub OAuth app with callback
`http://127.0.0.1:3100/api/auth/github/callback` and put its id and secret in `.env`.

**Alternatives considered:** `authlib` or `itsdangerous` signed-cookie sessions (a dependency for
about 40 lines and no revocation); letting the browser call the API directly (cookies and CORS);
storing the session token unhashed (a database leak would be account takeover).

## D-034 · 2026-11-03 · Fighters with versions and encrypted bring-your-own keys

**Decision:** A signed-in user owns up to 10 fighters (`MAX_FIGHTERS_PER_USER`). `fighters` holds the
name (unique per owner) and `daily_match_cap`; `fighter_versions` holds each numbered version:
provider, model, persona, the API key encrypted, and its last four characters (`key_hint`). Every
edit (`POST /fighters/{id}/versions`) adds a version and starts it unverified; leaving the key out
keeps the saved one. Providers must be one of the `[providers.*]` in `config/fighters.toml`, so a user
cannot point the server at an arbitrary URL. Routes: `GET /fighters`, `POST /fighters`,
`GET /fighters/{id}`, `POST /fighters/{id}/versions`, `GET /fighters/options` (providers and the
Aggressive, Defensive and Counter-puncher persona templates). Someone else's fighter is a 404.
Responses never include the key, only `key_hint`; no log line prints it.

**Key encryption:** Fernet (AES-128-CBC with an HMAC) with a server secret `KEY_ENCRYPTION_SECRET`
from the environment. Without it, saving a fighter answers 503 and says why; a changed secret makes
saved keys undecryptable (reported, not crashed on). The secret is not rotated or stored with the
data. This protects a copied database, not a compromised server.

**Dependency (new, `api` group):** `cryptography` (Fernet). Writing our own cipher is not an option.

**Spend cap:** `daily_match_cap` (default 10, 1 to 50) is a limit on matches per fighter per day, the
only cap the engine can enforce today. It is stored here; sparring and later ranked play enforce it
(6c). It is not a token or dollar cap: nothing tracks usage yet. What bounds the cost of one match is
`turn_max_tokens`/`defender_max_tokens` times the number of calls.

**Not done:** tools, strategy settings, avatars and weight classes (no engine support yet, or later
slices); key rotation; deleting a fighter or a key.

**Linter configuration:** `[tool.vulture] ignore_names` gains `verified` and `version`, which only the
API's JSON output reads.

**Alternatives considered:** one key per user instead of per fighter (the spec stores a key reference per
version, and a user may want a different provider per fighter); letting users type any base URL
(server-side request forgery); a secrets manager (a service to run for one value).

## D-035 · 2026-11-03 · Sparring against the house bot, owned by the user who asked

**Decision:** `POST /fighters/{id}/spar` (owner only) queues a sparring match between the fighter's
latest version and the `house_bot` named at the top of `config/fighters.toml` (`gemini-lite`;
`Config.house_bot`, which must be a configured fighter). It answers 202, or 404 for someone else's
fighter, 422 if the fighter's provider left the config, 429 when the fighter reached its
`daily_match_cap` or the user reached `MAX_SPARS_PER_USER_PER_DAY` (5) or the queue holds
`MAX_QUEUED` (5), 503 without a house bot or when Redis is down. Caps count matches created in the
last 24 hours, whatever happened to them. In the match the user's fighter is named `handle/name`
(unique, so its key cannot be applied to another fighter) and plays side A with the user's own key;
the house bot uses the server's keys. The worker builds one `LlmClient(keys=...)` per match, so a key
lives only as long as its match; `LlmClient` takes an optional `keys` map (fighter name to key) and
falls back to the provider's environment key. A spar lasts `SPARRING_TURNS = 3` (the spec's "3 unranked
rounds"; a round is a turn, D-006): `run_match` gained an optional `max_turns`, default `MAX_TURNS`,
so nothing else changes. `matches` gained `mode` (`sim` or `sparring`), `requested_by`, `fighter_id`
and `fighter_version` (migration 0004). The old open `POST /matches` is removed: the only way to start
a match through the API is now a spar by a signed-in owner, which closes the D-032 hole (anyone who
could reach the API could spend the server's keys). `GET /matches/{id}` is for the requester only.

**Verified:** a version is marked verified (`verified_at`) when its spar finished and the fighter
replied at least once (a verified attack, a retry or a defense answer). A key that the provider rejects
fails the match instead; a fighter whose every call times out finishes but stays unverified. A new
version starts unverified. Verification is a check that key and model work, not a rating.

**Privacy:** a sparring replay contains the owner's persona, so `GET /replays/{id}` opens it only for
its owner (404 for anyone else) and the public `GET /replays` lists only `sim` matches. Provider
errors can echo a rejected key, so the worker replaces the key with `[key]` in any error it stores.

**Web:** `/fighters` (mine), `/fighters/new`, and `/fighters/{id}` with a spar button, the spar list
(status refreshes every 5 s while one is waiting or playing, links to the replay when finished) and an
edit form that saves a new version. A signed-out visitor to a protected page is sent to `/login`. The
API key field is write-only.

**Checked live:** in the compose stack, dev sign-in, creating a fighter with a dummy key, and a spar:
the worker used the user's key against Groq, which answered 401, and the page showed
`failed: groq returned HTTP 401 ... Invalid API Key`; the database held a Fernet token (not the key),
no log line or page contained the key. The success path (a finished spar marking the version
verified) is covered by tests with a scripted LLM, not run live: that needs a real provider key, which
is the owner's to enter.

**Not done:** a real spar with a real key; per-token or dollar caps; deleting fighters or keys;
publishing and rating (slice 9); the GitHub sign-in against github.com (needs an OAuth app).

**Alternatives considered:** sparring over the full 6 turns (twice the cost on the user's key and the
house bot's free tier); letting any signed-in user start config-fighter matches (the same abuse hole
as before); a global key per provider shared by all users (the point of this slice is that users bring
their own).

## D-036 · 2026-11-03 · Difficulty from a reference panel

**Decision:** After an attack passes its own check, a panel of reference models (`[[panel]]` entries in
`config/fighters.toml`, each a fighter-shaped provider, model and persona) solves the problem, all at
the same time, with the defender's prompt and `defender_max_tokens`. Each answer is checked with
`answers_match`. Difficulty is `0.5 + 1.5 × failed / answered` (`damage.difficulty_from_panel`; range
`DIFFICULTY_MIN` 0.5 to `DIFFICULTY_MAX` 2.0, the spec's), and `damage = 20 × difficulty × (1 − score)`.
A member that times out, is cut off at the token cap, or gives no parseable answer counts as failing,
as a defender would. A member that hits a provider error (rate limit, outage) is left out of the count;
if none answers the difficulty stays `DIFFICULTY` (1.0). Backfires are never scored (nothing verified)
and still cost `20 × 1.0 × 0.5`. `run_match(panel=...)` takes the panel (default empty = 1.0 as before);
`arena match` and `arena sim` pass `config.panel` unless `--no-panel`. Sparring and the worker pass no
panel, to spare the server's free-tier quota; ranked play (slice 9) will. A new `difficulty` event
follows `attack_verified`: `value`, `failed`, `answered`, `tokens` and each member's `result`
(`solved`, `failed`, `error`) and `tokens`. `Completion` gained `tokens` (the provider's
`usage.total_tokens`, None if not reported) and the `Complete` alias moved to `llm.py` so the scorer and
the orchestrator can share it without an import cycle. The replay API adds `difficulty`,
`panel_failed` and `panel_answered` per turn and its damage arithmetic uses the logged difficulty (old
logs show 1.0); the page shows "Difficulty 1.5 (2 of 3 reference models failed it)". No new dependencies.

**Panel chosen:** `gemini-3.5-flash-lite` (Gemini), `openai/gpt-oss-20b` and `qwen/qwen3.8-27b` (Groq):
three families, none of them the two fighter models, so difficulty is not just difficulty for the
fighters. Tried first with the server's free-tier keys: `gemma-4-31b-it` answered correctly but took
37 to 55 s a call (the 60 s turn limit would turn it into a false failure), `gemini-2.5-flash-lite`
returned 404, the chosen three answered in 3 to 9 s. Two members share Groq's 8000 tokens-per-minute
budget with the Groq fighter, which is the weak point (below).

**Measured live** (one match, gemini-lite vs gpt-oss, `runs/m_20261103T082617.json`, free tiers): five
problems were scored; difficulties 0.5, 1.0, 0.5, 1.5, 1.0, so the scale does spread. Cost per scored
problem: 3 extra calls and about 4,300 tokens in total (3,250 to 6,060), roughly 1,450 per member.
Panel time was 7.5 to 9 s for three problems, 32 s for one and 372 s for one (Groq rate limits: 13
retry warnings in the run); the match took about 8.5 minutes, 372 s of it that single wait. Per
member, failures: qwen 2 of 5, gpt-oss-20b 1, gemini 1. Every scored problem was still blocked by the
defender, and one attack backfired, so no damage was dealt by a scored problem in this sample.

**Known limits:**
- The panel cannot tell a hard problem from an ill-posed one: a broken problem every model fails
  scores 2.0 and its defender takes double damage. A consensus check (members agreeing with each
  other against the attacker's answer) would flag it; not built.
- The turn-based gate (D-026, "neither role wins over 70% of turns") does not move with difficulty:
  a block deals no damage at any difficulty. Slice 8 needs a damage- or HP-based measure, or to feed
  difficulty back to attackers (as D-023 does with outcomes), and that is the owner's call.
- Free-tier cost: the panel adds roughly three calls per verified problem and rate-limit waits on
  Groq; a 100-match run will be slow. `gpt-oss-20b` was rejected as a fighter earlier (D-014, token
  cap); as a panel member a cut-off counts as failing, which could inflate difficulty.
- Novelty penalty (the spec's embedding check) is not part of this slice.

**Alternatives considered:** reusing the two fighter models in the panel (correlated with the
defenders); running the three calls one after another (a turn would wait three times as long); counting
panel provider errors as failures (a rate limit would raise difficulty); a non-linear scale (no data
to justify one yet).

## D-037 · 2026-11-03 · How the slice 8 balance re-check is run

**Decision:** The 100-match gate re-check (CLAUDE.md: slice 8 must pass, or the rules be changed and
logged, before ranked play) runs as `arena sim --n 100 --no-panel --out runs/gate2.jsonl`, with the
D-025 retry, the D-023 outcome feedback and the 2048-token defender budget (D-024) as shipped, on the
free tiers.

- **No panel:** the gate counts which role wins each turn, and difficulty only scales how much a hit
  deals, so scoring problems cannot change a turn's outcome. Skipping it roughly halves the calls and
  avoids the Groq rate-limit contention seen in the one panel match (D-036).
- **Verdict on intervals:** `format_stats` now prints 95% Wilson intervals for both roles and the hit
  rate among attacks that reached a defender (backfires excluded), and the gate verdict follows the
  interval: PASS when the dominant role's upper bound is at most 70%, FAIL when its lower bound is above
  70%, INCONCLUSIVE when the interval straddles 70%. A run under 100 matches is INCOMPLETE and says
  "cannot pass" once the dominant role's lower bound exceeds 70%, which is the early-stop signal: the
  run is checked at 50 matches (about 300 turns) and stopped if it cannot pass, to spare free-tier
  quota.
- **Defender token logging:** `Completion.output_tokens` is the total minus the prompt, so hidden
  reasoning counts (Gemini's `completion_tokens` leaves its thinking out), and a defender's
  `defend_result` and cut-off `timeout` events carry it. The panel measurement showed defenders spending
  about 1,000 to 2,000 tokens a problem, so the defender budget is a strong lever; with the token
  counts logged, the share of defenses a tighter cap would have cut off can be computed from the run
  itself, without another run, before any rule is changed.

**Not decided here:** what to change if the gate fails. That choice (a deliberate defender budget, a
prompt change, or changing the gate metric) waits for the measurement and the owner.

**Alternatives considered:** running with the panel (about double the quota and time for no change to
the verdict); judging on the point estimate (a run near 70% would be called a pass or fail on noise);
a fixed 100 matches regardless of what 50 show (spends free-tier quota on a run that cannot pass).

## D-038 · 2026-11-03 · `arena sim` waits out an overloaded provider and replays the match

**Decision:** `LlmClient` raises `LlmUnavailable` (a subclass of `LlmError`) when a provider's
retries run out on a 429 or 5xx, or when it cannot be reached; every other provider error (a 401 for a
bad key, a 400, an empty reply) stays a plain `LlmError`. `arena sim` catches `LlmUnavailable` from a
match, waits `SIM_COOLDOWN_S` (300 s), and replays that same match, up to `SIM_MATCH_ATTEMPTS` (3)
attempts in all; after the last it stops with the error as before. The replay starts clean: a fresh
`BattleLog` and a fresh `Random(i)`, so it is the same pairing and topics as an undisturbed match, and
nothing from the failed attempt is saved. Plain `LlmError`s do not wait. Callers that catch `LlmError`
(the worker, `arena match`) are unaffected. The two numbers are constants in `cli.py`.

**Why:** the first two slice 8 gate attempts (15:40 and 15:56 on 2026-11-03) each died inside match 1
because Gemini kept answering 503 "overloaded" for longer than the client's own eight retries (about
nine minutes), although a probe between them was answered. Each attempt saved nothing. Matches are
independent apart from the outcome feedback built from saved results, so replaying one is safe.

**Bounds:** at most two waits of 5 minutes per match, so a real outage costs about ten minutes of
waiting and then stops; "never retry forever" holds. A 401 or 400 does not wait, so a bad key fails at
once.

**Not done:** the same wait for `arena match` (one match, run by hand) and for the worker (a user is
waiting on the status page; it fails the match and shows the reason).

**Alternatives considered:** raising `max_retries` or the backoff in `config/fighters.toml` (it would
also slow every user-facing call, and a 401 would still be retried); swapping the Gemini fighter (a
different experiment); waiting and rerunning by hand (needs someone present).

## D-039 · 2026-11-04 · The slice 8 gate runs on a Groq-only fighter pool

**Decision:** The 100-match re-check (D-037) runs with `gpt-oss` (openai/gpt-oss-120b) against `qwen`
(qwen/qwen3.8-27b), both on Groq, from `config/gate-groq.toml`:
`arena sim --n 100 --no-panel --config config/gate-groq.toml --out runs/gate3.jsonl`. `gemini-lite`
leaves the gate pool. `config/fighters.toml` is unchanged, so the house bot and the web app still use it.
The 14 matches already in `runs/gate2.jsonl` are kept as a partial record and are not counted in the
gate: that run paired `gemini-lite` with `gpt-oss`, and mixing pairings would blur the role effect.

**Why:** Gemini answered 503 on every attempt at match 15 in two runs, with a 5-minute cooldown between
attempts (D-038), and a probe on 2026-11-04 still got a 503 while Groq answered. Waiting more would only
spend free-tier quota and time. Qwen is a different family from gpt-oss and answered live in the panel
match (D-036) and in a probe today.

**What this changes:** the gate now measures role balance for a pair of Groq models, not for the
original pair. The 14-match reading (attacker 20.2%, 95% interval 13.0-30.0%) is not evidence for
this pool. Both fighters share Groq's 8000 tokens-per-minute limit, so the run may be slow.

**Not done:** no change to rules, prompts or budgets; the early-stop check at 50 matches (D-037) still
applies.

**Alternatives considered:** waiting for Gemini and resuming (open-ended); gpt-oss-20b as the second
fighter (same family as gpt-oss-120b, so a weaker test of role balance); an OpenRouter `:free` model
(unreliable in D-011); counting the 14 saved matches (mixes two pairings).

## D-040 · 2026-11-06 · An unreadable attacker reply gets the one retry

**Decision:** A first attacker reply with no usable `<problem>`, `<answer>` and `<code>` tags is retried
once, as a failed snippet check already is (D-025): `attack_retry` is logged with `reason` and
`truncated` (the reply hit the token cap), and the retry prompt (`unparsed_prompt`) says whether the
reply was cut off or unreadable and asks for brief working with the tags written early. There is still
one retry per attack, so an unreadable draft followed by a wrong snippet backfires. A timeout still gets
no retry. The attacker rules now ask for brief working ("a few lines") and warn that a reply cut off
before the tags costs the turn, in place of "work the problem out step by step".

**Why:** In the first 22 gate matches on the Groq pool (D-039), 33 of the 49 backfires were a missing
tag, and `_draft` treated a cut-off reply as a backfire on the spot, with no retry. A live check of 24
attacker calls (12 per fighter, `turn_max_tokens` 4096) found 5 failures, all cut off at the cap: two
qwen replies of 9,600 and 13,900 characters of working, and three gpt-oss replies with no visible text
at all (the cap went to hidden reasoning). The prompt told them to work step by step first.

**Measured after the change (the same 24 calls, retry included):** first drafts failed 6 of 24 (qwen 5,
gpt-oss 1; 3 of the 6 cut off), and the retry recovered all 6, so 0 of 24 attacks failed to produce a
readable reply (5 of 24 before). The first-draft rate did not fall (6 of 24 against 5 of 24): gpt-oss
improved (3 of 12 to 1 of 12), while 3 qwen failures were short replies that were not cut off (39, 146
and 556 tokens) and had not appeared before. With 12 calls a fighter that is within noise, so the prompt
change is not shown to help; the retry is what works. The gate logs will show it: `truncated` is on
every such retry.

**Not done:** raising `turn_max_tokens` (Groq counts max_tokens toward its 8000 tokens-per-minute limit,
D-019), a per-model reasoning-effort setting, and the defender cap, which is a separate problem: all 32
hits in the 22 matches were defenders cut off at 2048 tokens. The gate metric is untouched.

**Cost:** an unreadable draft now costs a second call, which slows the run on Groq's limits.

**Alternatives considered:** only softening the prompt (the live check shows it does not remove the
failures); a larger `turn_max_tokens` (rejected in D-019); retrying twice (the one-retry contract of
D-025 holds).

## D-041 · 2026-11-06 · The gate metric stays; answer matching accepts arcsin, arccos, arctan

**Decision:** The slice 8 gate keeps its metric (D-037): the share of turns each role wins, where a
defender cut off at its token budget is a hit (D-024 set that budget on purpose to weaken the
defender). The 100-match re-check runs on the Groq pool (D-039) with the attacker retry (D-040), as
`arena sim --n 50 --no-panel --config config/gate-groq.toml --out runs/gate4.jsonl`, then on to 100 if
the 50-match check allows. The report should also show how many hits were cut-offs and how many were
finished wrong answers, taken from the logs (`timeout` against `defend_result`), so a pass can be read
for what it is. Separately, `answers_match` now accepts `arcsin`, `arccos` and `arctan` for SymPy's
`asin`, `acos` and `atan`: a defender who wrote `100*arcsin(3/5) - 48` against a stated
`100*asin(3/5) - 48` was scored wrong for the same value.

**Why:** the owner chose to keep the metric when shown the alternatives, on 22 matches of
`runs/gate3.jsonl`: current metric, attacker 24.2% of turns (95% interval 17.7-32.2%); cut-offs left out
of the turns, 5.7% (2.6-11.8%); verified attacks only, 38.6% hit rate (28.8-49.3%), or 10.5%
(4.9-21.1%) with cut-offs left out. The budget is part of the rules, so a cut-off is a legitimate hit.

**Correction to D-040:** its last paragraph says all 32 hits in those 22 matches were defenders cut off
at 2048 tokens. That is wrong: 26 were cut-offs (`timeout`, qwen 22, gpt-oss 4) and 6 were finished
replies scored wrong, of which one was the `arcsin` notation (now fixed), one had no `<answer>` tag and
one answered an attacker problem whose stated answer was the word `redesign`. At most 3 look like
genuine misses. D-040's retry change is unaffected.

**Known weakness, accepted:** a pass on this metric would be mostly "the defender ran out of budget",
which favours concise models (the D-019 caveat). The 6 finished-wrong hits are 7% of 83 verified
attacks, so the problems are still easy for a defender that finishes. Not addressed here: the attacker
accepting a non-numeric answer such as `redesign`, and a defender reply with no `<answer>` tag.

**Alternatives considered:** leaving cut-offs out of the turns (the gate would fail clearly at about
6-10%, which says problems are too easy and points at a prompt or rules change); verified attacks only
(drops backfires, which the attacker caused).

## D-042 · 2026-11-07 · Slice 8 waived by the owner; the gate run continues in the background

**Decision:** The owner waives the slice 8 gate so that slice 9 (ranked play and Elo) can be planned
and built, as D-026 did for Phase 0. The 100-match run (`runs/gate4.jsonl`, D-041) is not stopped: it
keeps going on the Groq pool and its result is recorded in PROGRESS.md when it ends. No rule changes.

**Why:** the run is limited by the free-tier rate limits (13 of 50 matches after about two days of
stalls, over 400 rate-limit retries), and every measurement so far has been about the measurement
itself. Latest numbers, 14 matches of `runs/gate4.jsonl` (with the D-040 retry and the D-041 matching
fix): attacker 31.0% of turns (95% interval 22.1-41.5%), defender 69.0% (58.5-77.9%), 32% backfires,
hit rate 45.6% of attacks that reached a defender. That is inside the 70% line but far from the
100 matches the gate needs, so it is a hint, not a pass.

**What this does not claim:** the gate has not passed. The D-041 weakness stands: a share of the hits
are defenders cut off at the token budget, which favours concise models, and small-model results do not
establish balance for stronger models (D-019). If the finished run lands outside the 70% line, the
rules are to be changed and logged then, and ranked play re-checked.

**Alternatives considered:** waiting for 100 matches before slice 9 (days of stalls, probable
inconclusive result); changing the rules first (a defender cap change would need its own measurement).

## D-043 · 2026-11-07 · Ranked play: Elo, closest-rating pairing, no new dependency

**Decision:** Slice 9 adds ranked play on plain Elo (`arena_api/ratings.py`, pure functions). A fighter
(not a version) starts at 1200 and K is 32; a win scores 1, a draw 0.5, a loss 0, and a rating changes
only when a ranked match finishes (a failed match changes nothing). A user queues a ranked match for
one of their fighters with `POST /fighters/{id}/ranked`; the server picks the opponent: another
owner's fighter whose latest version has passed a spar (so its key is known to work), whose provider is
still configured and which is under its daily cap, taking the closest rating, then fewer games, then
the lower id. Fighters of one owner are never paired (the collusion rule). Both versions are pinned when
the match is queued; the worker decrypts both owners' keys, plays the usual 6-turn match and stores the
result and both rating changes in one transaction that only runs for a match still `running`, so a
match cannot be rated twice. A ranked match counts against both fighters' daily caps. `GET
/leaderboard` is public (handle, fighter name, rating, record, last five results); a ranked replay
opens only for the two owners, as a spar does for its owner, because it shows personas. Migration 0005
adds the `ranked` match mode, the opponent columns and the `ratings` table.

**Why:** the plan's slice 9 is "two fighters are paired and rated automatically". Elo is the one
number to explain on a leaderboard and needs no state beyond the rating; the spec's Glicko-2 adds a
deviation to track and tune, which two or three fighters cannot make meaningful.

**Not done (spec items left out of the MVP):** weight classes, per-domain ratings, Glicko-2
deviation, flagging repeated result patterns between two owners, and any check that a fighter replied
in a ranked match (a fighter whose calls all time out still plays and loses). The gate behind this
slice was waived (D-042), so rating differences may partly reflect the roles rather than the fighters.

**Alternatives considered:** Glicko-2 now (extra state, no evidence it helps at this size); letting the
user pick the opponent (that is the spec's Challenge mode, later); rating by version (every edit would
reset the ladder).

## D-044 · 2026-11-07 · Sandbox for model-written code in the web worker (supersedes D-002 there)

**Decision:** The match worker runs every attacker snippet in a gVisor container
(`src/arena/sandbox.py`), through the `docker` command line (no new Python dependency): runtime `runsc`,
image `python:3.12-slim`, `--network=none`, `--read-only` with a 16 MB `noexec` tmpfs, 256 MB memory with
no swap, 1 CPU, 64 processes, all capabilities dropped, `no-new-privileges`, user 65534, nothing
mounted. The snippet goes in on stdin. Output is capped at 64 KB and the run is killed (and its
container removed) at the snippet limit plus a 10 s start-up allowance. The worker checks at start-up
that Docker has `runsc` (pulling the image if absent) and refuses to start otherwise; it never falls back
to the local subprocess silently. `ARENA_SANDBOX=off` is the explicit local-development escape: the
worker then logs a warning and runs snippets as in D-002. A Docker failure (exit 125) fails the match
with a clear reason instead of counting as a failed attack. The CLI (`arena match`, `sim`) keeps the local
subprocess of D-002, so Phase 0 behaviour and the free-tier runs do not change. `verifier` is split into
`run_local`, `judge` and `verify_attack`; the sandbox reuses `judge`, so both judge identically.

**Why:** in spars and ranked matches a user's persona steers a model that writes code, and that code
used to run on the server with the server's files and network. Containers share the host kernel; gVisor
puts its own user-space kernel between the snippet and the host. The spec asks for no network, CPU and
memory caps and a hard timeout.

**Not done:** Firecracker; a Dockerised worker (it would need Docker access of its own); sandboxing the
CLI; the SymPy parse of defender answers (`parse_expr` evaluates text, D-002), which still runs in the
worker and is the next hole to close; a per-user rate limit on sandbox runs. The sandbox is verified
against gVisor only where `runsc` exists: the tests that need it skip elsewhere.

**Alternatives considered:** Docker's default `runc` (shared kernel, weaker); a restricted Python
interpreter (known to be escapable); an external code-execution service (a new dependency and cost).

## D-045 · 2026-11-07 · Code strike: a second problem domain, off by default

**Decision:** A turn can be a code strike. `code_share` in `[settings]` (default 0.0, so nothing changes
until the owner sets it) is the chance a turn is code; it is drawn only when above 0, so seeded runs
keep their topics. The attacker writes a problem for a Python function `solve`, a reference
solution (`<code>`), 1 to 10 test inputs (`<tests>`, a JSON list of argument lists) and the expected
outputs (`<answer>`, a JSON list). Tests and outputs are JSON without floats, at most 20,000 characters
each; a reply that breaks this is an unreadable reply (D-040). The check mirrors math: the reference
solution is run on the inputs through `codestrike.harness`, and what it prints must equal the stated
outputs, or the attack gets the one retry (D-025) and then backfires. The defender sees only the
problem and replies with `<code>`; its function runs on the hidden inputs through the same harness and
scores 1 only if the printed outputs equal the expected ones, else 0 (crash, timeout, wrong output,
no code tag, or a reply cut off at the cap). The harness prints only results, so the expected outputs
never enter the sandbox and a defender's code cannot read them; `answers_match` compares two JSON
lists as canonical JSON (so `[1]` and `[true]` differ). Code and math use the same `verify` seam, so
the worker's code runs in gVisor (D-044) and the CLI's runs locally (D-002). The reference panel scores
math only: a code turn has difficulty 1.0, as backfires and sparring do. The log stays schema 2:
verified, retried and backfired code attacks add `domain` and `tests`; a code defender's `defend_result`
holds its code as `answer` and, on failure, `reason` (first 500 characters). Older logs are math.

**Why:** the spec lists the code strike as an MVP domain, and "every result is checked by code".
Reusing the verify seam and one binary score keeps the engine's rules (damage, backfire, retry) as
they are.

**Not done:** partial credit, float tolerance, panel difficulty for code (3 more sandbox runs a
problem), a web switch for the domain, per-test time limits (one limit covers the whole run), and any
balance measurement of the code domain: it is off in the shipped config until someone measures it.

**Live spot check (not a measurement):** two 4-turn matches, gpt-oss against qwen on Groq (the D-039
pool), `code_share` 1.0, seeds 7 and 11. None of the 8 first drafts verified; the one retry recovered 4
and the other 4 attacks backfired (stated outputs that the reference did not print, test inputs that were
not valid JSON, replies missing a tag). Of the 4 attacks that reached a defender: 1 block, 2 defenders cut
off at the 2048-token cap, 1 reply with no `<code>` tag. It also found a bug, fixed before the second
match: models copied the word `python` from the reply format into the code (3 of 4 first drafts in
the first match), which crashed the reference; the format no longer starts with it and a lone leading
`python` line is dropped (this also applies to math). So with these small models a code turn is mostly
an attacker format or arithmetic failure, which is a reason to keep `code_share` at 0 for now.

**Alternatives considered:** putting the expected outputs in the harness and printing PASS (the
defender's code could read them); a separate `verify_code` seam (the existing one already fits);
comparing outputs with SymPy (lists do not parse as expressions).

## D-046 · 2026-11-07 · Open source: public MIT repository on GitHub

**Decision:** The project is released as open source at `github.com/aum2606/agent-arena` under the MIT
license (the owner's choice, 2026-11-07). The existing history of 109 commits is published unchanged,
including the author email on every commit (the owner chose to keep it). The repository gets a README,
CONTRIBUTING, SECURITY and CODE_OF_CONDUCT files, issue and pull-request templates, a `.gitattributes`
(`* text=auto`, so the repository keeps LF) and a GitHub Actions workflow (`.github/workflows/ci.yml`)
that runs the same checks as the pre-commit hooks plus pytest against a throwaway Postgres, and the web
typecheck, tests and build. The gVisor tests skip in CI (the runner has no `runsc`). The workflow uses
the GitHub actions `checkout`, `setup-uv` and `setup-node`; nothing is added to the runtime. Work
arrives by pull request from forks or branches into `main`, which should require CI to pass. Releases
are not tagged yet: Phase 0 closed without its gate (D-026) and the MVP is not finished.
Before publishing, the whole history and the tracked files were searched for provider keys, tokens,
private keys, `.env` files, `runs/` and personal paths: none were found.

**Why:** the owner wants anyone to be able to try the project, contribute and help build it. A license is
required for others to use or change the code, and CI plus templates keep outside contributions to the
same standard as `CLAUDE.md`.

**Disclosed, not hidden:** SECURITY.md and the README state the known problems: the answer parser still
evaluates text from a model reply in the worker (D-002, D-044), the CLI does not sandbox code, the
local Docker stack is not safe to expose, and the balance gate was waived (D-042). The first item of the
launch-hardening slice closes the parser hole.

**Left for the owner (GitHub settings the repository files cannot set):** turn on private vulnerability
reporting, require the CI checks and a review before merging into `main`, delete head branches after
merge, and set the repository description and topics. The CI workflow has not run on GitHub yet; it was
checked by running its commands locally and parsing its YAML.

**Alternatives considered:** Apache-2.0 (patent grant) and AGPL-3.0 (hosted forks must share changes)
were offered and not chosen; rewriting the history to a GitHub no-reply email (offered, declined);
squashing the history into one commit (loses the record the decision log refers to).
