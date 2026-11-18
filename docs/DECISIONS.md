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

## D-047 · 2026-11-07 · Answers are read, never evaluated (supersedes the parser part of D-002)

**Decision:** `answers_match` no longer uses `sympy.parse_expr`. `arena.safe_expr.parse_answer` reads the
text with Python's `ast` and builds the SymPy value bottom-up; nothing is ever passed to `eval`. It
accepts only: integers and decimals; the operators `+ - * / % ** ^` (`^` is a power) and brackets;
single-letter variables; the constants `pi E I oo GoldenRatio EulerGamma Catalan`; and calls to a fixed
list of functions (roots, `exp`, `log`/`ln`, trigonometric and hyperbolic functions with `arcsin`,
`arccos`, `arctan` as spellings of `asin`, `acos`, `atan`, `gcd`, `lcm`, `Abs`, `floor`, `ceiling`,
`sign`, `Mod`, `Max`, `Min`, `Rational`, `Integer`, and `factorial`, `binomial`, `gamma`, `zeta`). Anything
else is refused: attribute access, subscripts, strings, comprehensions, lambdas, keyword arguments, other
names (`xy`, `theta`, `True`), underscores, `!`, and `1/0`. Limits: 200 characters, 150 syntax-tree
nodes, a numeric exponent of at most 100,000 (200 when the base has a variable), no power with more than
100,000 estimated digits, a number passed to a function of at most 1,000 digits, and `factorial`,
`binomial`, `gamma` and `zeta` of nothing above 10,000. A refused answer is an answer that does not
match, so a defender who sends one scores 0, and an attacker whose snippet prints one fails its check.
`n!` is no longer read: the answer format now says to write `factorial(n)`. Applies to the CLI, the
panel and the worker alike.

**Why:** the old parser ran a model's reply as Python in the worker, which holds the database URL, the
provider keys and the encryption secret, and users control their fighters' personas (found and probed
safely on 2026-11-07: a reply changed an environment variable of the process). It also hung on `9**9**9`,
`99999999!` and `factorial(10**8)` for more than 10 s each, which would stall the single worker.

**Checked against the data:** all 186 stored battle logs, 273 distinct math answer strings, 706 scored
defences. 272 strings parse. The one refused is `redesign`, an attacker's stated answer that the old
parser accepted as a variable (the weakness noted in D-041); it now fails the attacker's own check. The
new scores agree with the stored ones on 705 of 706; the one difference is the `arcsin` scoring bug
already fixed in D-041. (`zeta(3)` was refused until `zeta` was added with its size guard.)

**Not solved:** comparing two accepted answers still calls `sympy.simplify`, which can be slow on a
200-character expression of nested functions; nothing times it out, and the arq job timeout (one hour)
is the only backstop. Answers written with names outside the list (`theta`, `phi`, `fibonacci(n)`) are
now wrong answers; add a name here with a test if a real problem needs it.

**Alternatives considered:** keeping `parse_expr` behind a character whitelist (still evaluates, and the
hang remains); running the comparison in a killable child process (the right answer if `simplify`
proves slow; about a 2 s start-up per call without a long-lived helper); a regular-expression grammar
(cannot bound the size of what it builds).

## D-048 · 2026-11-07 · The compose worker runs with the sandbox off

**Decision:** `docker-compose.yml` sets `ARENA_SANDBOX` for the worker to `${ARENA_SANDBOX:-off}`. A
public deployment must not use the compose worker: it runs the worker on a host with gVisor (D-044).

**Why:** since D-044 the worker checks for the gVisor runtime at start-up and refuses to start without
it. The compose worker's container has no Docker, so it exited at once; this was found by reading the
compose file on 2026-11-07, after D-044 wrongly implied the worker was not in compose. Giving the
container the host's Docker socket would make it root-equivalent on the host, which is worse than the
local-only risk of the stack, which already enables a sign-in-as-anyone form (D-033).

**Alternatives considered:** no change (the stack's worker never starts); mounting the Docker socket (see
above); dropping the worker from compose (the local stack could then not play a match).

## D-049 · 2026-11-07 · Problems reach the defender as delimited data; fouls backfire

**Decision:** Two changes to what a defender sees and what an attacker may send.
(1) The defender's user message now holds the problem between `<problem>` and `</problem>` lines, the
reply format stays last, and the system rules say that the problem is untrusted data and that any order
inside it (ignore these rules, reveal your instructions, give a fixed answer) is part of the problem.
Any `<problem>` or `</problem>` tag inside the text is replaced by `[tag removed]`, so a problem cannot
close its own delimiter. This covers math, code and the reference panel alike.
(2) `moderation.check_problem` runs on every problem once its attack has verified. A problem is a foul if
it is empty, over 4,000 characters, contains zero-width, directional or control characters, or matches a
rule for text aimed at the opponent: telling it to ignore or override its instructions or rules, asking
it to reveal its system prompt, instructions, persona or key, or redefining its role ("you are now",
"new instructions", "developer mode", "jailbreak"). A foul is a backfire: the attacker takes half the
damage, the defender is never asked, there is no retry, and the `backfire` event keeps the problem with
the reason `foul: ...`. It applies in every mode, not only ranked (the spec calls it a ranked foul; one
rule is simpler and the filter never fires on real play).

**Why:** a problem is text one user's model writes and another user's model reads. The spec asks for
delimiters and a filter for problems that try to instruct the opponent.

**Checked against the data:** 441 distinct logged problems: the instruction rules flagged none; the
length limit flagged 2, both rambling problems of more than 4,000 characters (the maximum was 8,378; the
99th percentile is 1,512).

**Not done, and not measured:** this is a rule filter, not a content moderator: it knows nothing of
hateful, sexual or violent text (that needs a classifier or a paid API), and a paraphrased instruction
gets past it. Delimiters lower the chance that a model obeys a problem; they do not remove it. The new
defender wording was not measured for its effect on how often defenders solve problems (slice 8's gate
is waived, D-042). Reference solutions and hidden tests are not shown to the defender, so they are not
filtered.

**Alternatives considered:** a model-based classifier on every problem (cost and free-tier limits on
the hot path); filtering only in ranked matches (two rule sets); stripping the offending sentence instead
of a foul (the attacker would profit from trying).

## D-050 · 2026-11-07 · Per-user rate limits, error pages and response headers

