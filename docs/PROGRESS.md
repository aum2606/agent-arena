# Progress — Phase 0 (Balance Prototype)

Gate: over 100+ simulated matches, neither role wins more than 70% of turns.

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
- [ ] 10. gate run, report, tag `v0.1.0-prototype`

## Current task
None in progress.

## Next task
10. gate run (100+ matches), after the owner decides how to handle the backfire rate

## Blockers
- Backfires dominate: about half of all attacks fail self-verification even after prompt tuning
  (D-012). Defenders win every backfire turn, so the defender role cannot fall below roughly the
  backfire rate. Owner decision needed on rules before the gate run (see report).
- Groq's free tier rate-limited Qwen past 5 retries in 3 of 8 calls; a 100-match sim would keep
  stopping. Probably needs a larger `call_delay_s` / `max_retries` (not yet changed).
- No third fighter: the OpenRouter free models tried were unreliable (D-011).

## Latest sim stats
Smoke test, 3 matches (qwen vs gemini-lite, `runs/smoke.jsonl`, not the gate run):
- Attacker wins 5.6% of turns, defender 94.4% (block 8, backfire 9). Backfire rate 50%.
After prompt tuning (D-012), attack-only checks of 8 attacks per fighter: 8/16, 7/16, 7/16 pass
self-verification. No full match was rerun.

## Notes
- Vulture is back to `uv run vulture src` and passes (D-005/D-009 transition ended with task 7).
