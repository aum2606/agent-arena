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
- [ ] 7. cli `match`
- [ ] 8. stats + cli `sim`
- [ ] 9. live smoke test (needs API keys)
- [ ] 10. gate run, report, tag `v0.1.0-prototype`

## Current task
None in progress.

## Next task
7. cli `match`

## Blockers
- API keys are needed from task 9.
- `config/fighters.toml` has providers and settings but no fighters yet; task 9 adds them after
  checking current free model IDs.

## Latest sim stats
None yet.

## Notes
- Until task 7, vulture runs as `uv run vulture src tests` (D-005, D-009).
- `pytest` exits with code 5 ("no tests collected") until task 1 adds the first tests.
