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
Rolling outcome feedback is implemented (D-023). Live trial, 10 matches (`runs/feedback.jsonl`):
attacker 6.7% of turns (4 hits), backfires 48.3% (baseline 3.8% and 26.4%). Per attacker, gemini-lite
backfires 21 of 30, gpt-oss 8 of 30. Matches 6-10 backfire less than 1-5 (11 vs 18 of 30), but 10
matches cannot separate that from noise. The gate is still failing; feedback alone does not fix it.

## Blockers
- The rules/prompts as they stand give the defender about 96% of turns. Needs a design change.
- Groq's 8000 tokens-per-minute limit counts prompt + `max_tokens` (4096) per request, so two
  close calls hit it and the sim waits up to 300 s. Lowering `turn_max_tokens` to 2048 was tried and
  rejected (D-019): gpt-oss got cut off in 40% of attacks.
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

## Scripted-fighter sweep (`arena synth`, D-020)
A model of the rules, not of LLMs (see D-020). Results depend only on skill minus difficulty:
- With no attacker advantage the attacker's best case is about 22-25% of turns (skill equal to
  problem difficulty), so the 70% gate cannot pass however strong the models are.
- When skill exceeds difficulty by 0.2 or more, the attacker wins 0-3% of turns whatever its bonus.
  The live result (3.8%) matches this regime: strong models, problems that are too easy.
- Stronger models alone make it worse (skill 0.9, difficulty 0.5: 2-3%) unless problems get harder
  with skill.
- Correction (D-021): taking the attacker's answer from its snippet looked like the fix but is not.
  `arena synth --compare-rules` shows its extra attacker wins come from broken problems (about half
  the hits at the sweet spot); wins on solvable problems equal the current rule's. Keep backfire on
  mismatch.
- The current rule can pass the gate offline: with attacker bonus 0.1, difficulty near skill gives
  31-33% attacker wins (skill 0.7, difficulty 0.7-0.8; skill 0.9, difficulty 0.9), at the cost of
  30-48% backfires. With no bonus the attacker peaks at about 22%.
- So the lever is difficulty targeting. A closed-loop attacker (D-022) does not converge inside one
  6-turn match (2 feedback events: 3% -> 14% from a start that is too easy), but converges to
  difficulty 0.7-0.8 and passes the gate (29-31%, 35% backfires) if its calibration persists
  across matches.

## Suggested next steps
1. DONE (D-017): attacker variety. Each turn has a random topic and the attacker sees the problems
   already posed. Not yet measured at scale (3 live matches: 13 verified problems, all distinct).
2. DONE (D-018): difficulty prompt (multi-step, no textbook formula, trap, design backwards).
   Untested: the live sim was stopped after 1 match because of Groq rate limits.
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
