# Flow

```mermaid
sequenceDiagram
    participant C as cli
    participant O as orchestrator
    participant P as prompts
    participant L as llm
    participant V as verifier
    participant D as damage
    participant S as scorer
    participant G as battle_log

    C->>O: run_match(a, b, llm.complete, log, rng, verify)
    loop each turn (max 6, roles swap)
        O->>G: start_turn, attack_start
        O->>P: attack_prompts(attacker, random topic, problems so far, its recent outcomes)
        O->>L: complete(attacker)
        O->>P: parse_attack(reply)
        O->>V: verify_attack(answer, snippet)
        opt failed check (D-025) or unreadable reply, often cut off at the cap (D-040)
            O->>G: attack_retry (reason; truncated when the reply had no tags)
            O->>P: correction_prompt(attack, real result) or unparsed_prompt(truncated)
            O->>L: complete(attacker), parse_attack, verify_attack again
        end
        alt parse error, timeout or failed check
            O->>G: backfire, hit (attacker is target, half damage)
        else verified
            O->>G: attack_verified
            opt panel configured (D-036)
                O->>S: score_problem(panel, attack): each member solves it like a defender, in parallel
                O->>G: difficulty (value 0.5-2.0, who failed, tokens)
            end
            O->>G: defend_start
            O->>P: defense_prompts(defender, problem)
            O->>L: complete(defender, defender_max_tokens)
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
seeded RNG; each fighter's earlier attack outcomes come from the saved results via
`stats.attack_outcomes` and go to `run_match` as `history`), calling `stats.append_record` after each one, then prints `format_stats` over all
saved records.

`arena synth` runs the same `run_match` with `SyntheticLlm.complete` and `synthetic_verify`
(scripted fighters, no network) for each cell of a skill x attacker-bonus table, or `--compare-rules` / `--adaptive` to compare answer rules or closed-loop attackers.

## Modules

- `models`: dataclasses (`Fighter`, `Attack`, `TurnResult`, `MatchRecord`, `MatchResult`).
- `damage`: pure rule functions and the constants (HP, base damage, max turns, difficulty range and its mapping from the panel).
- `scorer`: `score_problem` asks the reference panel to solve a verified problem (parallel, defender budget) and returns the difficulty.
- `verifier`: SymPy answer equality and the snippet runner (subprocess, timeout, temp dir).
- `battle_log`: per-turn event list with `t` in ms, a schema 2 header (fighters with personas), JSON writer.
- `config`: loads `config/fighters.toml` into settings, providers and fighters.
- `llm`: OpenAI-compatible client per provider, 429 backoff, delay between calls.
- `prompts`: attacker and defender prompts and tag parsing of the replies.
- `cli`: `arena match` and `arena sim` (load `.env` and config, run matches, print output).
- `stats`: balance stats over `MatchRecord`s, plus reading and appending the results JSONL.
- `synthetic`: scripted fighters and the balance sweep behind `arena synth` (D-020).
- `orchestrator`: `play_turn` and `run_match`, the only module that sequences a match.
- `arena_api` (Phase 1): FastAPI app plus an arq worker. `POST /fighters/{id}/spar` (`fighter_routes`) saves a
  `queued` sparring row in Postgres (`store.py`, `match_routes`) and enqueues `play_match`; the worker
  (`jobs.py`) decrypts the owner's key, builds a one-match `LlmClient` with it, calls `run_match` (3 turns) in a
  thread and stores the log and summary (or the failure reason, with the key scrubbed); a spar where the
  fighter replied marks that version verified. `GET /replays` lists public (sim) matches; a sparring replay opens
  only for its owner. `replays.parse_replay` turns a log's events into one reveal-panel record per turn.
  `import_logs` loads old log files. `db.migrate` applies `migrations/`.
- `ratings` / `ranked_routes` (Phase 1, D-043): `POST /fighters/{id}/ranked` picks the closest-rated fighter of another
  owner (`ratings.pick_opponent` over `store.ranked_candidates`), saves a `ranked` match with both versions pinned and
  queues `play_match`. The worker decrypts both keys, plays the match, and `store.finish_ranked` stores the result and
  both Elo changes in one transaction (only while the match is `running`). `GET /leaderboard` is public.
- `auth` / `accounts` (Phase 1): GitHub sign-in (`/auth/github/login` and `/callback`), a session cookie whose
  token is stored hashed, `current_user` for protected routes, and a local-only dev sign-in. The web app
  forwards `/api/*` to the API so the cookie stays same-site.
- `fighters` / `fighter_routes` / `secret_box` (Phase 1): a signed-in user's fighters, each a list of
  numbered versions (provider from `config/fighters.toml`, model, persona, encrypted API key). Responses
  carry only the last four characters of the key; the worker decrypts it to play that fighter.
- `web` (Phase 1): Next.js app that only calls the API. A replay page plays each turn on a Pixi canvas:
  `choreography.planTurn` turns a turn into timed steps (3 to 6 s), `stage.Stage` draws the scene as a
  pure function of (plan, time), `viewer.tsx` holds play, pause, speed and whole-match state.
