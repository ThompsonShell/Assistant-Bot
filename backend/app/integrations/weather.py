"""Current weather via Open-Meteo (free, no API key) plus a clothing hint.

Open-Meteo needs only latitude/longitude and returns the current temperature,
apparent ("feels-like") temperature, wind speed and a WMO weather code. From
those we build a short, friendly message in Uzbek and a "what to wear" tip so
the owner can glance at the bot and decide before stepping out.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import settings

logger = logging.getLogger("lifeos.weather")

_API = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> (emoji, Uzbek description).
# https://open-meteo.com/en/docs — "Weather variable documentation".
_WMO: dict[int, tuple[str, str]] = {
    0: ("☀️", "ochiq"),
    1: ("🌤", "asosan ochiq"),
    2: ("⛅️", "qisman bulutli"),
    3: ("☁️", "bulutli"),
    45: ("🌫", "tumanli"),
    48: ("🌫", "qirovli tuman"),
    51: ("🌦", "yengil shivalama"),
    53: ("🌦", "shivalama"),
    55: ("🌧", "quyuq shivalama"),
    61: ("🌦", "yengil yomg'ir"),
    63: ("🌧", "yomg'ir"),
    65: ("🌧", "kuchli yomg'ir"),
    66: ("🌧", "muzlagan yomg'ir"),
    67: ("🌧", "kuchli muzlagan yomg'ir"),
    71: ("🌨", "yengil qor"),
    73: ("🌨", "qor"),
    75: ("❄️", "kuchli qor"),
    77: ("🌨", "qor donalari"),
    80: ("🌦", "yengil jala"),
    81: ("🌧", "jala"),
    82: ("⛈", "kuchli jala"),
    85: ("🌨", "yengil qor jalasi"),
    86: ("❄️", "kuchli qor jalasi"),
    95: ("⛈", "momaqaldiroq"),
    96: ("⛈", "do'lli momaqaldiroq"),
    99: ("⛈", "kuchli do'lli momaqaldiroq"),
}

_RAIN_CODES = {51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_SNOW_CODES = {71, 73, 75, 77, 85, 86}


@dataclass
class Weather:
    city: str
    temp: float          # actual air temperature, °C
    feels_like: float    # apparent temperature, °C
    wind: float          # wind speed, km/h
    code: int            # WMO weather code

    @property
    def emoji(self) -> str:
        return _WMO.get(self.code, ("🌡", "noma'lum"))[0]

    @property
    def description(self) -> str:
        return _WMO.get(self.code, ("🌡", "noma'lum"))[1]

    @property
    def is_rain(self) -> bool:
        return self.code in _RAIN_CODES

    @property
    def is_snow(self) -> bool:
        return self.code in _SNOW_CODES


def fetch_weather(http: httpx.Client | None = None) -> Weather:
    """Fetch current weather for the configured location.

    Raises on network/parse errors; callers should catch and show a friendly
    fallback. A client may be passed in (reused by the bot) or one is created.
    """
    params = {
        "latitude": settings.weather_latitude,
        "longitude": settings.weather_longitude,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "wind_speed_unit": "kmh",
        "timezone": settings.display_timezone,
    }
    own = http is None
    client = http or httpx.Client(timeout=15)
    try:
        resp = client.get(_API, params=params)
        resp.raise_for_status()
        cur = (resp.json() or {}).get("current") or {}
    finally:
        if own:
            client.close()
    return Weather(
        city=settings.weather_city,
        temp=float(cur.get("temperature_2m", 0.0)),
        feels_like=float(cur.get("apparent_temperature", cur.get("temperature_2m", 0.0))),
        wind=float(cur.get("wind_speed_10m", 0.0)),
        code=int(cur.get("weather_code", 0)),
    )


def clothing_advice(w: Weather) -> str:
    """Return a short "what to wear" recommendation based on feels-like temp
    and conditions (rain, snow, wind)."""
    t = w.feels_like
    if t >= 30:
        base = "🥵 Juda issiq — yengil kiyim, yoqa ochiq. Suv oling, quyoshdan saqlaning."
    elif t >= 23:
        base = "😎 Iliq — futbolka yoki yengil ko'ylak yetarli."
    elif t >= 16:
        base = "🙂 Salqinroq — yengil kofta yoki uzun yeng oling."
    elif t >= 8:
        base = "🧥 Salqin — kurtka yoki qalin kofta kiying."
    elif t >= 0:
        base = "🧣 Sovuq — issiq kurtka, sharf tavsiya etiladi."
    else:
        base = "🥶 Qattiq sovuq — qalin palto, qo'lqop va shapka kiying."

    extras: list[str] = []
    if w.is_snow:
        extras.append("❄️ Qor bor — suv o'tkazmaydigan oyoq kiyim.")
    elif w.is_rain:
        extras.append("☔️ Yomg'ir bor — soyabon yoki suv o'tkazmas kurtka oling.")
    if w.wind >= 30:
        extras.append("💨 Kuchli shamol — shamoldan himoya qiluvchi kiyim.")

    return base + ("\n" + "\n".join(extras) if extras else "")
