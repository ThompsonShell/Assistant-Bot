"""The single list of bot commands.

The "/" menu, the "Yana" screen and the main menu are all built from here, so
they cannot drift apart. A command can depend on a setting (``needs``); when
that is not configured it is hidden from every list. The command itself still
answers if someone types it, with setup instructions.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import settings


@dataclass(frozen=True)
class Cmd:
    name: str           # without the slash
    desc: str           # short Uzbek description
    group: str
    needs: str | None = None  # "jira" | "channels" | "news" | None


G_LEARN = "📚 O'rganish"
G_DIARY = "📓 Kundalik"
G_PLAN = "📅 Reja"
G_GIT = "📊 GitHub"
G_WORLD = "🌍 Dunyo"
G_OTHER = "⚙️ Boshqa"

COMMANDS: list[Cmd] = [
    Cmd("menu", "Asosiy menyu", G_OTHER),
    Cmd("bugun", "Bugungi umumiy ko'rinish", G_OTHER),
    Cmd("word", "So'z qo'shish", G_LEARN),
    Cmd("words", "So'zlar holati", G_LEARN),
    Cmd("review", "So'z takrorlash", G_LEARN),
    Cmd("quiz", "Imtihon", G_LEARN),
    Cmd("read", "Bugungi maqola", G_LEARN),
    Cmd("summary", "Maqola xulosasi (ingliz tilida)", G_LEARN),
    Cmd("tried", "Hujjat misolini sinadim", G_LEARN),
    Cmd("topic", "Haftalik mavzu", G_LEARN),
    Cmd("readlog", "O'qishlar tarixi", G_LEARN),
    Cmd("drill", "Qo'lda kod mashqi", G_LEARN),
    Cmd("diary", "Bugungi kundalik ro'yxati", G_DIARY),
    Cmd("learned", "Bugun nimani o'rgandim", G_DIARY),
    Cmd("recall", "Yodimdan yozish (output)", G_DIARY),
    Cmd("photo", "Qog'oz kundalik rasmi", G_DIARY),
    Cmd("date", "Keyingi rasm qaysi kun uchun", G_DIARY),
    Cmd("delete_entry", "Qog'oz yozuvni o'chirish", G_DIARY),
    Cmd("stats", "Statistika (kun/hafta/oy/yil)", G_DIARY),
    Cmd("streak", "Ketma-ket kunlar", G_DIARY),
    Cmd("plan", "AI reja tuzish", G_PLAN),
    Cmd("tasks", "Vazifalar ro'yxati", G_PLAN),
    Cmd("done", "Vazifa bajarildi", G_PLAN),
    Cmd("today", "GitHub: bugun", G_GIT),
    Cmd("week", "GitHub: hafta", G_GIT),
    Cmd("month", "GitHub: oy", G_GIT),
    Cmd("github", "GitHub hodisalari", G_GIT),
    Cmd("repos", "Kuzatilayotgan repolar", G_GIT),
    Cmd("news", "Yangiliklar (/news space — kosmos)", G_WORLD, needs="news"),
    Cmd("weather", "Ob-havo va kiyim", G_WORLD),
    Cmd("jira", "Jira: issue'lar, /jira add <nom>, /jira status", G_WORLD, needs="jira"),
    Cmd("channels", "Kuzatilayotgan kanallar", G_WORLD, needs="channels"),
    Cmd("remember", "Bot eslab qolsin (doimiy xotira)", G_OTHER),
    Cmd("memory", "Bot nimalarni eslab qolgan", G_OTHER),
    Cmd("forget", "Eslab qolinganni o'chirish", G_OTHER),
    Cmd("effort", "Claude chuqurligi", G_OTHER),
    Cmd("cancel", "Joriy savolni bekor qilish", G_OTHER),
    Cmd("help", "Yordam", G_OTHER),
]


def is_available(cmd: Cmd) -> bool:
    """False when the command's feature is not configured."""
    if cmd.needs == "jira":
        return bool(settings.jira_base_url and settings.jira_email and settings.jira_api_token)
    if cmd.needs == "channels":
        return bool((settings.watch_channels or "").strip())
    if cmd.needs == "news":
        return bool(settings.news_enabled)
    return True


def visible() -> list[Cmd]:
    return [c for c in COMMANDS if is_available(c)]


def telegram_menu() -> list[dict]:
    """Payload for Telegram's ``setMyCommands`` (only configured features)."""
    return [{"command": c.name, "description": c.desc[:250]} for c in visible()]


def full_list_text() -> str:
    """Every visible command, grouped. Shown under the "Yana" button."""
    groups: dict[str, list[Cmd]] = {}
    for c in visible():
        groups.setdefault(c.group, []).append(c)
    lines = ["📋 Barcha buyruqlar", ""]
    for group in (G_LEARN, G_DIARY, G_PLAN, G_GIT, G_WORLD, G_OTHER):
        if group in groups:
            lines.append(group)
            lines += [f"/{c.name} — {c.desc}" for c in groups[group]]
            lines.append("")
    lines.append("Argumentsiz yuborsangiz, bot o'zi savol beradi. Masalan: /word")
    return "\n".join(lines).rstrip()
