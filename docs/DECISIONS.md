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
