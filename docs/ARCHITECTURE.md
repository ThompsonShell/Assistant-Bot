# Architecture (Phase 0 discovery)

Written 2026-11-19 from reading the code at commit `69bd973`, updated the same day
for master plan v2 (paper diary by photo, statistics). Facts only; decisions are
in `OPEN_QUESTIONS.md`. Nothing in this file needed new code.

## 1. Stack at a glance

| Part | What it is |
|---|---|
| Language | Python. Docker image `python:3.12-slim`; the owner's laptop runs 3.12/3.13 |
| Web/API | FastAPI app factory `app.main:create_app`, served by uvicorn. Dashboard is one static page (`backend/app/web/index.html`) |
| Telegram | **Raw Bot API over `httpx`**, long-polling `getUpdates`. No aiogram, no python-telegram-bot |
| Database | SQLAlchemy 2.1 + Alembic (`0001`..`0005`). **SQLite** (`./lifeos.db`) when run locally, **PostgreSQL 16** in `docker-compose.yml` |
| Redis | Web login sessions and rate limit only. Not used by the bot. Tests use `fakeredis` |
| Scheduler | APScheduler `BackgroundScheduler`, **in the same process** as the web app |
| AI | Claude, see section 5 |
| Config | `pydantic-settings` (`app/config.py`), values from environment / `.env` |
| Tests | pytest, 136 tests, in-memory SQLite, no network |

There is no separate worker. One process runs: web app, Telegram thread, scheduler.

## 2. Entry points

- `./scripts/run-local.sh` is the owner's way to run it. It creates `.env` on first run, `source`s it (so the values are exported to the process), kills an old `uvicorn app.main`, then `exec uvicorn app.main:create_app --factory --port 8000`.
- `create_app()` (`app/main.py`) does: create tables if `AUTO_CREATE_TABLES` (default true), bootstrap the admin user, start the scheduler (`_start_scheduler`), start the bot thread (`_start_telegram_bot`), mount routers (health, auth, github, notifications, calendar, chat, web).
- Standalone: `python -m app.jobs.telegram_bot` (bot only), `python -m app.jobs.github_poll` (one poll).
- Docker: `backend/Dockerfile` (non-root, `/health` healthcheck) and `docker-compose.yml` (db + redis + app). **No Railway/VPS config exists in the repo.**

## 3. Telegram bot internals (`app/jobs/telegram_bot.py`)

- Runs in a daemon thread (`run_bot`). Only starts when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set.
- **Owner-only**: `process_update` compares `chat.id` with `TELEGRAM_CHAT_ID`; everyone else gets a refusal. Callback buttons are checked the same way.
- **How commands are registered** (all by hand, there is no decorator/registry):
  1. `handle_text(db, provider, text)` is one `if` chain returning a reply string. Order: help, `reading.handle_reading`, `study.handle_study`, github ranges, repos, jira, news, channels, weather, effort, tasks, plan, done, unknown `/x`, then free text goes to `provider.chat`.
  2. `process_update` handles what needs more than a string: `callback_query` (review buttons), `/news` (photo cards), `/review` (inline keyboard). It runs before `handle_text`.
  3. `HELP` (text) and `BOT_COMMANDS` (the "/" menu, sent with `setMyCommands` at start) are separate manual lists. A new command has to be added to both, plus `MAIN_KEYBOARD` if it should be a button.
