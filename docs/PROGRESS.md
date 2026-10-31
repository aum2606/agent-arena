# Progress — Phase 0 (Balance Prototype)

Gate: over 100+ simulated matches, neither role wins more than 70% of turns.

**Status: gate NOT reached. The run was stopped at 48 of 100 matches (owner's call) with the
defender winning 96.2% of turns. No `v0.1.0-prototype` tag yet.**

## Checklist
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
- [ ] 10. gate run: stopped at 48/100, gate failing (see below); tag `v0.1.0-prototype` pending

## Current task
None in progress.

## Next task
Difficulty prompt (step 2 below), tested with a short sim once Gemini is stable.

## Blockers
- The rules/prompts as they stand give the defender about 96% of turns. Needs a design change.
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

## Suggested next steps
1. DONE (D-017): attacker variety. Each turn has a random topic and the attacker sees the problems
   already posed. Not yet measured at scale (3 live matches: 13 verified problems, all distinct).
2. Raise problem difficulty in the attacker prompt (multi-step, no textbook formula), since 95% of
   verified attacks are solved.
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
