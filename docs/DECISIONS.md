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