- **Only text is read.** `process_update` ignores messages without `text`, so voice, photos and documents are dropped today.
- **No conversation state except one table**: an unfinished `quiz_sessions` row makes plain text count as a quiz answer. There is no multi-step "flow" mechanism yet (the plan's `/diary` flow needs one).
- Free-text chat calls `provider.chat(text, system=SYSTEM_PROMPT)` with **no history** in the Telegram path (the web chat API keeps history in `chat_messages`).
- Message size: `send_message` cuts at 4000 chars; photo captions at 1024.

## 4. Scheduler jobs (`app/main.py::_start_scheduler`)

Timezone for cron jobs = `DISPLAY_TIMEZONE` (**code default is `UTC`**, so the owner's `.env` must set `Asia/Tashkent`). Jobs start only if `ENABLE_SCHEDULER` and Telegram are configured.

| Job id | When | What |
|---|---|---|
| `github_poll` | every 120 s (min 30) | poll watched repos, notify (needs `GITHUB_TOKEN`) |
| `morning_brief` | 08:00 | weather + clothing, then news cards: 3 tech + 2 space |
| `channel_watch` | every 30 min (min 5) | forward keyword-matching posts from public channels |
| `study_review` | 09:00, 14:00, 20:00 | "N cards due" with a Start button, only if N > 0 |
| `study_diary` | 21:00 | nudge if today's diary lacks input or output |
| `study_quiz` | 19:00 | suggest a quiz when the last one is 3+ days old |
| `study_reading` | 18:00 | Mon/Fri/Sun reading nudge until done |

Up to **6 proactive messages per day** can be sent today (see OPEN_QUESTIONS Q5).

## 5. How Claude is called (`app/providers/`)

`get_provider()` picks one provider once per process:

1. `ANTHROPIC_API_KEY` set -> `ClaudeApiProvider` (Anthropic SDK, per-token billing).
2. else `USE_CLAUDE_SUBSCRIPTION` or `CLAUDE_CODE_OAUTH_TOKEN` -> `ClaudeAgentProvider` (name `claude-cli`): runs the **`claude -p` binary in a subprocess** with tools disabled, no session persistence, `ANTHROPIC_*` env stripped, token passed as `CLAUDE_CODE_OAUTH_TOKEN`. Model alias `sonnet`. Timeout 120 s (180 s for plans).
3. else `DeterministicProvider` (no AI, canned replies).

**The owner uses option 2** (confirmed by `scripts/check-ai.sh`: provider `claude-cli`, reply OK).

Interface (`AIProvider`): `chat(prompt, system=None, history=None)`, `plan_tasks(instruction)`, `summarize`, `plan`. Calls are synchronous and stateless. Reasoning effort is read per call from `claude_runtime.json` (`/effort` command, default `medium`).

Consequences for the mentor plan:
- Each AI call starts a CLI process, so expect a few seconds of latency and usage counted against the Claude subscription limits. Exam generation, writing feedback and speaking feedback all go through this path.
- Anthropic's own docs say products should use API-key auth; subscription use is a gray area accepted for private single-user use. This is the owner's decision (OPEN_QUESTIONS Q11).
- The bot's code blocks the Telegram thread while the CLI runs, so a long AI call delays the next update.

## 5a. Photos, files and vision (needed by plan v2, section 7b)

The paper-diary flow is the new core of Phase 1. Today the bot cannot do any step of it:

| Needed | Today |
|---|---|
| Receive a photo and its caption | **No.** `process_update` only reads `message.text`. `photo`, `caption`, `voice`, `document` are ignored |
| Download the file from Telegram | No `getFile` call; no download code |
| Send a local image (charts, heatmap) | **No.** `send_photo` sends a *URL* only. Uploading a file needs a multipart request |
| Give an image to Claude | **No.** The CLI provider pipes **text** to `claude -p` on stdin with `--tools ""`. The API provider (`claude_api.py`) has no image code either |
| Keep photos privately | No storage folder exists. Only `*.db` is gitignored; a `data/` folder would need its own ignore rule |
| Draw charts / heatmap | No `matplotlib`/`Pillow` in `requirements.txt` |
| Multi-step conversation (confirm / edit field / ask a follow-up) | Only inline buttons for review cards and the quiz table. No generic "pending flow" state |
| Inline button callbacks | Yes (`process_callback`, owner-only) |

**Vision through the owner's subscription is the main unknown.** `claude` 2.1.328 offers
`--input-format stream-json` and `--allowedTools`, which are the two likely routes
(send the image as a content block, or allow only the Read tool on one temp file).
I did **not** test either: the sandbox has no logged-in Claude, and I did not want to
send anything on the owner's behalf. It needs a 10-minute spike on the owner's machine
(OPEN_QUESTIONS Q15). The plain Claude API supports images natively, but no API key is
configured.

Handwriting that mixes Uzbek and English is a quality risk for any vision model. The
plan's "nothing counts until confirmed" rule is the right safeguard and should be kept
exactly as written.

## 6. Data model: what exists vs the plan's section 14

| Plan table | Exists as | Gap |
|---|---|---|
| `diary_entries` | `diary_entries(day, learned, recalled, ...)` | plan has 7 fields plus `source` (`paper_photo` or `text`); here only `learned` (=input) and `recalled` (=output) |
| `paper_entries` | none | photo paths, transcription, parsed JSON, minutes per category, AI-off minutes, `confirmed` flag |
| `cards` | `vocab_cards` | uses **SM-2** (`interval_days, ease, reps, lapses`), plan wants **Leitner boxes 1/3/7/14/30**; no `type`, `source`, `active` |
| `card_reviews` | none | |
| `queue_words` | none | needed for the 1100-word PDF queue |
| `exams` | `quiz_sessions` | questions stored as JSON, no `kind` (mini/weekly), no weak-topic data |
| `error_log` | none | |
| `curriculum_items` | none | |
| `lessons_log` | none | |
| `leet_problems` | none | |
| `english_scores` | none | |
| `settings` | `study_kv(key, value)` | currently holds `topic` and `reading_start` only |
| (not in plan) | `reading_logs` | article routine: kind, url, words sent, 2-sentence summary, example tried |
| (existing) | `tasks`, `chat_messages`, `github_repos`, `github_events`, `notifications`, `users`, `audit_logs` | `tasks` has `scheduled_date, category, source`, so lessons can appear as tasks |

All study data lives in the local database file. `*.db` is gitignored.

## 7. Existing commands

From the plan's rule 1 (must not break): `/today /week /month /github /repos /plan /tasks /done /jira /news /channels /weather /effort /help` and free-text chat. All still work.

Added after the plan author's snapshot (not in the plan): `/word /words /review /learned /recall /diary /quiz /drill /read /summary /tried /topic /readlog`. Several of them overlap with the plan's commands (OPEN_QUESTIONS Q2, Q3, Q4).

Changed behaviour you may not expect: `/github` now defaults to **today** (`all` shows the old list); `/today /week /month` list who did what; `/news` and the morning brief send photo cards.

## 8. Jira (`app/integrations/jira.py`)

Read-only by design: one call, `POST /rest/api/3/search/jql` with Basic auth (`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`), JQL = open issues assigned to me. **No create/update code exists.** Part 2 section 6 (import month 1) needs write access.

## 9. Security and privacy facts

- Secrets only in `.env` (gitignored). The bot never prints tokens. Web login: Argon2id + optional TOTP, Redis-backed sessions.
- **The GitHub repo `ThompsonShell/Assistant-Bot` is PUBLIC** (checked via the GitHub API on 2026-11-19). The plan says "the repo is private". Study data is not in git, but anything committed under `docs/` or `data/` would be world-readable. `BOT_MASTER_PLAN` was not committed.
- `tg-business-bot/` is a separate private project; it is gitignored here.

## 9a. Things I could not determine

- The owner's real `.env` values (timezone, whether `JIRA_*` and `WATCH_CHANNELS` are set). I never read `.env`.
- Whether the news feeds and `t.me/s/<channel>` pages work from the owner's network. The build sandbox blocks outside hosts, so article fetching, images and Open-Meteo were only tested with fixtures.
- The PDF's location and whether it has a text layer or is scanned.
- Whether IELTS audio exists.
- Telegram voice-note and photo behaviour: not implemented, so untested.
- Whether `claude -p` can read an image on the owner's setup (see 5a).
- How well Claude reads the owner's handwriting (Uzbek + English). Only a real sample page can answer this.

## 10. Documentation that is out of date

`README.md` still says "Phase 3", describes Claude via `claude-agent-sdk` (replaced by the `claude -p` subprocess) and lists only the early commands. `LOCAL_SETUP.md` was not re-checked. Updating them is cheap; not done in Phase 0.
