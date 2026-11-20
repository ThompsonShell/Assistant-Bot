"""Find out why the bot says Jira is not connected, without printing secrets.

Run through ``scripts/check-jira.sh`` (it loads .env exactly like run-local.sh,
then calls this). Two parts:

  1. scan the .env FILE for the usual mistakes: a JIRA_ name that appears twice
     (the last line wins, so a later empty one silently erases the real value),
     spaces around "=", Windows line endings, quotes, an unquoted value with
     spaces
  2. look at what the program actually received, then call Jira once

Secrets are never printed: the token shows only its length and first letters,
the email is masked, the site shows only its host name.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

_ASSIGN = re.compile(r"^(?P<export>export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<pre>\s*)=(?P<post>\s*)(?P<value>.*?)(?P<cr>\r?)$")


@dataclass
class KeyScan:
    lines: list[tuple[int, bool]] = field(default_factory=list)   # (line number, has a value)
    problems: list[str] = field(default_factory=list)


@dataclass
class FileScan:
    keys: dict[str, KeyScan] = field(default_factory=dict)
    file_problems: list[str] = field(default_factory=list)


def scan_env_text(text: str, prefix: str = "JIRA_") -> FileScan:
    """Check .env text for mistakes. Reports names and line numbers only."""
    out = FileScan()
    for number, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _ASSIGN.match(line.lstrip())
        if not m:
            out.file_problems.append(f"{number}-qator '=' li yozuvga o'xshamaydi (bash uni buyruq deb o'qiydi)")
            continue
        key, value = m["key"], m["value"]
        quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "'\""
        if not key.startswith(prefix):
            if value and not quoted and re.search(r"\s", value) and not value.startswith("#"):
                out.file_problems.append(
                    f"{number}-qator ({key}): qiymatda bo'sh joy bor, qo'shtirnoqsiz. "
                    "Bash qolgan qismini buyruq deb ishga tushirishga urinadi, skript to'xtashi mumkin"
                )
            continue
        info = out.keys.setdefault(key, KeyScan())
        info.lines.append((number, bool(value.strip("'\"").strip())))
        if m["pre"]:
            info.problems.append(f"{number}-qator: '=' dan oldin bo'sh joy bor (to'g'risi {key}=qiymat)")
        if m["post"]:
            info.problems.append(f"{number}-qator: '=' dan keyin bo'sh joy bor")
        if m["cr"]:
            info.problems.append(f"{number}-qator: Windows qator oxiri (CRLF)")
        if value and (value[0] in "'\"") != (value[-1] in "'\""):
            info.problems.append(f"{number}-qator: bitta qo'shtirnoq, ikkinchisi yo'q")
        if " #" in value and not quoted:
            info.problems.append(f"{number}-qator: qiymat ichida ' #' izoh bor")
    for key, info in out.keys.items():
        if len(info.lines) > 1:
            last_number, last_has_value = info.lines[-1]
            where = ", ".join(str(n) for n, _ in info.lines)
            if not last_has_value and any(has for _, has in info.lines[:-1]):
                info.problems.append(
                    f"{key} {where}-qatorlarda takrorlangan va OXIRGISI ({last_number}) bo'sh: "
                    "u oldingi to'g'ri qiymatni o'chirib yubormoqda"
                )
            else:
                info.problems.append(f"{key} {where}-qatorlarda takrorlangan (oxirgisi ishlaydi)")
    return out


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "?"


def main(env_path: str | None = None) -> int:
    from . import jira
    from ..config import settings

    ok = True
    print("=== 1. .env fayli ===")
    if env_path and Path(env_path).is_file():
        print(f"Fayl: {env_path}")
        scan = scan_env_text(Path(env_path).read_text(encoding="utf-8", errors="replace"))
        for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
            info = scan.keys.get(name)
            if info is None:
                print(f"❌ {name}: bu faylda umuman yo'q")
                ok = False
                continue
            print(f"{'✅' if info.lines[-1][1] else '❌'} {name}: {len(info.lines)} marta yozilgan, "
                  f"oxirgi qiymat {'bor' if info.lines[-1][1] else 'BO‘SH'}")
            for p in info.problems:
                print(f"   ⚠️ {p}")
                ok = False
        for p in scan.file_problems:
            print(f"⚠️ {p}")
            ok = False
    else:
        print("Fayl topilmadi (skript orqali ishga tushiring: ./scripts/check-jira.sh)")

    print("\n=== 2. Bot nimani ko'radi ===")
    missing = jira.missing_settings()
    if missing:
        print("❌ Yetishmayotgan: " + ", ".join(missing))
        print("   Demak bot .env dagi qiymatni olmayapti. Sabab: boshqa .env fayl, "
              "takrorlangan bo'sh qator yoki skript orqali ishga tushirilmagan.")
        return 1
    try:
        host = urlparse(jira.base_url()).netloc
    except jira.JiraError as exc:
        print("❌", exc.user_message)
        return 1
    token = (settings.jira_api_token or "").strip().strip("'\"")
    print(f"✅ JIRA_BASE_URL  : {host}" + ("" if host.endswith("atlassian.net") else "  ⚠️ atlassian.net emas"))
    print(f"✅ JIRA_EMAIL     : {_mask_email((settings.jira_email or '').strip())}")
    print(f"✅ JIRA_API_TOKEN : uzunligi {len(token)}, boshi {token[:5]}…"
          + ("" if token.startswith("ATATT") else "  ⚠️ odatda ATATT bilan boshlanadi"))
    project = jira.project_key_from_env()
    print(f"ℹ️ JIRA_PROJECT_KEY: {project or 'bo‘sh (botda tanlanadi)'}")

    print("\n=== 3. Jira'ga so'rov ===")
    try:
        me = jira.whoami()
        print(f"✅ Ulandi: {me.get('displayName', '?')}")
        projects = jira.list_projects()
        print(f"✅ Ko'rinadigan loyihalar: {', '.join(p['key'] for p in projects) or 'yo‘q'}")
    except jira.JiraError as exc:
        print("❌", exc.user_message)
        return 1
    print("\nHammasi joyida. Bot hamon 'ulanmagan' desa, u ESKI nusxa: ./scripts/check-jira.sh jarayonlarni ko'rsatadi.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
