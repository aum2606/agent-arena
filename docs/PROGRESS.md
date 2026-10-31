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
10. gate run (100+ matches), after the owner decides how to handle the defender dominance

## Blockers
- Defenders win nearly every turn: in the latest 3-match smoke test attackers won 0 of 18 turns
  (11 blocks, 7 backfires). Verified attacks are easy enough that both fighters block them, and
  a backfire is also a defender win. The gate (70%) will fail with these rules. Owner decision
  needed: see the report (difficulty is fixed at 1.0 in Phase 0, D-013 notes the backfire metric).
- Gemini 503s stopped the first gate attempt at 34/100; 5xx are now retried (D-015).
- Groq free tier has an unknown daily token limit; a 100-match run (about 2 hours) may stop and
  need resuming (D-014).
- No third fighter: the OpenRouter free models tried were unreliable (D-011).

## Latest sim stats
Smoke test 2, 3 matches (gpt-oss-120b vs gemini-lite, `runs/smoke2.jsonl`, not the gate run):
- Attacker wins 0.0% of turns, defender 100% (block 11, backfire 7). Backfire rate 38.9%.
- About 68 s per match, no provider errors.
Attack-only check (6 attacks each): gpt-oss 6/6 verified, gemini-lite 3/6.

## Notes
- With backfire at half damage a knockout cannot happen in 6 turns (max 90 damage); every match
  ends by decision or draw (D-013).
- Vulture is back to `uv run vulture src` and passes (D-005/D-009 transition ended with task 7).