**Decision:** The routes that write or spend are limited per signed-in user with a Redis counter
(`arena_api.limits`; `SET` with a lifetime, then `INCR`, so a counter always expires): creating a fighter
20 a minute, adding a version 100 a day, a spar 10 a minute, a ranked match 10 a minute. Past the limit
the answer is 429 with `Retry-After`. Reading is never limited. If Redis fails the limiter lets the request
through and logs a warning (no match can be queued then either, and the existing per-user and per-fighter
daily caps still apply). The web app gets `error.tsx`, `global-error.tsx` and `not-found.tsx` (no error
text is shown to the visitor), the leaderboard page shows "The API is unreachable" like the replay list,
and every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin` and a `Permissions-Policy` that turns off the camera,
microphone and location.

**Why:** the plan's launch-hardening slice asks for rate limits and error pages, and a small group will
share one worker and the free tiers.

**Not done:** limits for visitors who are not signed in (the sign-in routes only redirect to GitHub or
check its answer); a Content-Security-Policy (Next injects inline scripts, so a policy needs nonces);
`Strict-Transport-Security` and HTTPS (the reverse proxy in front sets those); limits per IP (behind a
proxy every visitor shares one address unless forwarded headers are trusted).

**Alternatives considered:** an in-process counter (wrong with more than one API process and lost on a
restart); a limiter library (a dependency for 30 lines); failing closed when Redis is down.

## D-051 · 2026-11-08 · A ranked match with a silent fighter is void; shorter job timeout (supersedes a "not done" of D-043)

**Decision:** A ranked match in which either fighter's model never answered is marked `failed` with a
reason naming the silent fighter ("... got no reply from its model, so the match was not rated: check the
key and the model") and rates nobody. A fighter "answered" if it has a verified or retried attack, a
defence result, or a defence cut off at the token cap. To tell that cut-off from a model that never
answered, the defender's `timeout` event now carries `truncated: true` when a reply came back and
`false` for a real timeout (an additive log field; older logs have neither, and so count as silent).
Sparring uses the same definition to decide whether a spar verifies a fighter's key, so a spar whose
only replies were cut off now verifies it (the key and model do work). The worker's job timeout is
1,800 s instead of 3,600 s: past half an hour a match is stuck, and one worker serves everyone.

**Why:** D-043 left it open that a fighter whose calls all time out still plays and loses. A user with a
dead key or an overloaded model lost rating, and the opponent gained it for a match nobody played. The
match still counts toward both fighters' daily caps, since it used a queue slot and calls.

**Not done:** a fighter that answers once in six turns is still rated; the failed match is not
retried; its log is not kept (`failed` matches store only the reason).

**Alternatives considered:** rating a forfeit as a loss for the silent side (punishes a transient
outage); requiring a minimum number of answers (a number nobody has measured).

## D-052 · 2026-11-08 · Answer comparison runs in a helper process with a time limit (adds to D-047)

**Decision:** `sympy.simplify` is no longer called in the worker's own process. `arena.equality` keeps
one long-lived helper process (started on first use with the `spawn` method, so it behaves the same on
Windows and Linux) that reads two answers, runs `parse_answer` and `simplify`, and sends back the result.
If it does not answer within 5 seconds the parent kills it and the answer counts as not equal; the
next comparison starts a fresh helper (about 2 to 3 s, SymPy's import). A helper that died is replaced the
same way, comparisons are serialised with a lock, and a helper that cannot start raises `ConfigError`,
which fails the match with a clear reason. `answers_match` keeps the JSON-list comparison in the parent
and sends everything else to the helper. The CLI, the panel and the worker all use it.

**Why:** D-047 made answers safe to read but left comparison unbounded. `(x+1)**200*(x+2)**200*(x+3)**200`
is 32 characters, passes the parser (an exponent of 200 is allowed when the base has a variable) and
kept `simplify` busy for more than 25 s; because the worker plays one match at a time, one crafted
answer stalled everyone. SymPy cannot be interrupted, so only a process can be stopped.

**Cost and limits:** a hostile answer still costs the worker about 8 s (5 s limit plus the restart),
and an honest answer that simplifies slowly (the slowest seen took about 2 s) is safe under the limit but a
slower one would count as wrong. The helper adds a process of roughly 100 MB. Not done: a per-user limit
on how many slow answers a defender may send.

**Alternatives considered:** a smaller exponent cap (does not stop other slow shapes); a thread with a
timeout (the thread keeps burning CPU); a new process per comparison (2 to 3 s each); replacing
`simplify` with a numeric check (wrong for symbolic answers).

## D-053 · 2026-11-08 · The comparison helper is a plain subprocess (supersedes the mechanism in D-052)

**Decision:** `arena.equality` starts its helper with `subprocess.Popen([python, "-m", "arena.equality"])`
and talks to it in JSON lines over the pipes (ASCII only, so no pipe encoding can fail), instead of a
`multiprocessing` spawn process. A reader thread feeds the helper's lines into a queue so the parent can
wait with a time limit on every platform. The helper gets a minimal environment (the Windows
`SYSTEMROOT` and a `PYTHONPATH` to the package, no provider keys, no database URL), its stdout is
reserved for the protocol, and it is killed at exit and replaced when it dies or runs past 5 s.
Everything else in D-052 (the 5 s limit, one helper, the lock, `ConfigError` if it cannot start) stands.

**Why:** found by running a live-match script on Windows: `multiprocessing`'s spawn method re-runs the
caller's main script in the child, so any script without an `if __name__ == "__main__"` guard made the
helper fail to start (and, in the worst case, re-ran the script's top level in the child). The `arena`
CLI, uvicorn, arq and pytest have guards, so no shipped entry point was hit, but anyone using the
library from a plain script would have been.

**Not done:** if the parent is killed outright while a comparison is running, that one helper keeps
running until the comparison ends, then exits when its input closes.

**Alternatives considered:** a `multiprocessing` process with a guard documented for users (a trap for
every script); the `fork` method (not on Windows).

## D-054 · 2026-11-08 · CI runs the sandbox tests under gVisor

**Decision:** `.github/workflows/ci.yml` has a third job, `sandbox`, that installs gVisor (`runsc`) on the
runner from gVisor's own apt repository, registers it with Docker, and runs `tests/test_sandbox.py` with
skips treated as a failure. The Python job still skips those tests (it has no `runsc`).

**Why:** until now the claim that snippets cannot reach the network, the disk or other processes had been
checked only by hand in one WSL distro. A sandbox that is not tested on every change is not one to
rely on.

**Not verified when written:** the job could only be proved by running it on GitHub's runners (the same
install steps work in the Ubuntu 24.04 WSL distro). If a runner cannot run gVisor, the job fails and this
entry is to be superseded, not hidden.

**Alternatives considered:** a self-hosted runner (the owner's PC, kept on); leaving the tests skipped in CI.

## D-055 · 2026-11-12 · A fighter may set how hard its model thinks (`reasoning_effort`)

**Decision:** `Fighter` (and so every `[[fighters]]` and `[[panel]]` entry) takes an optional
`reasoning_effort`. When set, it is sent to the provider unchanged in the request body (`extra_body`,
because the SDK's typed field rejects values such as qwen's `none`); when unset the request is exactly
what it was. The allowed values differ by model (Groq gpt-oss: low, medium, high; Groq qwen3.8-27b: none,
default, low, medium, high; Gemini 3.1 Flash-Lite: minimal, low, medium, high), so the config holds a free
string and a wrong value comes back from the provider as a plain HTTP 400. The battle log header records
each fighter's setting. `config/gate-groq.toml` sets `low` for gpt-oss and leaves qwen at the provider
default. `config/fighters.toml` and fighters made in the web app are unchanged.

**Why:** in the 14 matches of `runs/gate4.jsonl` (84 turns), 27 turns were decided by a token cap: 16 of
the 26 hits were defenders cut off at 2,048 tokens and 11 of the 27 backfires were attacker replies cut
off at 4,096 before any code (D-040). Both Groq fighters are reasoning models and their hidden thinking
counts against `max_tokens` (`output_tokens`, D-037). Groq's 8,000 tokens per minute also counts each
request's `max_tokens`, so this is also what makes the sim wait on 429s.

**Measured (small, a spot check, not a balance run):** real attack calls with the real prompts, 3 topics
per setting. gpt-oss: default 1 of 3 cut off (2,490 / 4,096 / 1,656 tokens), `low` 0 of 3 (859 / 262 / 216).
qwen: default 0 of 3 cut off (857 / 1,424 / 291), `low` 2 of 3 cut off at 4,096, `none` 1 of 3. So `low`
helps gpt-oss and did not help qwen (it looked worse; three calls cannot say how much). The planned
10-match run did not finish: Groq's rate limit allowed one match in about two hours (it had `low` on both
fighters: 3 of 3 qwen attacks cut off, defender replies 918 / 923 / 1,316 / 2,048 tokens), so it was
stopped. That match is the only whole-match evidence and it is one match.

**Not done:** the cut-off share per 84 turns with the shipped settings has not been measured; the token
caps are unchanged; the panel does not set an effort (it scores difficulty, D-036). Whether qwen
needs `none`, `medium` or a larger cap is open, as is a different effort for attacking and defending (a
balance lever, the owner's call).

**Alternatives considered:** one effort for every fighter (the qwen probe says no); lowering the caps first
(would turn more replies into cut-offs before the effort is known to help); counting a cut-off as a
no-contest turn (a rule change, left to the owner).

## D-056 · 2026-11-12 · Replays read only the fighter fields they show (corrects a claim in D-055)

**Decision:** `arena_api.replays` builds each replay's fighter info from the four fields it shows (name,
provider, model, persona) instead of unpacking the whole log header entry. A header may carry more.

**Why:** D-055 added `reasoning_effort` to the log header. I wrote then that readers ignore the extra
field, but I had only checked the web app. `parse_replay` unpacked the header into `FighterInfo`, so
every replay of a match made after D-055 failed with "unreadable" (commit 0ac2334 on `main`; the CI
Python job failed on it). The tests that showed it need Postgres and skip on the Windows PC, so the local
full run passed. The full suite now also runs on Linux with Postgres before a push, and a database-free
regression test covers this case.

**Alternatives considered:** keeping `reasoning_effort` out of the log header (loses the record of what
each match ran with); adding the field to `FighterInfo` (shows a setting nobody asked to see).

## D-057 · 2026-11-12 · qwen keeps the provider's default reasoning effort; effort does not fix its cut-offs

**Decision:** `config/gate-groq.toml` is unchanged: qwen (`qwen/qwen3.8-27b`) sets no `reasoning_effort`.
None of the three settings tried brings its token cut-offs near the 10% target set when this was planned.

**Why:** in `runs/logs_gate4` (14 matches, no effort set) qwen's first attack drafts were cut off in 13 of 42
(31%) and its defences ran into the 2,048-token cap in 13 of 37 (35%); gpt-oss was 5 of 42 (12%) and 3 of
20 (15%). To see whether effort changes that, qwen made 15 real attack calls and 15 real defence calls
at each of three settings (real prompts, real verified math problems from earlier logs, settings
interleaved; `qwen/qwen3.8-27b` on Groq, 2026-11-12):

| setting | attack: cut off at 4,096 / did not parse | defence: cut off at 2,048 / did not parse |
|---|---|---|
| default | 3 / 4 of 15 | 4 / 6 of 15 |
| `none` | 2 / 5 of 15 | 4 / 4 of 15 |
| `low` | 13 / 13 of 15 | 4 / 4 of 15 |

Median output tokens: attack 1,339 (default), 868 (`none`), 4,096 (`low`); defence 1,189, 1,229, 1,007.
`low` is clearly worse for attacks (13 of 15 cut off). Default and `none` are not told apart by 15 calls
each, and neither can be told from the 31% baseline with this many (3 of 15 against 13 of 42 could be
chance). Defence cut-offs are 4 of 15 at every setting, so effort does not move them. Some replies end
under the cap and still lack a required tag (for `none` attacks, 5 did not parse and only 2 were cut off),
so a bigger cap would not fix all of it.

**Not known:** why. The likeliest cause is qwen's visible working-out (D-040 saw replies of 9,600 and
13,900 characters), but the replies were not kept, so this is a guess. The next step is to read some
(save the text of cut-off and unparsed replies) and then change the prompt, the cap for this one model, or
the model; each is its own plan. gpt-oss keeps `low` (D-055), the only measured gain: 0 of 3 cut off
against 1 of 3 at the default, which is itself a spot check.

**Alternatives considered:** `none` for qwen (no better than default on these counts and untested against
the real match flow); `low` (worse); a larger cap for qwen (a new per-fighter setting, and Groq's 8,000
tokens-per-minute limit counts the cap on every request).

## D-058 · 2026-11-12 · qwen's cut-offs are visible working-out, not hidden thinking

**Decision:** No code or config change. This records what qwen's failing replies contain, so the next fix
is chosen on evidence (D-057 left the cause open).

**Evidence:** qwen (`qwen/qwen3.8-27b` on Groq, default effort, the shipped prompts, real math problems)
made calls whose full replies were kept; 20 of a planned 24 had been collected when this was written
(attacks 11 incl. 1 connection error, defences 10; the rest were still waiting on Groq's rate limit).
- The `reasoning` field was empty on every call and Groq reported no reasoning tokens: qwen at the default
  setting does not think in hidden tokens.
- Attacks: 3 of 10 answered calls were cut off at 4,096 tokens, with 8,700 to 10,600 characters of design
  notes and trial arithmetic before any tag; none reached `<problem>`, `<answer>` or `<code>`. A fourth
  failure was not a cut-off: all tags present but `<answer></answer>` empty.
- Defences: 5 of 10 were cut off at 2,048 tokens (3,800 to 4,800 characters). Each had already solved the
  problem and was re-checking it ("Matches.", "Let's re-verify") when the cap hit, so `<answer>` never came.
- Both prompts already tell the fighter to keep its working short (`ATTACKER_RULES`, `DEFENDER_RULES`);
  qwen does not follow that.
- Together with D-057 (4 of 15 defences cut off at every effort setting), the effort setting cannot fix
  this; the length is in the visible answer.

**Not known:** how the 4 unfinished calls would count; the share is from about 10 calls per role, enough to
name the kind of failure but not to rank fixes. A defender that outruns its token budget loses by the
game's rules, so for a defence this is partly the rule working as designed; for an attack, a cut-off costs
a backfire (D-040).

**Options, each its own plan:** (1) a different second fighter for balance runs, since qwen's cut-offs
measure verbosity, not skill; (2) an answer-first reply format (the final answer in tags before any
working), which loses the cut-off but may cost accuracy for a model that thinks aloud; (3) a larger cap
for this one model (a per-fighter setting; Groq's 8,000 tokens per minute counts the cap on every
request); (4) one follow-up call asking for just the final answer after a cut-off (more tokens per turn).

**Alternatives considered:** treating the cut-offs as qwen's loss and doing nothing (leaves the balance
numbers measuring verbosity).

## D-059 · 2026-11-12 · Balance runs use gpt-oss against gemini-lite (`config/gate-mixed.toml`), not qwen (supersedes the pool in D-039)

**Decision:** `config/gate-mixed.toml` is the fighter pool for balance runs:
`arena sim --config config/gate-mixed.toml --no-panel`. It pairs `gpt-oss` (openai/gpt-oss-120b on Groq,
`reasoning_effort = "low"`, D-055) with `gemini-lite` (gemini-3.1-flash-lite on Gemini, default effort), with
the personas from `config/fighters.toml`. `config/gate-groq.toml` stays as the record of the runs in
`runs/gate3.jsonl` and `runs/gate4.jsonl`; no further runs should use it. `config/fighters.toml`, the house
bot and the panel are unchanged.

**Why:** qwen's replies were cut off in 31% of attacks and 35% of defences in the gate4 matches, and in a
fresh test (D-058) 3 of 11 attacks and 5 of 12 defences, because it writes its working out at length and
ignores the instruction to keep it short; no reasoning setting fixes that (D-057). A balance run with qwen
measures its verbosity, not role balance. Groq offers no other usable family: its chat models are
gpt-oss-120b, gpt-oss-20b, gpt-oss-safeguard-20b, qwen3.8-27b and a 4,096-context allam model, so a second
family has to come from Gemini.

**Measured (12 attack and 12 defence calls per candidate, the same 12 verified math problems for every
defence, 2026-11-12):**

| fighter | attacks: errors / cut off / unparsed | defences: cut off / correct |
|---|---|---|
| qwen, default | 1 / 3 / 4 of 12 | 5 / 7 of 12 (cut-offs count as wrong) |
| gpt-oss-20b, `low` | 8 / 0 / 0 | 0 / 9 of 12 |
| gemini-3.1-flash-lite, default | 1 / 0 / 0 | 0 / 11 of 11 (1 call timed out) |

gemini-3.1-flash-lite was never cut off and answered every defence it returned correctly; its two errors
were one "Request timed out" per role. gpt-oss-20b was rejected as an attacker: on 8 of 12 attacks Groq
returned HTTP 400 "Tool choice is none, but model called a tool" (the model called a tool nobody offered),
which our client treats as a hard error. A user's fighter on that model would probably hit it too; not
tested, not part of this decision.

**Smoke match on the new pool** (one match, `gpt-oss` first, no panel): finished, gpt-oss won 90 to 70 by
decision. No reply was cut off. Both backfires were an attacker whose stated answer differed from its
snippet's output (the D-025 problem, not the token cap). Gemini returned HTTP 503 nine times (retried), and
one Gemini defence timed out and was scored a hit: a provider that is slow or overloaded loses turns on the
Gemini side, which D-039 had already moved the pool away from.

**Not known:** the replies were checked for format only, not how often Gemini's attacks verify or how hard
its problems are (D-017 found it repeating easy ones); 12 calls per role names the kinds of failure, not
exact rates; a Gemini overload can bias a run against it, and the sim only replays a match when the provider
is unreachable (D-038), not for a timeout.

**Alternatives considered:** gpt-oss-120b against itself under two personas (removes the strength
difference, shares one Groq token budget, so slower; untested); keeping qwen (cut-offs measure verbosity);
gpt-oss-20b as the second fighter (cannot attack).

## D-060 · 2026-11-13 · First balance measurement on the mixed pool: the defender still wins about 78% of turns, and tokens are no longer the cause

**Decision:** No code or rule change. This records the result of `arena sim --n 30 --no-panel
--config config/gate-mixed.toml --out runs/mixed.jsonl` (D-059), so the next balance decision rests on it.
The slice 8 gate stays waived (D-042); this is not a gate run.

**Result (29 of 30 matches, 174 turns, 2026-11-12):** the 30th match was rate limited by Groq on all three
attempts (8 retries and a 300 s wait each, D-038) and the sim stopped; the 29 saved matches are intact and
the run can be resumed.
- Attacker won 22.4% of turns (39 hits, 95% interval 16.9% to 29.2%); defender 77.6% (85 blocks and 50
  backfires, 70.8% to 83.1%). The gate verdict is "cannot pass": the defender's lower bound is above 70%.
- Backfires were 28.7% of turns: gemini-lite 36% of its 87 attacks, gpt-oss 22% of its 87. A backfire is
  an attacker whose stated answer differs from its snippet's output (D-025), not a token cut-off.
- Of attacks that reached a defender, 31.5% hit. Matches: gpt-oss 18, gemini-lite 10, 1 draw; 28 ended by
  decision, none by KO; average length 6.0 turns.
- Token cut-offs: 1 of 174 turns (a gpt-oss reply), against 27 of 84 turns in the qwen runs (`runs/gate4.jsonl`).
  All 39 hits are wrong or missing answers; in `gate4`, 16 of 26 hits were defenders cut off at their cap.
- Timeouts: 1 real defender timeout (gemini-lite, no reply) and 2 attacker timeouts logged without the
  flag. Leaving the real-timeout turn out moves the shares by 0.4 points (attacker 22.0%, defender 78.0%).
  The timeout rule (a defender that does not answer in time scores 0, an attacker backfires) stays.

**Why it matters:** the attacker's 22.4% matches what the scripted-fighter study predicted (D-020): with
no attacker advantage its best case is about 22 to 25% of turns, so the 70% gate cannot pass however the
fighters behave. The earlier skew toward the defender was partly tokens (cut-offs fed hits in the qwen
runs) and is now mostly the rules. The levers D-020 found were an attacker bonus of 0.1 and problems pitched
near the defender's skill (31 to 33% attacker wins, at the cost of 30 to 48% backfires). Choosing among
them is a design decision for the owner; it is not made here.

**Not known:** a 29-match, two-fighter sample, one model pair; no panel, so every difficulty is 1.0; Gemini's
problem quality and variety were not measured (D-017); whether Groq stopped on its per-minute or a daily
limit is not shown by the log. These are the results, not a balance verdict for other model pairs.

**Alternatives considered:** running to 100 matches for the formal gate (it cannot flip the verdict at the
observed rates and spends the free-tier budget); treating the result as a token problem (the data says it
no longer is).

## D-061 · 2026-11-13 · A reply Groq rejects as a failed tool call is an unreadable reply, not a failed match

**Decision:** `LlmClient` treats an HTTP 400 whose error `code` is `tool_use_failed` as a reply with no
text (`Completion("", truncated=False)`) instead of raising `LlmError`. The orchestrator then handles it as
any unreadable attack reply: one retry (D-040), then a backfire; a defender's empty reply scores 0. Every
other 400 (a bad key, a bad request) stays a hard `LlmError`. The code, not the message, is matched. There
is no retry inside the client: the unreadable-reply retry is the retry.

**Why:** gpt-oss models on Groq sometimes write their reply as a call to a tool named `python`, which
nobody offered (the attack prompt asks for a Python snippet), and Groq answers 400 `tool_use_failed` with the
attempted call in `failed_generation`. Before this, the first such 400 aborted the whole match: a spar failed
and its fighter was not verified, a ranked match failed and rated nobody (D-051), and the opponent's slot
was wasted. Web fighters never set `reasoning_effort` (the setting from D-055 is only in the config
files), so users get the provider's default. Probe, 8 real attack calls per cell, 2026-11-13:

| model and effort | 400 errors | repeat of the same call worked | OK calls that parsed |
|---|---|---|---|
| gpt-oss-20b, default | 5 of 8 | 2 of 5 | 0 of 3 (all 3 cut off at 4,096) |
| gpt-oss-20b, medium | 6 of 8 | 3 of 6 | 0 of 2 |
| gpt-oss-20b, high | 0 of 8 | n/a | 0 of 8 (all cut off) |
| gpt-oss-20b, low | 5 of 8 | 3 of 5 | 3 of 3 |
| gpt-oss-120b, default | 0 of 8 | n/a | 6 of 8 |

Every error body had the same code. The 120b model never failed this way.

**Checked live:** one match, gpt-oss-20b on both sides at the default effort, finished (before this it would
have failed on the first 400); 5 of its 6 attacks backfired with "missing or empty `<code>`".

**Not fixed, and not claimed:** gpt-oss-20b stays a poor attacker whatever the client does: at the default
effort its answers that do arrive are mostly cut off. A user's fighter on it will lose most attacks. A
fighter whose every reply is unreadable still counts as having replied under D-051 (a retried attack is a
reply), so a ranked match with it is rated, not voided: it loses rating, as a model that writes garbage would.
Defences on this model were not probed at the default effort.

**Alternatives considered:** retrying the same request once inside the client (the repeat worked in 8 of 16
tries, and the caller already retries); matching the message text (brittle); keeping the hard error (a clear
message for the owner, but a wasted match for the opponent); offering the model a tool so the call is
accepted (changes the request for every model).

## D-063 · 2026-11-14 · Visitors are rate limited per address on the routes anyone can reach

**Decision:** `/replays`, `/replays/{id}`, `/leaderboard` share a "read" allowance of 60 requests a minute per
visitor address, and the GitHub sign-in routes (`/auth/github/login`, `/auth/github/callback`) a "login"
allowance of 20 a minute (`VISITOR_RULES` in `src/arena_api/visitor_limits.py`). Counting is the same Redis
counter as the signed-in write limits (D-050) and fails open the same way; past the limit the answer is 429
with `Retry-After`. The per-page session check (`/auth/me`), `/auth/config` and `/health` are not counted.
The numbers are guesses, not measured.

The address: the API only ever sees the web server (the browser talks to the Next origin, which relays `/api`
and fetches server-side), so the deployer names a header in `CLIENT_IP_HEADER` that their reverse proxy
**overwrites** with the visitor's address (X-Real-IP, CF-Connecting-IP, ...). The API uses it only if it is
exactly one valid address; unset, malformed or a list falls back to the connection, so a made-up header
cannot buy a fresh allowance. The web server passes that header on in its server-side fetches
(`web/lib/client-address.ts`) and the `/api` relay already carries it. `CLIENT_IP_HEADER` is in `.env.example`
and `docker-compose.yml` for both services.

Code: the limiter and the shared counter (`count_request`) live in `visitor_limits.py`; `get_queue` moved from
`match_routes.py` to `deps.py`, because the auth routes need the limiter and `limits.py` imports auth (a cycle
otherwise); `limits.py` now calls `count_request`.

**Checked** (production web build, the API and Redis in WSL, the web server with `CLIENT_IP_HEADER=x-real-ip`):
through the `/api` relay a request with `X-Real-IP: 198.51.100.7` counted under that address; a page fetched
with `X-Real-IP: 198.51.100.8` counted under that address (the server-side path); a request with no header or
`not-an-address` counted under the connection address. Unit tests cover the limit, per-address and per-rule
counting, the fallback cases, the Redis outage and the real sign-in routes; the read-route test needs
Postgres and ran on Linux.

**Not safe to ignore:** with `CLIENT_IP_HEADER` unset every visitor shares the web server's address, so one
allowance serves the whole site (fine for one person on localhost, wrong for a public site); a header the
proxy passes through instead of overwriting lets a visitor pick their address; behind a tunnel or proxy that
cannot set a header there is no per-visitor limit at all. A page whose server-side fetch is refused shows the
error page. No hosting is chosen yet, so none of this has met a real proxy.

**Alternatives considered:** leaving per-address limits to the reverse proxy (needs no code, but hosting is
undecided and Redis is already here); parsing `X-Forwarded-For` (which hop to trust depends on the proxy
chain, and a wrong guess is spoofable); limiting by the web server's own address (one flood would lock out
everyone).

## D-064 · 2026-11-14 · A Content-Security-Policy with a nonce per request

**Decision:** `web/proxy.ts` (Next 16's name for middleware) gives every page request a fresh nonce and sends
`Content-Security-Policy` built by `web/lib/csp.ts`: `default-src 'self'`; `script-src 'self'
'nonce-<n>' 'strict-dynamic'` (plus `'unsafe-eval'` in development only, where React needs it); `style-src
'self' 'nonce-<n>'`; `img-src 'self' blob: data:`; `font-src 'self'`; `object-src 'none'`; `base-uri 'self'`;
`form-action 'self'`; `frame-ancestors 'none'`. It does not run for `/api`, built assets, the icon or link
prefetches. There is no `upgrade-insecure-requests`: HTTPS belongs to the reverse proxy (D-050) and the
directive would break plain-HTTP localhost. `web/lib/stage.ts` imports `pixi.js/unsafe-eval`, Pixi's build
that makes no eval calls, so the replay viewer still draws without `'unsafe-eval'`. Every page was already
dynamically rendered, which nonces need. D-050's "no policy yet" is superseded.

**Checked** in the browser pane on a local production build (the stack, the old gate replays and a stub
model behind it): home, a replay (the Pixi canvas was created at 900 by 400 and drew both fighters and the
turn buttons; "Play match" ran), leaderboard, login, signed-in fighters list, new-fighter form, a fighter's
page and a real spar through the worker (the fighter was verified). The browser console held no violation
from any of them. Controls showed the console does report violations and the policy bites: an external
image, an inline event handler and a `javascript:` link were each blocked and reported. A script element
created through the DOM ran, as `strict-dynamic` allows by design (the browser cannot tell who created it);
markup an attacker injects stays inert.

**Not checked:** Firefox and Safari (only the Chromium-based pane); HTTPS or any real proxy; the standalone
server that the Docker image runs (`node server.js`) as opposed to `next start`, though the proxy file is
part of the build; the GitHub sign-in round trip; development mode under the policy. One thing found
on the way: the `/api` relay's target (`API_URL`) is fixed when the app is built, so a build made without it
relays to `localhost:8000`; the Dockerfile already sets it.

**Alternatives considered:** a policy with `'unsafe-inline'` (defeats the point); hashes instead of nonces
(Next's inline scripts change per build and render); `Content-Security-Policy-Report-Only` first (this
project has no endpoint to collect reports, and the console check showed the same).

## D-062 · 2026-11-14 · An attack may get more than one correction (`attack_retries`); it halves backfires but does not move the attacker's share

**Decision:** `Settings.attack_retries` (default 1, the behaviour since D-025 and D-040) sets how many
corrections a failed attack gets before it backfires; each retry shows the attacker the real output of its latest
attempt, or says the reply was unreadable. It is validated as not negative. `config/gate-mixed.toml` sets 2;
`config/fighters.toml`, the house bot, sparring and ranked play keep 1, so nothing a user sees changes. The log
carries one `attack_retry` event per retry (the replay viewer shows the first, as before).

**Why:** in the first 29-match run on the mixed pool (D-060) only 34 of 174 attacks verified on the first try, the
one retry rescued 90 of the 139 that needed it, and 49 still backfired, nearly all because the stated answer
differed from the snippet's output. A second retry looked like the cheapest lever for the attacker.

**Result** (`runs/mixed2.jsonl`, 28 of a planned 30 matches, 168 turns, `--no-panel`, gpt-oss against gemini-lite;
the pairings and topics are the same by match number because each match seeds its own `Random`, the model replies
are not; compared with D-060's 29 matches / 174 turns):

| | `attack_retries` 1 (D-060) | `attack_retries` 2 |
|---|---|---|
| Backfires | 50 of 174 (28.7%) | 21 of 168 (12.5%) |
| Attacks that verified | 124 (71%) | 147 (87.5%) |
| Attacker share of turns | 22.4% (16.9 to 29.2%) | 24.4% (18.5 to 31.4%) |
| Hit rate of verified attacks | 31.5% | 27.9% |
| Draws (of the matches) | 1 of 29 | 8 of 28 |

Backfires: gemini-lite 36% to 17% of its attacks, gpt-oss 22% to 8%. Of the 35 attacks that needed a second retry,
14 verified (40%) and 21 backfired. Hit rate by path now: first try 7 of 43 (16%), after one retry 30 of 90
(33%), after two 4 of 14 (29%); the rescued attacks do not hit harder than the others, so there is no sign
they are broken problems. Attack calls per turn: 1.80 before, 1.95 now (+8%). Token cut-offs 1 of 168 turns, real
timeouts 0.

**What it shows and what it does not:** the second retry cuts the attacker's wasted turns by more than half, but
the attacker's share of turns rose by 2.0 points, inside the noise and short of the 4 to 6 expected: the
extra attacks that now verify are mostly blocked (the defender wins 72% of verified attacks, up from 68.5%).
Draws rose because fewer backfires means fewer lopsided matches. The defender's share is 75.6% (68.6 to
81.5%): the interval now reaches below 70%, so the gate is no longer ruled out, but the point estimate is
still above it and the formal gate needs 100 matches (waived, D-042). The remaining lever is how hard the
verified problems are, a design choice for the owner.

**Not known:** a 28-match, two-fighter sample; the first sim hung when the computer slept and was restarted once
after match 20 (matches are independent and the restart resumed from the saved ones); the 29th and 30th matches
were rate limited by Groq and the run was stopped at 28; the rescued attacks' hit rate rests on 14 attacks.

**Alternatives considered:** keeping 1 (leaves 28.7% of turns wasted); a third retry (the second rescued 40%,
the third would rescue fewer and cost more calls); taking the answer from the snippet (rejected in D-021).

## D-065 · 2026-11-14 · The 70%-of-turns balance gate is retired, not just waived (supersedes the waiver in D-042)

**Decision:** The owner approved (2026-11-14) closing the question of the attacker's share of turns. The gate "neither
role wins more than 70% of turns over 100+ matches" is no longer a launch condition or a target to tune toward;
`arena sim` still prints its verdict as a number, nothing acts on it. No rule, prompt or config change comes with this.
Balance is to be judged by whether the stronger fighter wins more often than the weaker one, which is what makes
ranked play (D-043) mean something, and that is measured when ranked matches exist, not before.

**Why:** the reason for the gate was the defender's near-total dominance in Phase 0 (D-026). The causes found since were
mostly not the game's design: token cut-offs decided about a third of turns with the earlier fighter pool (D-055 to
D-059), and a fighter whose reply failed to parse cost its match (D-061). With those fixed, the mixed pool gives the attacker
22.4% of turns (D-060) and 24.4% with a second attack retry (D-062), which is the ceiling the scripted-fighter study
predicted for these rules (D-020): the defender is simply the easier role. Raising the attacker's share further means
making verified problems harder to solve, which is a different experiment (below), not a fix.

**Evidence that the game tells fighters apart, and its limits:** in D-062's 28 matches gpt-oss won 13, gemini-lite 7 and 8
were draws. That is not an independent measure of which model is stronger, it is one pair of models, and the draws
(29% of matches) show many matches are decided by nothing. The real test is ranked results over many fighters.

**Not done:** a reference-panel "too easy" retry (a verified problem every panel solver answers would be sent back to be made
harder) was considered and not built: the panel costs about 4,300 tokens per scored problem on the same free-tier budget and
its effect on the attacker's share is unknown. The `--no-panel` runs also hide that real matches use the panel's 0.5 to 2.0
difficulty, so knockouts are possible in the real game and were impossible in these runs; how often they happen is not measured.

**Alternatives considered:** chasing the gate with an attacker bonus or harder-problem pitching (D-020's levers; the owner
chose not to); leaving the gate as a standing waiver (it would keep reading as an open failure).

## D-066 · 2026-11-14 · The API and the worker refuse to start without a valid KEY_ENCRYPTION_SECRET

**Decision:** `secret_box.check_secret()` raises `ConfigError` ("KEY_ENCRYPTION_SECRET is not set" or "is not a valid
key") and runs first in the API's startup (`lifespan`) and the worker's (`startup`), before the database migration, so
a process without a usable secret does not come up.

**Why:** until now the secret was read lazily (D-034). A deploy that forgot it, or had a typo in it, started normally and
failed at the first user who saved or used an API key. For a public launch that is the wrong place to find out.

**Effects:** a local `docker compose up` without the secret now stops at startup with the message instead of at the first
fighter; the README already says to set it. `docker compose up -d postgres redis` (used by the tests) is not affected, and
the compose file still passes the variable through with an empty default, because a required variable would break that.
The check does not tell a right secret from a wrong one: a changed secret still passes and then fails to decrypt
the stored keys ("wrong or changed KEY_ENCRYPTION_SECRET?"), as before. Tests: the check itself, and that neither process
touches the database or Redis before it; the worker tests set the secret.

**Alternatives considered:** leaving it lazy; a required variable in compose (breaks the database-only commands); a stored
check value to catch a changed secret (new state and a migration, and there is no rotation story yet).

## D-067 · 2026-11-14 · Real GitHub sign-in checked end to end; denying access no longer shows a raw error

**Decision:** A user who presses Cancel on GitHub (or whom GitHub refuses) comes back to `/login?error=denied`, which says "GitHub
did not let you in. You can try again.", instead of a raw 422 JSON error. `/auth/github/callback` takes GitHub's `error` parameter,
and `code` and `state` now default to empty, so a callback with neither is a 400 ("sign-in state did not match"), not a 422. The login
page shows text only for the fixed value `denied`; any other `error` value shows nothing.

**Checked live** (2026-11-14, local only: the owner's own GitHub OAuth app with the callback
`http://127.0.0.1:3100/api/auth/github/callback`, a generated local `KEY_ENCRYPTION_SECRET`, the production web build, the API,
Postgres and Redis in WSL, the "sign in as anyone" form off):
- The API started with the real secret, so the startup check (D-066) accepts a real key.
- The redirect to GitHub carried the right callback address, a random 32-character state in a cookie that is HttpOnly,
  SameSite=Lax and lasts 10 minutes, and no scope, so GitHub shares only the public profile.
