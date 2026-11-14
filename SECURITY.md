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

- **A crafted answer can still cost the worker a few seconds.** Answers are read by a restricted parser
  that never evaluates them (D-047) and compared in a helper process with a 5-second limit (D-052), but a
  slow answer still occupies the single worker for about 8 seconds (the limit plus a restart), and
  nothing yet limits how many a user can send.
- **The CLI does not sandbox model-written code** (D-002). Only the web worker uses a gVisor sandbox
  (D-044). Run the CLI on a machine you are willing to risk, with minimal credentials.
- **The local Docker stack is not safe to expose.** Its worker runs with the sandbox off, it enables a
  "sign in as anyone" form, and the Postgres password is a published default. Bind it to localhost only.
- **Limits and filters are basic.** Signed-in users' write routes are rate limited (D-050), and the
  routes anyone can reach (replays, the leaderboard, GitHub sign-in) are limited per visitor address
  (D-063). That only works behind a reverse proxy that overwrites one header with the visitor's address
  and a `CLIENT_IP_HEADER` naming it; without that every visitor shares one allowance, and a header the
  proxy passes through lets a visitor pick their own address. The problem filter (D-049) is a set of rules
  for instructions aimed at the opponent: it does not catch hateful or adult text, or a cleverly reworded
  instruction.
- **The Content-Security-Policy is new** (D-064): scripts and styles run only with a per-request nonce, and
  no eval is allowed in production. It was checked page by page in a browser, but only on a local
  production build; HTTPS and Strict-Transport-Security still belong to the reverse proxy.

## Handling secrets

Users' provider API keys are encrypted at rest with `KEY_ENCRYPTION_SECRET` (D-034). Keep that secret out
of the repository and back it up: without it the saved keys cannot be read again.
