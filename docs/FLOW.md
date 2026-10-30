# Flow

```mermaid
sequenceDiagram
    participant O as orchestrator
    participant P as prompts
    participant L as llm
    participant V as verifier
    participant D as damage
    participant G as battle_log

    loop each turn (max 6, roles swap)
        O->>G: start_turn, attack_start
        O->>P: attack_prompts(attacker)
        O->>L: complete(attacker)
        O->>P: parse_attack(reply)
        O->>V: verify_attack(answer, snippet)
        alt parse error, timeout or failed check
            O->>G: backfire, hit (attacker is target)
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
```

Task 7 adds the CLI at the top of this flow; task 8 adds `stats` reading the `MatchRecord`s.

## Modules

- `models`: dataclasses (`Fighter`, `Attack`, `TurnResult`, `MatchRecord`, `MatchResult`).
- `damage`: pure rule functions and the Phase 0 constants (HP, base damage, max turns).
- `verifier`: SymPy answer equality and the snippet runner (subprocess, timeout, temp dir).
- `battle_log`: per-turn event list with `t` in ms, JSON writer.
- `config`: loads `config/fighters.toml` into settings, providers and fighters.
- `llm`: OpenAI-compatible client per provider, 429 backoff, delay between calls.
- `prompts`: attacker and defender prompts and tag parsing of the replies.
- `orchestrator`: `play_turn` and `run_match`, the only module that sequences a match.
