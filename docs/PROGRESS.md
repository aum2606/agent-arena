# Progress — Phase 0 (Balance Prototype)

Gate: over 100+ simulated matches, neither role wins more than 70% of turns.

## Checklist
- [x] 0. Bootstrap (git, uv, tooling, pre-commit, docs skeleton)
- [x] 1. models + damage
- [ ] 2. verifier
- [ ] 3. battle_log
- [ ] 4. llm + config
- [ ] 5. prompts + parsing
- [ ] 6. orchestrator
- [ ] 7. cli `match`
- [ ] 8. stats + cli `sim`
- [ ] 9. live smoke test (needs API keys)
- [ ] 10. gate run, report, tag `v0.1.0-prototype`

## Current task
None in progress.

## Next task
2. verifier

## Blockers
- Open rule question: is a "round" one turn or two (one attack each)? Must be settled before task 6
  (it sets `max_turns`). With 6 turns and base 20, a KO is almost impossible.
- API keys are needed from task 9.

## Latest sim stats
None yet.

## Notes
- Until task 6, vulture runs as `uv run vulture src tests` (D-005).
- `pytest` exits with code 5 ("no tests collected") until task 1 adds the first tests.
