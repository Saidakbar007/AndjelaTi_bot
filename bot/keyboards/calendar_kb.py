from __future__ import annotations

import calendar
import datetime as dt
from typing import Callable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.callbacks import CalCb
from bot.utils.time_helpers import MONTH_NAMES_RU, WEEKDAY_NAMES_RU, today

_IGNORE = "ignore"


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """(first day, last day) of the given month."""
    first = dt.date(year, month, 1)
    last = dt.date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def _blank_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=" ", callback_data=CalCb(role="x", action=_IGNORE, date_str="-").pack()
    )


def build_month_calendar(
    role: str,
    year: int,
    month: int,
    decorate: Callable[[dt.date], tuple[str, bool]],
) -> InlineKeyboardMarkup:
    """Generic 7-column month calendar used by both the client and the
    admin panel.

    `decorate(date)` is called once per real day of the month and must
    return (label, clickable). Padding cells (before day 1 / after the
    last day) and header cells are always non-interactive ("ignore").
    Navigating to months before the current one is disabled (the "◀"
    button is simply omitted on the current month).
    """
    first_day, last_day = month_bounds(year, month)
    days_in_month = last_day.day
    current_year, current_month = today().year, today().month

    rows: list[list[InlineKeyboardButton]] = []

    nav_row: list[InlineKeyboardButton] = []
    if (year, month) > (current_year, current_month):
        prev_anchor = (first_day - dt.timedelta(days=1)).replace(day=1)
        nav_row.append(
            InlineKeyboardButton(
                text="◀",
                callback_data=CalCb(role=role, action="prev", date_str=prev_anchor.isoformat()).pack(),
            )
        )
    else:
        nav_row.append(_blank_button())

    nav_row.append(
        InlineKeyboardButton(
            text=f"{MONTH_NAMES_RU[month - 1].capitalize()} {year}",
            callback_data=CalCb(role=role, action=_IGNORE, date_str="-").pack(),
        )
    )

    next_anchor = (last_day + dt.timedelta(days=1)).replace(day=1)
    nav_row.append(
        InlineKeyboardButton(
            text="▶",
            callback_data=CalCb(role=role, action="next", date_str=next_anchor.isoformat()).pack(),
        )
    )
    rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=name, callback_data=CalCb(role=role, action=_IGNORE, date_str="-").pack()
            )
            for name in WEEKDAY_NAMES_RU
        ]
    )

    week: list[InlineKeyboardButton] = []
    leading_blanks = first_day.weekday()  # Mon=0 .. Sun=6
    for _ in range(leading_blanks):
        week.append(_blank_button())

    for day_num in range(1, days_in_month + 1):
        date = dt.date(year, month, day_num)
        label, clickable = decorate(date)
        action = "day" if clickable else _IGNORE
        week.append(
            InlineKeyboardButton(
                text=label,
                callback_data=CalCb(role=role, action=action, date_str=date.isoformat()).pack(),
            )
        )
        if len(week) == 7:
            rows.append(week)
            week = []

    if week:
        while len(week) < 7:
            week.append(_blank_button())
        rows.append(week)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_week_calendar(
    role: str,
    monday_date: dt.date,
    decorate: Callable[[dt.date], str],
) -> InlineKeyboardMarkup:
    """A single Mon-Sun week as a compact calendar strip (nav row, weekday
    header, one row of 7 dates). Every real date is clickable; `decorate`
    only supplies its label (e.g. the day number, optionally with a
    rest-day marker). Navigating to a week before the current one is
    disabled (the "◀" button is simply omitted).
    """
    current_monday = today() - dt.timedelta(days=today().weekday())

    rows: list[list[InlineKeyboardButton]] = []

    nav_row: list[InlineKeyboardButton] = []
    if monday_date > current_monday:
        prev_monday = monday_date - dt.timedelta(days=7)
        nav_row.append(
            InlineKeyboardButton(
                text="◀",
                callback_data=CalCb(role=role, action="week_prev", date_str=prev_monday.isoformat()).pack(),
            )
        )
    else:
        nav_row.append(_blank_button())

    week_end = monday_date + dt.timedelta(days=6)
    label = f"{monday_date.day:02d}.{monday_date.month:02d}–{week_end.day:02d}.{week_end.month:02d}"
    nav_row.append(
        InlineKeyboardButton(
            text=label, callback_data=CalCb(role=role, action=_IGNORE, date_str="-").pack()
        )
    )

    next_monday = monday_date + dt.timedelta(days=7)
    nav_row.append(
        InlineKeyboardButton(
            text="▶",
            callback_data=CalCb(role=role, action="week_next", date_str=next_monday.isoformat()).pack(),
        )
    )
    rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text=name, callback_data=CalCb(role=role, action=_IGNORE, date_str="-").pack()
            )
            for name in WEEKDAY_NAMES_RU
        ]
    )

    day_row: list[InlineKeyboardButton] = []
    for i in range(7):
        date = monday_date + dt.timedelta(days=i)
        day_row.append(
            InlineKeyboardButton(
                text=decorate(date),
                callback_data=CalCb(role=role, action="day", date_str=date.isoformat()).pack(),
            )
        )
    rows.append(day_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)
