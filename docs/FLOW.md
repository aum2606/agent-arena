# Flow

```mermaid
sequenceDiagram
    participant C as cli
    participant O as orchestrator
    participant P as prompts
    participant L as llm
    participant V as verifier
    participant D as damage
    participant G as battle_log

    C->>O: run_match(a, b, llm.complete, log, rng, verify)
    loop each turn (max 6, roles swap)
        O->>G: start_turn, attack_start
        O->>P: attack_prompts(attacker, random topic, problems so far)
        O->>L: complete(attacker)
        O->>P: parse_attack(reply)
        O->>V: verify_attack(answer, snippet)
        alt parse error, timeout or failed check
            O->>G: backfire, hit (attacker is target, half damage)
        else verified
            O->>G: attack_verified, defend_start
            O->>P: defense_prompts(defender, problem)
            O->>L: complete(defender)
            O->>P: parse_defense(reply)
            O->>V: answers_match(reply, answer)
            alt timeout or wrong answer
                O->>G: timeout or defend_result, hit
            else correct
                O->>G: defend_result, block
            end
        end
        O->>D: damage, apply_damage, match_result
        O->>G: hp, knockout, match_end
    end
    O-->>C: MatchRecord
    C->>G: write(runs/<match_id>.json)
    C->>C: print summary
```

`arena sim --n N` repeats the loop above for each missing match (pairs picked by a per-index
seeded RNG), calling `stats.append_record` after each one, then prints `format_stats` over all
saved records.

`arena synth` runs the same `run_match` with `SyntheticLlm.complete` and `synthetic_verify`
(scripted fighters, no network) for each cell of a skill x attacker-bonus table.

## Modules

- `models`: dataclasses (`Fighter`, `Attack`, `TurnResult`, `MatchRecord`, `MatchResult`).
- `damage`: pure rule functions and the Phase 0 constants (HP, base damage, max turns).
- `verifier`: SymPy answer equality and the snippet runner (subprocess, timeout, temp dir).
- `battle_log`: per-turn event list with `t` in ms, JSON writer.
- `config`: loads `config/fighters.toml` into settings, providers and fighters.
- `llm`: OpenAI-compatible client per provider, 429 backoff, delay between calls.
- `prompts`: attacker and defender prompts and tag parsing of the replies.
- `cli`: `arena match` and `arena sim` (load `.env` and config, run matches, print output).
- `stats`: balance stats over `MatchRecord`s, plus reading and appending the results JSONL.
- `synthetic`: scripted fighters and the balance sweep behind `arena synth` (D-020).
- `orchestrator`: `play_turn` and `run_match`, the only module that sequences a match.
