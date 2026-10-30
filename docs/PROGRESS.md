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
10. gate run (100+ matches) once the owner has seen the smoke-test findings below

## Blockers
- Smoke test shows the gate would fail with the current prompts (see below). Owner decision needed
  on whether to tune prompts/rules before the 100-match run.
- No third fighter: the OpenRouter free models tried were unreliable (D-011).

## Latest sim stats
Smoke test, 3 matches (qwen vs gemini-lite, `runs/smoke.jsonl`, not the gate run):
- Attacker wins 5.6% of turns, defender 94.4% (block 8, backfire 9). Backfire rate 50%.
- All 9 backfires were "snippet output != stated answer": models state the answer before the
  snippet, so they often guess it wrong. A few snippets also returned unevaluated sympy objects.
- About 2 minutes per match (Groq 429 backoff included), so 100 matches take roughly 3 hours.

## Notes
- Vulture is back to `uv run vulture src` and passes (D-005/D-009 transition ended with task 7).