- A real sign-in, done by the owner in their own browser (the browser pane's cookies were not shared): GitHub returned a code, the
  callback answered 307 and `/auth/me` answered 200; one user row (provider `github`) and one session row were stored.
- A mismatching state, and a callback with no state cookie, each got a clean 400; both the denial and the missing-parameter cases
  were reproduced as a 422 before this fix and checked as a redirect and a 400 after it, and the new login message showed with no
  console error in the browser pane. The per-address sign-in counter (D-063) counted each of those requests.

**Not checked:** signing out and in again in the real flow (a test covers that the same user is kept); what the owner's browser
console showed after returning to the app, so the Content-Security-Policy (D-064) is untested across the real redirect; any
domain other than `127.0.0.1`, HTTPS, or a real proxy. **Deploy requirement found:** the session and state cookies are Secure only
when `PUBLIC_URL` starts with `https://`, so production must set it to an `https` address; each OAuth app has one callback, so
production needs its own app with the public domain as the callback.

**Alternatives considered:** showing GitHub's own error text (it would put outside text on the page); a generic error page (the
user would not know they pressed Cancel).

## D-068 · 2026-11-15 · Exposure guardrails: local-only switches, a smaller worker environment, non-root images, no API docs

**Decision:** First phase of the pre-deploy security work (a read-only audit of the API, the engine and the web side,
then a plan approved by the owner).
- `ARENA_DEV_LOGIN=1` only takes effect when `PUBLIC_URL` is a localhost address (`127.0.0.1`, `localhost`, `::1`;
  `auth.public_url_is_local`); `/auth/dev` also has the sign-in rate limit (D-063).
