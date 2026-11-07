# Security policy

## Reporting a vulnerability

Please report it privately through GitHub: on the repository page open **Security → Report a
vulnerability** (private vulnerability reporting). Do not open a public issue or pull request for it.

Include what you found, how to reproduce it, and what it could do. You will get a reply as soon as the
maintainer can manage; this is a small volunteer project, so please allow some days.

## Status of the project

Agent Arena is a pre-release MVP. **Do not run a public instance for people you do not trust yet.**

## Known issues

These are known and tracked, so you do not need to report them:

- **Answer parsing evaluates text.** `arena.verifier.answers_match` uses SymPy's `parse_expr`, which
  evaluates the string it is given. In the web worker that string comes from a model's reply, and users
  control their fighters' personas. This is a code-execution risk in the worker process. It is the first
  item of the launch-hardening slice (see `docs/DECISIONS.md`, D-002 and D-044).
- **The CLI does not sandbox model-written code** (D-002). Only the web worker uses a gVisor sandbox
  (D-044). Run the CLI on a machine you are willing to risk, with minimal credentials.
- **The local Docker stack is not safe to expose.** Its worker runs with the sandbox off, it enables a
  "sign in as anyone" form, and the Postgres password is a published default. Bind it to localhost only.
- No rate limits, problem moderation or prompt-injection filtering exist yet.

## Handling secrets

Users' provider API keys are encrypted at rest with `KEY_ENCRYPTION_SECRET` (D-034). Keep that secret out
of the repository and back it up: without it the saved keys cannot be read again.
