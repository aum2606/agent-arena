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

- **Comparing two answers can hang the worker.** Answers are read by a restricted parser that never
  evaluates them (D-047), but `sympy.simplify` has no time limit: a 32-character answer such as
  `(x+1)**200*(x+2)**200*(x+3)**200` ran for over 25 seconds, and the single worker is blocked meanwhile.
  A fix (a helper process with a time limit) is next.
- **The CLI does not sandbox model-written code** (D-002). Only the web worker uses a gVisor sandbox
  (D-044). Run the CLI on a machine you are willing to risk, with minimal credentials.
- **The local Docker stack is not safe to expose.** Its worker runs with the sandbox off, it enables a
  "sign in as anyone" form, and the Postgres password is a published default. Bind it to localhost only.
- **Limits and filters are basic.** Rate limits cover only signed-in users' write routes (D-050); visitors
  who are not signed in are not limited. The problem filter (D-049) is a set of rules for instructions
  aimed at the opponent: it does not catch hateful or adult text, or a cleverly reworded instruction.
  There is no Content-Security-Policy yet.

## Handling secrets

Users' provider API keys are encrypted at rest with `KEY_ENCRYPTION_SECRET` (D-034). Keep that secret out
of the repository and back it up: without it the saved keys cannot be read again.