- The worker refuses `ARENA_SANDBOX=off` unless `PUBLIC_URL` is a localhost address, so a public deployment cannot run
  model-written code unsandboxed by a typo or a copied default.
- Compose: `PUBLIC_URL` can be set (`${PUBLIC_URL:-http://127.0.0.1:3100}`) for the API and the worker; the worker gets
  an explicit list (the three provider keys, `PUBLIC_URL`, the shared database, Redis, config and secret settings) in
  place of the whole `.env`, so `GITHUB_CLIENT_SECRET` never sits in the process that runs model-written code.
- The API and web images run as unprivileged users (`app`, uid 10001; `node`).
- FastAPI's `/docs`, `/redoc` and `/openapi.json` are off: they load scripts from a CDN, unpinned and without
  integrity hashes, on the app's own origin.

**Why:** the audit's worst finding: the shipped compose stack, put behind a tunnel on the same machine, ran
model-written code as root with the secret and the database URL in reach (`/proc/1/environ`), and let anyone sign in as
anyone, which exposes every user's stored key. Binding ports to localhost does not stop a tunnel.

**Found on the way, not part of the audit:** `docker compose up --build`, which the README tells newcomers to run, had
been failing since the open-source release (D-046): `pyproject.toml` names `README.md` and `LICENSE`, and the API
Dockerfile did not copy them, so `uv sync` failed. CI never builds the images. Fixed, and a test checks the Dockerfile
copies every file the package metadata names. Both images were built and run in WSL after the change: the API and worker
modules import as uid 10001, and the web image served the login page as `node` with the Content-Security-Policy header
(which also settles D-064's open question about the standalone server).

**What this does not do:** the guards trust `PUBLIC_URL`: a deployment that forgets it is treated as local, and so is a
tunnel to an unchanged stack. They are a safety net under a deploy checklist (SECURITY.md), not a replacement for it.
The images are still pinned by tag, not digest, and Redis and Postgres still have default or no passwords (later
phases and the deploy step).

**Alternatives considered:** removing the dev-login default from compose (breaks the one-command local try-out); refusing to
start the API at all on a public `PUBLIC_URL` without a sandboxed worker (it cannot see the worker); dropping `ARENA_SANDBOX=off`
from compose (the compose worker has no Docker, so it could not start).

## D-069 · 2026-11-15 · Match integrity in the engine: a panel review on ranked hits, and the sandbox and parser holes closed

**Decision:** Second phase of the pre-deploy security work. From the audit, with the owner's choice on the first item:
- **Review on hits (ranked math only).** `scorer.review_hit` (new) asks the `[[panel]]` to solve the problem just before a
  defender who gave an answer takes a hit; if at least two members answered and most of them gave the defender's answer, the hit
  becomes a block and a `review` event (overturned, who answered what, tokens) is logged. The worker passes `config.panel` for
  ranked matches only (`Players.review`); sparring, sims, code strikes, timeouts and unparsed answers are never reviewed, and a
  panel member with no key on the server leaves the hit standing (logged as a warning, the match goes on). The replay shows it
  ("Panel review: overturned the hit: 2 of 3 ...").
- **Exit code 125 can no longer void a match.** The snippet runs as `sh -c 'python -I -; ...'` and any exit code of 125 or more
  becomes 1, so only Docker can produce 125 (`ConfigError`). `SystemExit(125)` used to make the worker fail the match, so a losing
  attacker or a defender could void a ranked game.
- **Output flood:** the size cap is also checked after the process exits (a burst between two polls was read whole), the docker
  client is killed before `docker rm` (it kept copying a flood into the temp files), `docker rm` has a 30 s timeout, and the worker
  removes `arena-snippet-*` containers a dead worker left, at startup.
- **Sandbox image:** `docker/sandbox.Dockerfile` (base pinned by digest, SymPy 1.14.0 as in uv.lock), built by the worker as
  `arena-sandbox:1` when missing, run with `--pull=never`. The attacker prompt allows SymPy and the plain Python image had none, so
  those snippets failed with `ModuleNotFoundError` and backfired in the web worker.
- **Deep nesting:** JSON nested too deeply (in a snippet's output, a code attack's tests or its expected outputs) raises
  `RecursionError`, which was not caught and aborted the match; it is now a mismatch or a rejected test, and tests are limited to
  20 levels.
- **Short reasons:** a mismatch or error reason keeps at most 300 characters of what the snippet printed, so the battle log and the
  correction prompt cannot carry up to 64 KB per attempt.
- **Earlier problems in the attacker prompt** are framed as untrusted data inside `<problems>` tags with tags stripped (one
  player's problem used to reach the other's attacker prompt as plain text).
- **Moderation:** more invisible characters (soft hyphen, C1 controls, "tag" characters, variation selectors, fillers, invisible
  operators) are fouls, and the instruction patterns run on the NFKC-normalised text, so full-width letters do not hide them.

**Why:** the audit's engine findings. The wrong-answer one needs no special access: a ranked user's persona can make its model state
a wrong answer and print it, the self-check passes, and every such attack is a hit; the panel is the only independent check there is.

**Checked:** the new tests, including the exit-125, burst-flood and SymPy-image cases under real gVisor in WSL, an end-to-end ranked
match through the worker with a configured panel (the stored replay shows overturned hits), and the full suite on Linux.

**Not solved, and not claimed:**
- The review is a majority of free-tier models: two weak members who agree can overturn a correct hit, and a problem the panel cannot
  solve leaves a wrong attacker answer standing. It costs server-key tokens on every ranked math hit (about three panel calls).
- Moderation stays a rule filter: homoglyphs from other alphabets (Cyrillic `і`), other languages, base64 and "answer in LaTeX"-style
  sabotage still pass.
- An attacker's reference in a code strike can still be a lookup table; verification proves only that it agrees with its own outputs.
- Code strikes and sparring are not reviewed, and a snippet can still run for up to timeout plus the 10 s start-up allowance.
- The equality helper still has no memory limit (Phase 4).

**Alternatives considered:** a panel check on every attack (about 4,300 tokens a problem on every match); a lower bar for overturning
(two agreeing weak models would overturn too easily); counting an overturned hit as a backfire for the attacker (it punishes an honest
mistake as if it were cheating, and the owner chose "overturn to a block").

## D-070 · 2026-11-15 · Accounts, keys and data: owner control, safer failures, a connection pool

**Decision:** Third phase of the pre-deploy security work (the audit's API and data findings).
- **A new provider needs a new key.** Saving a version with another provider and no key is a 422: the saved key belongs to the old
  provider and would have been sent to the new one as its credential.
- **Delete a fighter** (`DELETE /fighters/{id}`, owner only, a button on the fighter page): erases the fighter, every version (so
  every key it stored) and its rating. Finished matches stay on record with the link to it cleared (the foreign keys already said
  so). Refused while a match of it is waiting or being played.
- **Ranked pool opt-in** (`fighters.ranked_opt_in`, migration 0006, `PUT /fighters/{id}/ranked-pool`, a checkbox on the fighter
  page): other players' ranked matches spend a fighter's key only if its owner turned it on; asking for your own ranked match needs
  it too. Every fighter that existed before starts out of the pool, so the pool is empty until owners opt in.
- **Handles:** `handle` is unique across providers, and a clash (a GitHub rename onto a taken name, or a dev-login user holding it)
  ended in a 500 at sign-in. `upsert_user` now gives the clashing account `name-2`, `name-3`, ... and keeps it.
- **The worker stops at its time limit:** a match stops asking models (raising "ran out of time") 60 s before arq's 1,800 s job timeout,
  instead of its thread spending keys after arq gave up; a cancelled or crashing match is marked failed (it used to stay `running`
  until a restart), and `mark_failed` never overwrites a finished match.
- **No internals in errors users see:** a server bug is "the match failed because of a server error" (the detail, scrubbed of keys, goes
  to the worker's log and is re-raised scrubbed); a queue failure no longer shows the Redis host; an unreadable replay says so without the
  parser's text; and a ranked match's error, which both owners can read, says only that "a fighter's model returned an error".
- **Per-user limits:** at most 2 matches waiting or playing per user (the single worker was one user's to fill), and one
  spar or ranked request per user at a time, held with a Postgres advisory lock that never waits (waiting would freeze the API's event
  loop); a second concurrent request gets "try again in a moment". This closes the check-then-insert race on a user's own caps.
- **Cross-site writes and big bodies** (`arena_api/guards.py`, middleware): a POST/PUT/DELETE whose `Origin` is not the app's own
  (on a local address: any local origin, for `npm run dev`) or whose `Sec-Fetch-Site` is not `same-origin`/`none` gets 403; a body over
  64 KB gets 413 and a body with no length 411. Requests with neither header (curl, scripts) pass. The three body-less POSTs
  (`/spar`, `/ranked`, `/logout`) were protected by SameSite=Lax alone.
- **Persona and model** reject invisible, bidirectional and control characters (the other player sees both in a ranked replay);
  newlines and tabs stay.
- **A bounded database pool:** `store.connect()` takes a connection from a `psycopg_pool.ConnectionPool` (size `ARENA_DB_POOL`, default 10;
  a request waits up to 5 s) instead of opening one per call, and an exhausted pool is a 503 with `Retry-After`, not a 500. Pools are
  closed at shutdown and by the test fixture.

**New dependency (`psycopg-pool`, in the `api` group: the pool package from the project that makes `psycopg`; its licence was not checked here):** the audit showed that every
authenticated request opens a new connection, so any flood of cheap requests can exhaust Postgres's connection limit; a pool is the
standard bound and nothing smaller (a semaphore around `psycopg.connect`) would also reuse connections.

**Checked:** each item has tests written first; the whole suite passes on Linux with Postgres and gVisor.

**Not done, and not claimed:**
- A victim's daily cap can still be overshot a little: a ranked match picks the opponent and counts its cap without a lock on the opponent
  (bounded by the requester's rate limit of 10 a minute and the 2-match limit).
- The body-size check reads `Content-Length`; a client that lies about it is stopped later by the field limits, not here.
- Old fighter versions keep their keys (only deleting the fighter erases them); there is no key rotation for the server secret.
- Sessions are not ended on a new sign-in, and expired session rows are never deleted.
- The web changes (the checkbox, the delete button) pass the typecheck but were not exercised in a browser.

**Alternatives considered:** ending a match's thread by killing it (Python cannot, short of a subprocess per match); an opponent-side lock
(try-lock order problems and a failure mode for the requester); a CSRF token (the Origin and fetch-metadata checks need no state and no web
change); deleting only the key and keeping the fighter (a fighter without a key cannot play, so delete is the honest operation).

## D-071 · 2026-11-15 · Web headers, pinned images and actions, CI that builds the images, ignore files

**Decision:** Fourth phase of the pre-deploy security work (the audit's web, container and repository findings).
- **Headers:** pages also send `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy: same-origin`, and no longer announce
  `X-Powered-By: Next.js`; the API adds `X-Content-Type-Options: nosniff`, `Cross-Origin-Resource-Policy: same-origin` and
  `Referrer-Policy: no-referrer` to its own responses (including the guard's refusals).
- **Forms:** the API-key field is `autocomplete="new-password"` (browsers ignore `off` on password fields and offered to save the key); the
  local dev sign-in shows an error only when it is text (a list or a non-JSON body used to throw).
- **The answer checker** starts with `python -P` (no working directory on its import path) and limits its own address space to 1 GiB on POSIX, so a
  SymPy expression that eats memory inside its 5 s cannot take the worker with it. `-I` was not used: the helper's `PYTHONPATH` is how it finds
  the package from a source tree.
- **Ignore files:** `.env.*` (but not `.env.example`), `*.pem` and `*.key` in `.gitignore` and `.dockerignore`: `web/.env.local`, which Next reads,
  would have been copied into the web image build.
- **Pins:** every base image (the API, web and sandbox Dockerfiles, the `uv` image copied into the API image, `postgres` and `redis` in compose and
  the CI database) is pinned by digest, and every GitHub Action in CI by commit (with the tag as a comment). `python:3.12-slim` moved to a new
  digest within a day of the first pin, which is what a tag does; the sandbox image was rebuilt from the new one and its gVisor tests passed.
- **CI:** `uv sync --locked` (a stale lock now fails), `npm audit --audit-level=high` (0 vulnerabilities today), and a job that builds the
  API, web and sandbox images (D-068); `.github/dependabot.yml` proposes weekly updates for uv, npm, Actions and the Dockerfiles, because pins only stay safe if
  something moves them. `httpx2`, which `arena.llm` imports, is now declared.
- CONTRIBUTING says Node 22+, which is what CI builds with.

**Checked:** a test for each item (repo files, headers, the helper's limit run in a subprocess); the three images built from the pinned
digests in WSL; the full suite passes on Linux with Postgres and gVisor.

**Not checked, because they only run on GitHub:** the new `images` job, the SHA-pinned actions, `npm audit` as a gate, and Dependabot reading its
file. A first push will show; if an action's commit were wrong the job would fail loudly.

**Not done:** HSTS and TLS (the reverse proxy, at deploy), passwords for Redis and Postgres beyond the localhost-only defaults, a CSP report endpoint,
secret scanning and push protection on GitHub (repository settings, the owner's), and a pre-commit secret scanner.

**Alternatives considered:** `-I` for the checker (breaks its source-tree start); pinning actions by tag only (a retagged release would run in CI with
no review); leaving Dependabot out and pinning once (the pins would age into known-vulnerable images).

## D-072 · 2026-11-15 · Self-hosting: a production compose override, a host worker script and a guide

**Decision:** Agent Arena is open source and has no hosted instance, so the deployment work is a kit anyone can follow, not one
owner's setup. It adds:
- `docker-compose.prod.yml`, an override on the local stack. Compose refuses to start (naming the setting) without
  `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `KEY_ENCRYPTION_SECRET`, `PUBLIC_URL` and `CLIENT_IP_HEADER`, instead of falling back to a local
  default. It turns the sign-in-as-anyone form off, puts a password on Redis, restarts services, and leaves the container worker out
  (profile `container-worker`, off by default). Everything it publishes stays on 127.0.0.1.
- `deploy/run-worker.sh`, which runs the worker on the host: it needs Docker with `runsc`, an `https` `PUBLIC_URL`, the required
  secrets, and never `ARENA_SANDBOX=off`; it refuses an env file with Windows line endings; it builds the database and Redis URLs from
  the two passwords. `.gitattributes` keeps `*.sh` on LF checkouts.
- `docs/SELF_HOSTING.md`: a local try-it path (today's compose stack), and a public path with the gVisor install, the GitHub OAuth
  app, `.env`, three ways to get an `https` address (Caddy, Cloudflare Tunnel, Tailscale Funnel), the worker as a systemd service,
  a test that the visitor-address header really is overwritten, backups, updates and troubleshooting.

**Why:**
- The worker cannot live in the compose stack on a public host: a container would run model-written code unsandboxed, or need the Docker
  socket, which is the whole machine (D-044, D-068).
- The public address layer is the host's choice (a domain and Caddy, a Cloudflare domain, or a free Tailscale name), so the repository
  does not pick one; it only needs an `https` address and a header the layer overwrites (D-063).
- A secret that falls back to a default is a secret that is never set.

**Checked (WSL2 Ubuntu 24.04, Docker, 2026-11-15):**
- Compose without the secrets refuses and names each setting; with them it lists postgres, redis, api and web and no worker.
- The stack starts. Redis answers `NOAUTH` without the password. The API limits one address to 60 reads a minute.
- The header test in the guide tells the two cases apart. With no proxy and a made-up `X-Forwarded-For` per request, all 80 answers are
  200, so the limits are bypassed. Behind a real Caddy it was 59 answers of 200 and 21 of 429: Caddy replaced the made-up header and the
  Next.js `/api` relay passed it on unchanged.
- The worker script's refusals (missing setting, `http` address, sandbox off, no `runsc`, CRLF) and its success path are tested, with
  stubbed `docker` and `uv`, in `tests/test_deploy.py`.
- On the page `/leaderboard` a limited visitor still gets HTTP 200 and the page text "The API is unreachable", so the guide's test
  uses `/api/leaderboard`.

**Not checked:** Cloudflare Tunnel and Tailscale Funnel (no account here); their header behaviour is from vendor documentation. Tailscale
adds `X-Forwarded-For` for the visitor; if it appended to a made-up one instead of replacing it, the API sees a value that is not one
address and counts the visitor under the web server's address, so the limits become shared, not bypassed. The real worker started by the
script, and the systemd unit, were not run end to end. The guide has not been followed by anyone but its author.

**Not done:** a Caddy service in compose, a one-command installer, Kubernetes, a hosted instance, and content moderation beyond the
existing problem filter.

**Alternatives considered:** a worker in the compose stack with the Docker socket mounted (gives the machine away); picking one tunnel
vendor for everyone (ties an open-source project to one company's free plan); defaulting the secrets for convenience (see Why).

## D-073 · 2026-11-18 · Development style policy for Next's overlay, a dependency bump, and a production-only audit gate

**Decision:**
- In development only, `style-src` is `'self' 'unsafe-inline'` with no nonce (`web/lib/csp.ts`). Production is unchanged: `'self' 'nonce-...'`, no `unsafe-inline`.
- `next` 16.4.3 to 16.4.6 and `vitest` 5.0.5 to 5.1.1 (lockfile), which clears `npm audit --omit=dev` (a moderate `next` advisory).
- CI's audit step is now `npm audit --omit=dev --audit-level=high`: it gates on what ships.

**Why:**
- Next's development overlay writes `<style>` tags without a nonce, so the strict policy blocked them and its button showed as an
  unstyled grey square at the top of every page (34 console errors per page). A nonce makes browsers ignore `unsafe-inline`, so the
  development policy cannot have both; it mirrors how `unsafe-eval` is already development-only. A production build has no overlay.
- `npm audit` still reports 5 high findings, all one advisory: `picomatch` ReDoS (GHSA-fc5q-39xc-vjpf), reached through `vitest` ->
  `vite` / `tinyglobby` / `fdir`. It covers every picomatch version, so there is nothing to upgrade to (npm's only "fix" is a vitest
  downgrade). It is test tooling and never ships, but with the old gate it would fail every push. Production dependencies stay gated.

**Alternatives considered:** `devIndicators: false` (hides the overlay and its build-error badge); a nonce for the overlay (Next does not
pass one to it); pinning `vitest` back (older, and still affected); leaving the gate red.

## D-074 · 2026-11-18 · API fields for a readable UI

**Decision:** The web redesign (owner-approved 2026-11-18: UI plus small API additions, an arena look, plain CSS, no new dependency) needs data the API did not give. Added:
- `ReplaySummary` gains `mode` (sim, sparring or ranked) and `ended_at`. The public list is still sims only; the replay detail fills both from the match row, because the log does not say how a match came about.
- `GET /matches/mine` (signed in, visitor-limited like the other reads): the user's latest 20 spars and ranked matches as requester or as the ranked opponent's owner, newest first, with `you` ("a" or "b"), the names, and the result fields (null until finished). Without it a new self-hosted site has nothing on its home page, since the only public list is imported sims.
- `FighterView` gains `rating`, `games`, `wins`, `draws`, `losses` from `ratings` (rating is null before the first ranked game).
- `GET /fighters/options` returns providers as `{name, models, key_url}`. `models` are the model ids the config already uses with that provider (house fighters and panel), as suggestions in a free-text field; `key_url` is a new optional `key_url` on each `[providers.*]` entry in `config/fighters.toml`, which must be an `https://` address.

**Why:** a first-time visitor needs to see what happened (who fought, when, how it went), what their fighter has done, and where to get a key. No new write routes, no schema change, and ranked and sparring replays stay private to their owners (D-040's rule, unchanged).

**Checked:** tests for each field and route (ownership, hidden sims, signed-out 401, `mine` routing before `/{match_id}`), on Linux with Postgres.

**Alternatives considered:** making ranked replays public (rejected: they show a user's persona); a model list kept by hand in the UI (it would go stale; the config is where model ids are already checked, D-036 and the 2026-10-30 note).

## D-075 · 2026-11-18 · A readable web UI: dark arena theme in plain CSS, shared components

**Decision:** The web app is restyled and reorganised so a first-time visitor can tell what it is and what to do (owner-approved plan, 2026-11-18). No new dependency.
- **Look:** one dark "arena" theme as CSS custom properties in `web/app/globals.css` (surface levels, fighter A blue and B orange, hit red, block green, backfire amber), the system font stack, base styles for plain elements, and `.button` / `.button-primary` / `.button-danger` classes that work on links and buttons.
- **Components:** `web/app/components/` holds `PageHeader`, `Card`, `Badge`, `HpBar`, `EmptyState` and `MatchCard`, each with a CSS Module. Pure text and date helpers are in `web/lib/labels.ts` (unit tested).
- **CSP-safe styling (D-064):** no `style="..."` attributes anywhere, since `style-src` carries only a nonce; all styling is in CSS files. The health bar is an SVG whose `width` attribute carries the amount.
- **Content:** the home page explains the game in three steps and shows the signed-in user's own matches (`GET /matches/mine`, D-074) above the public replays; pages say what to do next and what each empty list means.
- Light mode is dropped: the previous light/dark switch is replaced by the one dark theme.

**Why:** the first walkthrough found bare browser-default pages, no explanation of the game, raw match ids and an empty home page on a new install. Plain CSS keeps the dependency list (next, react, react-dom, pixi.js) and the CSP as they are; Tailwind or a component library would have added a build step and an entry here for little a few shared components do not already cover.

**Not done:** sprites or avatars (Phase 3, D-031 still holds: fighters are drawn from shapes), live spectating, public ranked replays, component tests (jsdom and testing-library would be new dependencies), light mode.

**Alternatives considered:** Tailwind CSS; a component library; keeping the light/dark switch.

## D-076 · 2026-11-18 · The web lockfile is regenerated on Linux

**Decision:** After `npm audit fix` or any dependency change on Windows, regenerate `web/package-lock.json` in the project's Linux Node image before committing: `docker run --rm -v <repo>/web:/app -w /app node:24-alpine@<digest from docker/web.Dockerfile> npm install --package-lock-only`, then check `npm ci --dry-run` there.

**Why:** the lock written by `npm audit fix` on Windows (D-073) lacked two optional cross-platform packages (`@emnapi/core`, `@emnapi/runtime`). `npm ci` accepted it on Windows but refused it on Linux, so CI's web job and the web Docker image build both failed on the first push of the UI redesign. CI is the Linux check; the lock has to be valid there.

**Alternatives considered:** deleting the lock and reinstalling on Windows (same platform pruning); making CI use `npm install` (loses the lock's reproducibility).

## D-077 · 2026-11-18 · Limits on what accounts can spend or distort

**Decision:** First phase of the security hardening (the 2026-11-18 audit). Four limits:
- **A site-wide budget of server-paid matches:** `server_matches_per_day` (default 100, in `[settings]`), counted in Redis under `budget:server-matches` with a 24 h life, checked in `queue_match` for sparring and ranked alike. Past it the API answers 429 "today's shared free-tier model budget is used up". It is not a per-account limit: accounts are free, so only a shared number protects the server's own keys.
- **A daily ranked limit per user** (`MAX_RANKED_PER_USER_PER_DAY` = 10) over all their fighters; the per-fighter cap alone allowed 10 fighters x 50.
- **A pair limit:** two owners can be paired at most 3 times a day (`MAX_PAIR_MATCHES_PER_DAY`, counting any status), so two accounts cannot trade wins to farm rating. Pairing still finds a third owner's fighter.
- **A per-address limit for session checks** (`session`, 300 a minute) on the fighter and match routes, `/auth/me` and a fighter's ranked history: each costs a database lookup, and 120 junk-cookie requests had all been served.

**Why:** the audit found nothing that exposes other people's data, but cost and rating integrity rested on per-account caps that a handful of free accounts get round.

**Checked:** a test for each limit (`tests/test_abuse_guards.py`); the full Linux suite with Postgres and gVisor. Two older tests needed the stand-in Redis because the session limit now counts in it.

**Not done:** weighting a match by what it really costs in tokens; per-address caps on creating accounts (GitHub sign-in is the gate); detecting collusion beyond the pair limit.

**Alternatives considered:** a per-account budget (bypassed by new accounts); blocking an address after failed lookups only (a generous limit on every session check is simpler and covers the same flood).

## D-078 · 2026-11-18 · Key rotation, session controls, account deletion, a narrower worker environment

**Decision:** Second phase of the security hardening.
- **Key rotation:** `KEY_ENCRYPTION_OLD_SECRETS` (comma-separated) lets retired secrets decrypt while the current one encrypts (a `MultiFernet`); `python -m arena_api.rotate_keys` re-encrypts every saved key under the current secret, after which the old one can be dropped. A malformed old secret fails startup.
- **Sessions:** `POST /auth/logout-all` signs the user out everywhere; signing in deletes every expired session (nothing else did).
- **Account deletion:** `DELETE /auth/me` erases the user, their fighters, versions and saved keys (the database cascades) and their sparring matches. Ranked matches stay, because the other player's rating and history came from them, with this user's side renamed `deleted` and its persona replaced by `[removed]` in the stored log header. Refused (409) while a match of theirs is queued or running. The fighters page has "Sign out everywhere" and "Delete my account".
- **Worker environment:** `deploy/run-worker.sh` starts the worker with `env -i` and an allowlist (paths, the database and Redis URLs, the key secrets, the provider keys, `PUBLIC_URL`), so the GitHub client secret is not in its environment, as D-068 required of the compose worker.

**Why:** a leaked or old key secret had no way out; a stolen session could not be revoked in one step; users could not take their data and keys off the site; and the host worker loaded the whole `.env`.

**Checked:** tests for each (`tests/test_account_controls.py`, `tests/test_secret_box.py`, `tests/test_deploy.py`) on Linux with Postgres.

**Not done:** deleting a user's name from other people's ranked replays beyond the header (problem text written by their model stays); an export of the user's data; ending older sessions on a new sign-in (several devices at once is allowed on purpose).

**Alternatives considered:** deleting the user's ranked matches (would change the opponent's history and leave ratings unexplained); soft-deleting the account (keeps the keys).
