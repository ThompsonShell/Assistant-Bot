# Changelog

Newest first. One entry per feature or fix.

## 2026-11-19 (evening)
- **Bot UX:** bare commands start guided conversations (`conversation_state`, Alembic 0006); `/start` and `/help` show a short inline main menu (Bugun, Kundalik, So'z qo'shish, Takrorlash, Imtihon, Statistika, Yana); every reply ends with one best-next-action button; empty states offer a fixing button; unconfigured features are hidden; one command registry feeds all lists. `/bugun` added.
- **Diary checklist:** `/diary` shows input, output, words (3/day) and the paper photo with a button for each missing item. Evening reminder asks for the photo.
- **Paper diary by photo:** photo intake, vision reading (API and CLI routes), confirm / edit / wrong date / retake, `/date`, `/delete_entry`, next-morning reminder, `paper_entries` (Alembic 0007). CLI vision route unverified.
- **Statistics:** `/stats [kun|hafta|oy|yil]` and `/streak` from confirmed entries. `/stats github` keeps the old meaning.

## 2026-11-19
- **Docs:** updated for master plan v2 (paper diary by photo, statistics): new section 5a in `ARCHITECTURE.md`, questions Q15-Q19 in `OPEN_QUESTIONS.md`. Still no feature code.
- **Docs:** Phase 0 discovery: `ARCHITECTURE.md`, `OPEN_QUESTIONS.md`. No feature code.
- **Reading routine:** `/read`, `/summary`, `/tried`, `/topic`, `/readlog`; Mon/Fri/Sun reminder; max 5 new words per article. Tables `reading_logs`, `study_kv` (Alembic 0005).
- **Dependencies:** upgraded to latest (FastAPI 0.164, SQLAlchemy 2.1, pydantic 2.14, redis 8, pytest 9, ...).

## 2026-11-17
- **Self-study module:** `/word /words /review /learned /recall /diary /quiz /drill`, SM-2 scheduling, reminders (Alembic 0004).
- **Space news:** `/news space`, space stories in the morning brief.

## 2026-11-16
- **News cards:** `/news` and the morning brief send photo cards (image, short text, link). `/github` defaults to today; `/today /week /month` list who did what.

## 2026-11-12 .. 2026-11-13
- `/news`, `/channels` (keyword-filtered public channels, MAANG + space keywords), `/jira` (read-only), `/weather`, 08:00 morning brief.

## Earlier
- GitHub monitoring and analytics, Telegram bot, calendar (`/plan /tasks /done`), Claude chat via the `claude` CLI, `/effort`, web dashboard.
