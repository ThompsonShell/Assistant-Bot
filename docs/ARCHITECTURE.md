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
- **How commands are registered** (updated 2026-11-19):
  1. `app/bot/registry.py` is the one list of commands (name, short description, group, optional "needs" setting). The "/" menu, the "Yana" screen and the main menu are built from it; commands whose feature is not configured (`/jira`, `/channels`, `/news` when disabled) are hidden from all of them but still answer if typed.
  2. `handle_message(db, provider, text) -> Reply` is what the owner sees. A `Reply` is text plus inline buttons (`app/bot/ui.py`). It adds the menu screens (`/start /help /menu /more /bugun /diary /stats /streak /photo`), guided conversations, empty-state buttons and **one best-next-action button** under every reply (`app/bot/views.py::best_next`).
  3. `handle_text(db, provider, text) -> str` is still the one-message router (an `if` chain: reading, study, github ranges, jira, news, weather, effort, tasks, plan, done, then free text to `provider.chat`). `handle_message` calls it, so every old command keeps working.
  4. `process_update` handles what needs more than a string: photos, `callback_query`, `/news` (photo cards), `/review` (inline keyboard).
  5. Most buttons are `do:<command>`: tapping one runs that command exactly as if it was typed.
- **Guided conversations** (`app/bot/flows.py`, `paper_flow.py`): a bare command (`/word`, `/learned`, `/recall`, `/summary`, `/plan`, `/done`, `/topic`, `/drill`, `/date`, `/delete_entry`) asks one question and stores what it waits for in the `conversation_state` table (one row, 30-minute expiry). The next plain message is used as the answer. A new command or `/cancel` drops the pending question.
- **Photos are handled** (`_photo_of`, `_download_file`, `_handle_owner_photo`): the largest size, or an image sent as a file, up to 10 MB, owner only, edits ignored. Voice notes and other files are still dropped.
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
| `study_diary` | 21:00 | asks for the paper-diary photo (text `/diary` is the fallback); quiet once a photo is confirmed or text input+output exist |
| `study_quiz` | 19:00 | suggest a quiz when the last one is 3+ days old |
| `study_reading` | 18:00 | Mon/Fri/Sun reading nudge until done |
| `study_unconfirmed` | 08:10 | shows each unconfirmed paper-diary entry once |

Up to **8 proactive messages per day** can be sent today (brief, unconfirmed entry, 3 review nudges, reading, quiz, diary), against the plan's limit of 2 (see OPEN_QUESTIONS Q5). Not changed yet, because the owner has not answered Q5.

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

## 5a. Photos, files and vision (plan v2, section 7b)

Status after the 2026-11-19 implementation:

| Needed | Now |
|---|---|
| Receive a photo and its caption | **Done.** `message.photo` (largest size) and image documents; caption read for `date: YYYY-MM-DD` |
| Download the file from Telegram | **Done.** `getFile` then the file URL, 10 MB limit |
| Keep photos privately | **Done.** `data/diary_photos/` (`DIARY_PHOTO_DIR`), `data/` is gitignored, files are mode 600, removed by `/delete_entry` or "Qayta rasm". Photos are still sent to Claude to be read |
| Give an image to Claude | **Code done, one route unverified.** `ClaudeApiProvider.vision` sends a base64 image block (standard API). `ClaudeAgentProvider.vision` runs `claude -p` with **only the Read tool** on a private temporary copy. Both are tested with fakes only |
| Multi-step conversation | **Done.** `conversation_state` table |
| Send a local image (charts, heatmap) | Not done. `send_photo` sends a URL only; Phase 7 |
| Draw charts / heatmap | Not done. No `matplotlib` yet; Phase 7 |

**The CLI vision route has never run against a real login** (OPEN_QUESTIONS Q15). If it
fails, the bot keeps the photo and asks for the numbers by typing, so the day is
not lost; it does not invent anything. The plain Claude API route needs
`ANTHROPIC_API_KEY`, which is not configured.

How the flow protects the data: the prompt forbids correcting or inventing text and
asks for `null` when unsure; numbers are validated (0-1440 per field, a day cannot
exceed 24 h) and never guessed; missing numbers are asked one at a time; the date
comes from the caption, then `/date`, then the page, then today, and can always be
corrected; nothing counts until Confirm; an unreadable page is discarded and a
retake is requested.

Handwriting that mixes Uzbek and English is a quality risk for any vision model.
Only a real sample page can show how well it works.

## 6. Data model: what exists vs the plan's section 14

