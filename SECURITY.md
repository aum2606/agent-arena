# Security policy

## Reporting a vulnerability

Please report it privately through GitHub: on the repository page open **Security → Report a
vulnerability** (private vulnerability reporting). Do not open a public issue or pull request for it.

Include what you found, how to reproduce it, and what it could do. You will get a reply as soon as the
maintainer can manage; this is a small volunteer project, so please allow some days.

## Status of the project

Agent Arena is a pre-release MVP. **Do not run a public instance for people you do not trust yet.**

## Threat model

Who can do what, as built (D-077 to D-081):

- **A visitor with no account** can read the public replay list and the leaderboard and start a GitHub sign-in, each
  limited per address. Everything else needs a session; every route that reads or changes a fighter, a key or a match
  checks that it belongs to the signed-in user.
- **A signed-in player** controls their own fighters, keys (encrypted at rest, never shown again), matches and account.
  They can spend the server's own free-tier keys only through spars and ranked matches, each capped per fighter, per
  user and for the whole site per day; two accounts can be paired at most three times a day.
- **A player's model, and the problems it writes**, are untrusted. The text a player's persona or a model produces is
  shown only to the players of that match, and rendered as plain text (the web app has no place that inserts HTML, and a
  strict Content-Security-Policy backs that up).
- **Prompt injection** is a model obeying text it should only have read: a problem that says "answer 0", a persona that
  says "ignore the rules". It can change who wins a match and what a replay says. It cannot reach site data: no prompt
  carries a key or a secret, a model is offered no tools and can only write text, model output is read by a restricted
  parser and never evaluated, and model-written code runs in a gVisor sandbox with no network. Problems reach a model
  as delimited, untrusted data, a rule filter turns obvious attempts into fouls, and on ranked hits a reference panel
  can overturn a wrong result. Cheating that stays inside the game (a model told to lose, two cooperating accounts) is
  limited, not prevented.
- **A break-in to the API process** gets a database role that can only read and write rows, not the database owner's
  password. It does hold `KEY_ENCRYPTION_SECRET` and the GitHub client secret (it needs both), so it could decrypt every
  stored provider key and act as the site's GitHub app. Only the worker needs to decrypt keys; having the API encrypt
  with a public key and the worker hold the private one would close that, and is not done.
- **The person running the site** can read any stored data. Users' keys are encrypted with a key only the deployer
  holds, which protects them from a copy of the database, not from the deployer.

Security-relevant events (sign-ins, key changes, deletions, refused requests, rate limits) are logged by the API as
`security event=... key=value` lines on the `arena.security` logger, never with a secret in them.

## Known issues

These are known and tracked, so you do not need to report them:

- **A crafted answer can still cost the worker a few seconds.** Answers are read by a restricted parser
  that never evaluates them (D-047) and compared in a helper process with a 5-second limit (D-052), but a
  slow answer still occupies the single worker for about 8 seconds (the limit plus a restart). A user's
  matches are capped (a daily limit per fighter, two waiting at a time), so the cost is bounded, not zero.
- **Your key is yours to remove, with limits.** Deleting a fighter or your account erases every version and key stored
  for it (D-070, D-078); an old version of a fighter you keep still holds its old key. The server's secret can be rotated
  (D-078). A fighter is spent by other players' ranked matches only if you turn that on for it; then your key pays for
  them, up to its daily cap.
- **A deliberately wrong answer is only caught on ranked hits.** An attack passes if its snippet prints the stated
  answer, so a persona can make a model state a wrong answer on purpose. Ranked matches now have the reference panel
  look at a hit before it lands (D-069); sparring, sims and code strikes do not, and a panel member without a server
  key (or a panel that is down) leaves the hit standing.
- **The CLI does not sandbox model-written code** (D-002). Only the web worker uses a gVisor sandbox
  (D-044). Run the CLI on a machine you are willing to risk, with minimal credentials.
