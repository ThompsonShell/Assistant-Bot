# Private AI LifeOS

A **private, single-user** personal intelligence & productivity platform — your
own digital chief-of-staff. It watches your GitHub activity, plans your week,
tracks productivity, and notifies you privately, with security and privacy as
first-class requirements.

> **Status:** Phase 1 — **Foundation** (secure single-user auth, audit log,
> secret redaction, DB + migrations, containerized dev stack, tests).
> GitHub monitoring, analytics, calendar/planning, and notifications come next.

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
  api/               health + auth routes
  main.py            application factory
backend/alembic/     migrations
backend/tests/       pytest suite (SQLite + fakeredis)
```
