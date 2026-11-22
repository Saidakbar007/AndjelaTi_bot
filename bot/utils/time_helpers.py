from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from bot.config import settings

TZ = ZoneInfo(settings.TIMEZONE)

WEEKDAY_NAMES_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTH_NAMES_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def now() -> dt.datetime:
    """Current aware datetime in the configured timezone."""
    return dt.datetime.now(TZ)


def today() -> dt.date:
    return now().date()


def combine_local(date: dt.date, time: dt.time) -> dt.datetime:
    """Combine a date+time into an aware datetime in the configured timezone."""
    return dt.datetime.combine(date, time, tzinfo=TZ)


def format_date_human(date: dt.date) -> str:
    weekday = WEEKDAY_NAMES_RU[date.weekday()]
    return f"{date.day} {MONTH_NAMES_RU[date.month - 1]} ({weekday})"


def format_time(time: dt.time) -> str:
    return time.strftime("%H:%M")