- **The local Docker stack is not safe to expose.** Its worker runs with the sandbox off, it enables a
  "sign in as anyone" form, and the Postgres password is a published default. Binding it to localhost is not
  enough: a tunnel or proxy running on the same machine reaches it as localhost. Since D-068 the API refuses the
  "sign in as anyone" form, and the worker refuses `ARENA_SANDBOX=off`, whenever `PUBLIC_URL` is not a localhost
  address, and since D-080 it also refuses the form for a request that came through a tunnel or proxy header with a
  non-local address, and warns at start-up when it is on. That is a guard, not a hardening of the stack: set
  `PUBLIC_URL` to the real address before exposing anything, and never tunnel the local stack. The containers run as an unprivileged
  user, and the worker no longer receives the whole `.env`, only the provider keys, the secret and the database.
- **Limits and filters are basic.** Signed-in users' write routes are rate limited (D-050), and the
  routes anyone can reach (replays, the leaderboard, GitHub sign-in) are limited per visitor address
  (D-063). That only works behind a reverse proxy that overwrites one header with the visitor's address
  and a `CLIENT_IP_HEADER` naming it; without that every visitor shares one allowance, and a header the
  proxy passes through lets a visitor pick their own address. The problem filter (D-049) is a set of rules
  for instructions aimed at the opponent (with common look-alike letters folded in, D-080): it does not catch hateful
  or adult text, other languages, or a cleverly reworded instruction. A deployer can list words to refuse in
  `blocked_terms`; none are built in.
- **Left over from the audits** (details in D-069, D-070 and D-077 to D-081): a ranked opponent's daily cap can be
  overshot a little by parallel requests; the problem filter is English rules and bypassable with other languages; a code
  strike's reference solution can be a lookup table; a snippet can run for its limit plus a 10-second start-up allowance;
  the panel that reviews ranked hits is a majority of free-tier models, so it can be wrong; old fighter versions keep their
  keys until the fighter is deleted; several devices can be signed in at once (and "sign out everywhere" ends them all);
  the shared daily budget counts matches, not tokens; two accounts that cooperate can still move each other's rating
  within the pair limit; the database owner, used only by the one-shot migration, is a superuser.
- **Images and actions are pinned by digest or commit** (D-071) and Dependabot proposes updates; the base image the sandbox runs
  in is built from a pinned digest plus SymPy, and the worker builds it once. The pins are only as fresh as the last merged update.
- **The Content-Security-Policy is new** (D-064): scripts and styles run only with a per-request nonce, and
  no eval is allowed in production. It was checked page by page in a browser, but only on a local
  production build; HTTPS and Strict-Transport-Security still belong to the reverse proxy.

## Before you deploy

None of this is done by the repository; it is the deployer's checklist (D-068 to D-071 say why).
[`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) is the step-by-step version (D-072):

- Set `PUBLIC_URL` to the real `https://` address on **both** the API and the worker. The "sign in as anyone" form and
  `ARENA_SANDBOX=off` are only refused when it says so, and the session cookie is `Secure` only for `https`.
- Run the worker on a host with Docker and gVisor (`runsc`), never `ARENA_SANDBOX=off`, and keep it off the public network.
- Put a reverse proxy in front that terminates TLS, sends HSTS, and **overwrites** one header with the visitor's address;
  name it in `CLIENT_IP_HEADER` on the API and the web server. Keep the web server's port 3000 and the API's port 8000
  reachable only from the proxy, or a visitor can pick their own address.
- Make a production GitHub OAuth app (one callback each) and a **new** `KEY_ENCRYPTION_SECRET`, and back the secret up.
- Use `docker-compose.prod.yml` (D-072, D-079): it refuses to start without real passwords for Postgres (the owner),
  `APP_DB_PASSWORD` (the limited role the API and the worker use) and Redis; the compose defaults are for localhost.
- Decide what you will not host: list any words to refuse in `blocked_terms` (D-080).
- Read the `arena.security` log lines now and then (`docker compose logs api | grep "security event="`).
- On GitHub (the repository owner's settings, not the code's): private vulnerability reporting, branch protection on
  `main` requiring the CI jobs, Dependabot security updates, and keep secret scanning and push protection on.

## Handling secrets

Users' provider API keys are encrypted at rest with `KEY_ENCRYPTION_SECRET` (D-034). Keep that secret out
of the repository and back it up: without it the saved keys cannot be read again. The API and the worker refuse to
start without a valid one (D-066).