| Plan table | Exists as | Gap |
|---|---|---|
| `diary_entries` | `diary_entries(day, learned, recalled, ...)` | plan has 7 fields plus `source` (`paper_photo` or `text`); here only `learned` (=input) and `recalled` (=output) |
| `paper_entries` | `paper_entries` (Alembic 0007) | done: one row per day, photo paths, transcription, parsed JSON, minutes per category, AI-off, `confirmed`, `reminded`. Mistakes stay on the entry until an error log exists |
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
| (not in plan) | `conversation_state` | what the bot waits for after a bare command or a photo (Alembic 0006) |
| (not in plan) | `reading_logs` | article routine: kind, url, words sent, 2-sentence summary, example tried |
| (existing) | `tasks`, `chat_messages`, `github_repos`, `github_events`, `notifications`, `users`, `audit_logs` | `tasks` has `scheduled_date, category, source`, so lessons can appear as tasks |

All study data lives in the local database file. `*.db` is gitignored.

## 7. Existing commands

From the plan's rule 1 (must not break): `/today /week /month /github /repos /plan /tasks /done /jira /news /channels /weather /effort /help` and free-text chat. All still work.

Added after the plan author's snapshot: `/word /words /review /learned /recall /diary /quiz /drill /read /summary /tried /topic /readlog`. Added from master plan v2: `/menu /bugun /photo /date /delete_entry /stats /streak /cancel`, plus sending a photo. `/stats` used to be an alias of `/week`; that is now `/stats github`. Several of them overlap with the plan's commands (OPEN_QUESTIONS Q2, Q3, Q4).

Changed behaviour you may not expect: `/github` now defaults to **today** (`all` shows the old list); `/today /week /month` list who did what; `/news` and the morning brief send photo cards.

## 8. Jira (`app/integrations/jira.py`, `app/bot/jira_flow.py`)

Reads freely, **creates only after a preview and a tap on "Yaratish"**; it never edits, moves or deletes.

- `/jira` lists my open issues; `/jira status` proves the connection (`/myself`); `/jira add <title> [ertaga|YYYY-MM-DD] [#label]` or plain words ("Jira ga task qo'sh: ...") show a preview (project, title, due date, labels) with [Yaratish] [Loyiha] [Bekor].
- Project: `JIRA_PROJECT_KEY`, or chosen once from the account's projects with buttons and remembered (`study_kv`). Issue type: `JIRA_ISSUE_TYPE` (default Task) if the project has it, else the first ordinary type.
- Errors are explained (401 wrong token, 403 no permission, 404 wrong URL or project, 400 the field Jira rejected). When a setting is empty, the bot names the missing variable (never its value).
- `JIRA_BASE_URL` is tolerated with or without `https://`, with quotes, or with a pasted board URL.
- Not yet done: import of the month-1 plan (OPEN_QUESTIONS Q10), editing and transitions.

## 8a. Conversation memory (`app/bot/memory.py`)

Each Claude call is independent (`claude -p` keeps no session), so the bot hands over what it should know: the last 16 messages from `chat_messages` (shared with the dashboard chat, 6000-character budget, always starting with the owner), the facts saved with `/remember` or "eslab qol: ..." (`memory_facts`, max 60), and today's date. Errors, commands, guided flows and quiz answers are not stored as chat.

## 9. Security and privacy facts

- Secrets only in `.env` (gitignored). The bot never prints tokens. Web login: Argon2id + optional TOTP, Redis-backed sessions.
- **The GitHub repo `ThompsonShell/Assistant-Bot` is PUBLIC** (checked via the GitHub API on 2026-11-19). The plan says "the repo is private". Study data is not in git, but anything committed under `docs/` or `data/` would be world-readable. `BOT_MASTER_PLAN` was not committed.
- `tg-business-bot/` is a separate private project; it is gitignored here.

## 9a. Things I could not determine

- The owner's real `.env` values (timezone, whether `JIRA_*` and `WATCH_CHANNELS` are set). I never read `.env`.
- Whether the news feeds and `t.me/s/<channel>` pages work from the owner's network. The build sandbox blocks outside hosts, so article fetching, images and Open-Meteo were only tested with fixtures.
- The PDF's location and whether it has a text layer or is scanned.
- Whether IELTS audio exists.
- Telegram voice notes: not implemented.
- Whether `claude -p` can read an image on the owner's setup (see 5a). Photo download and the whole confirm flow were tested with fake Telegram and fake vision only.
- How well Claude reads the owner's handwriting (Uzbek + English). Only a real sample page can answer this.

## 10. Documentation that is out of date

`README.md` still says "Phase 3", describes Claude via `claude-agent-sdk` (replaced by the `claude -p` subprocess) and lists only the early commands. `LOCAL_SETUP.md` was not re-checked. Updating them is cheap; not done in Phase 0.
