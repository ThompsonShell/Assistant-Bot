# Private AI LifeOS

A **private, single-user** personal intelligence & productivity platform — your
own digital chief-of-staff. It watches your GitHub activity, plans your week,
tracks productivity, and notifies you privately, with security and privacy as
first-class requirements.

> **Status:** Phase 2 — **GitHub Monitoring** on top of the secure Foundation.
> Polls watched repos, tags actors (human / bot / Action), stores events,
> computes analytics, records notifications, and can push alerts to a private
> Telegram bot. Calendar/planning and the web dashboard come next.

## Design decisions (so far)

- **No automated AI yet.** The MVP is deterministic and costs nothing to run.
  A Claude Pro subscription **cannot** legitimately power an unattended backend
  — the supported path for that is the Claude *API*. AI access sits behind a
  provider abstraction (`app/providers`) with a no-AI `DeterministicProvider`
  active today, so the Claude API can be dropped in later as a config change.
- **Runs on your own machine.** The GitHub module will **poll** (no public
  webhook URL needed) and notifications will use Telegram **long-polling** —
  both work from a home machine with no inbound ports.
- **Secure modular monolith.** One FastAPI backend with clean module
  boundaries; Postgres + Redis.

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis
- **Security:** Argon2id passwords, optional TOTP 2FA, server-side sessions,
  CSRF protection, login rate limiting, structured logging with secret
  redaction, append-only audit log
- **Dev/infra:** Docker Compose, pytest

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env — at minimum set APP_SECRET_KEY and ADMIN_PASSWORD.
python -c "import secrets; print(secrets.token_urlsafe(48))"   # for APP_SECRET_KEY

docker compose up --build
```

Then:

- `GET http://localhost:8000/health` → liveness
- `GET http://localhost:8000/ready` → DB + Redis readiness
- `GET http://localhost:8000/docs` → interactive API docs

On first start the app creates your admin user from `ADMIN_USERNAME` /
`ADMIN_PASSWORD`. It never overwrites an existing user.

## Run the backend locally (without Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# SQLite + localhost Redis is fine for dev; or point DATABASE_URL at Postgres.
export APP_SECRET_KEY=dev-secret
export ADMIN_PASSWORD='choose-a-strong-password'
export DATABASE_URL='sqlite+pysqlite:///./lifeos.db'
export REDIS_URL='redis://localhost:6379/0'

uvicorn app.main:create_app --factory --reload
```

## Database migrations (Alembic)

Schema is managed by Alembic. For convenience, `AUTO_CREATE_TABLES=true` also
creates tables on startup in dev; set it to `false` to rely solely on
migrations.

```bash
cd backend
alembic upgrade head          # apply migrations
alembic revision -m "msg"     # create a new migration (autogenerate optional)
```

## Tests

The suite uses in-memory SQLite + fakeredis, so **no servers are required**:

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Covered: secret redaction, password hashing, TOTP, audit-log redaction, and the
full auth flow (login, CSRF-protected logout, rate limiting, session listing,
TOTP setup/enable/enforcement).

## Auth API (Foundation)

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | `{username, password, totp_code?}` → sets session cookie, returns CSRF token |
| POST | `/auth/logout` | requires `X-CSRF-Token` |
| GET  | `/auth/me` | current user + CSRF token + `ai_available` |
| GET  | `/auth/sessions` | list active sessions (ids masked) |
| POST | `/auth/sessions/revoke` | `{sid}`, requires CSRF |
| POST | `/auth/totp/setup` | re-auth with password; returns secret + `otpauth://` URI |
| POST | `/auth/totp/enable` | verify a code to turn 2FA on |
| POST | `/auth/totp/disable` | password + code |

State-changing requests send the CSRF token (from the login/`me` response) in
the `X-CSRF-Token` header. The session id lives in an HttpOnly cookie.

## GitHub Monitoring (Phase 2)

Watches repositories by **polling** (no public URL needed — works on a home
machine). Each event is de-duplicated by its GitHub id, the actor is tagged,
and a human-readable summary is stored. Notifications are recorded for the
dashboard and, if configured, pushed to your private Telegram bot.

**Setup:**
1. Create a **fine-grained read-only PAT**
   (https://github.com/settings/personal-access-tokens) with read access to
   *Contents, Metadata, Issues, Pull requests*. Put it in `.env` as
   `GITHUB_TOKEN`.
2. (Optional) Create a Telegram bot via **@BotFather**, set `TELEGRAM_BOT_TOKEN`
   and your numeric `TELEGRAM_CHAT_ID`. Without these, alerts still appear in
   the dashboard feed.
3. Start the app — a background poller runs every `GITHUB_POLL_INTERVAL_SECONDS`.
   You can also poll once on demand: `python -m app.jobs.github_poll`.

**Actor tagging:** `human`, `bot` (`*[bot]`), `github_action`
(`github-actions[bot]`), `app`, or `unknown`. It **never** claims a commit was
"AI-generated" — that can't be reliably detected from GitHub metadata, so
AI-assisted work is indistinguishable from human work here and is tagged
`human`.

| Method | Path | Notes |
|---|---|---|
| GET | `/github/repos` | list watched repos |
| POST | `/github/repos` | `{owner, name}` — start watching (CSRF) |
| DELETE | `/github/repos/{id}` | stop watching (CSRF); events are kept |
| GET | `/github/events` | activity feed; filters: `repo`, `actor_type`, `limit` |
| GET | `/github/analytics?range=` | `today\|yesterday\|week\|last_week\|month\|last_month\|year` |
| GET | `/github/notifications` | delivery history |
| POST | `/github/poll` | poll all watched repos now (CSRF) |

Analytics are computed from **stored real data** and labelled as *activity
volume, not productivity*. Ranges honour `DISPLAY_TIMEZONE`.

> **Privacy/security:** GitHub access is **read-only**. The Telegram channel
> only ever messages **you** (your own chat id). No code path sends a message
> to any contact — a hard project rule. Tokens are never logged or returned by
> any endpoint; raw event payloads are redacted before storage.

## Security posture

- No public registration; exactly one user.
- Secrets (passwords, TOTP secrets, tokens) are never logged or placed in audit
  detail; a redaction filter masks them as defense-in-depth.
- Every sensitive action is written to an append-only audit log.
- Sessions are server-side (Redis) and individually revocable.
- Future integrations (GitHub, calendar) start **read-only**, least-privilege,
  and no outbound message is ever sent without explicit, separate opt-in.

## Project layout

```
backend/app/
  config.py          settings (env-driven)
  redaction.py       secret redaction (logs/audit/AI context)
  logging_config.py  structured JSON logging
  db.py              engine/session helpers
  models/            User, AuditLog
  security/          passwords, TOTP, sessions, rate limit, CSRF, deps
  audit/             audit-log service
  providers/         AI provider interface + DeterministicProvider (no-AI)
  integrations/github/  client, actor tagging, event summarizer, poller
  notifications/     channel interface + Telegram + dashboard + notifier
  analytics/         timezone-aware ranges + GitHub metrics
  jobs/              background poll job (CLI + scheduler)
  models/            User, AuditLog, GitHubRepo, GitHubEvent, Notification
  api/               health + auth + github routes
  main.py            application factory (+ optional poll scheduler)
backend/alembic/     migrations (0001 foundation, 0002 github monitoring)
backend/tests/       pytest suite (SQLite + fakeredis, no network)
```
