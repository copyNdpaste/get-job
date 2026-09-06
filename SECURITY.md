# Security and privacy

get-job is designed as a local-first application. It processes personal resume evidence and
stores collected job data, so its safest supported deployment is a single-user machine.

## Safe defaults

- Frontend and backend ports bind only to `127.0.0.1`.
- PostgreSQL is not published to the host and is reachable only inside Docker Compose.
- Candidate profiles, `.env`, browser sessions, caches, and database exports are ignored by Git.
- Personal Markdown is allowed only in ignored `*.local.md` or `*.private.md` files. Tracked
  Markdown must contain documentation and synthetic examples only.
- A local OpenAI-compatible server is the default AI provider. If it is unavailable, the application keeps using
  deterministic rule-based scores instead of falling back to a paid API.
- Crawler URL imports are restricted to each supported site's HTTPS hostname and job-detail path.
- Cross-host redirects are rejected.

The local API has no user authentication because it is not intended to be exposed. Do not bind
it to `0.0.0.0`, forward its ports, or deploy it on a public server without adding authentication,
authorization, rate limiting, TLS, and a production deployment configuration.

## Personal profile handling

Copy `backend/examples/candidate-profile.example.json` to
`data/candidate-profile.local.json`. Only the anonymous example belongs in Git. The real local
file may contain resume evidence and is mounted read-only into the backend container.

Before every public push, review `git status --short` and the staged diff. Never force-add ignored
profile, resume, `.env`, database, cache, or browser-session files.

Run `./scripts/security-check.sh` before staging or publishing. It checks publishable working files and the actual staged blobs for private paths, personal filesystem
paths, non-example email addresses, and common credential signatures without printing matched values
or private filenames. Use `./scripts/security-check.sh --history` to include every reachable commit,
tag, and file blob. Run Gitleaks with `--redact=100 --log-opts=--all` as a separate full-history scan.
The example database credentials are development placeholders; put real values only in ignored `.env`.

## Slack notifications

Slack delivery is off by default. Enable it only in the ignored local `.env` using either an
incoming webhook or a bot token plus channel ID. Never commit those values. The notifier accepts
only the fixed Slack hosts and sends public company, position, technology, score, and job-link
metadata. Resume text, matching evidence, contact details, private notes, and credentials are
never included.

If a Slack secret is accidentally committed, revoke it in Slack immediately, remove it from the
entire Git history, and rotate any related credentials before publishing the repository.

## Public release checklist

1. Run `./scripts/security-check.sh`.
2. Confirm `git status --short` contains no `.env`, `data/` private files, resumes, databases,
   browser profiles, caches, credentials, or `*.local.md` files.
3. Review `git diff --cached` and verify every fixture is anonymous and synthetic.
4. Confirm Docker ports remain bound to `127.0.0.1` and PostgreSQL has no host port.
5. Confirm `AI_ALLOW_REMOTE=false` and `SLACK_NOTIFY_ENABLED=false` in public examples.

## AI providers and possible charges

The default configuration is:

```env
AI_PROVIDER=openai-compatible
AI_BASE_URL=http://host.docker.internal:1234
AI_MODEL=auto
AI_ALLOW_REMOTE=false
```

With `AI_ALLOW_REMOTE=false`, startup rejects non-local AI endpoints. There is no automatic cloud
fallback and no automatic model purchase or API-key discovery.

A user may deliberately configure an OpenAI-compatible remote service, but must set
`AI_ALLOW_REMOTE=true`. Doing so can transmit candidate and job data outside the machine and may
incur charges. That opt-in belongs only in the ignored `.env` file.

The optional Codex bridge uses the user's existing ChatGPT login rather than an API key. It still
sends structured resume evidence, the search question, and selected job facts to OpenAI and consumes
the user's Codex plan allowance. It is enabled only with `AI_PROVIDER=codex` and
`AI_ALLOW_REMOTE=true` in the ignored local `.env`. The bridge binds to loopback, disables Codex
tools, and never mounts Codex credentials into a container.

## Reporting a vulnerability

Do not open a public issue containing credentials, personal resume data, or a working exploit.
Use the repository's private vulnerability-reporting channel when available, and include affected
versions, reproduction steps, impact, and a suggested mitigation.

## Commit identity and feature branches

Use a GitHub `users.noreply.github.com` author address instead of a personal email.
The integration branch is `main`; feature branches group collection, matching, AI analysis,
dashboard, and documentation work. Run the security checks before each push.

Enable the checked-in guards in each clone:

```bash
git config core.hooksPath .githooks
```

`pre-commit` checks working and staged content; `pre-push` additionally checks reachable history.
These local guards complement, rather than replace, Gitleaks and manual privacy review.
