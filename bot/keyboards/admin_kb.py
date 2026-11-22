from __future__ import annotations

import datetime as dt
from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Booking
from bot.utils.callbacks import (
    AdminCancelBookingCB,
    AdminDayHoursCB,
    AdminDayToggleCB,
    AdminResetOverrideCB,
    AdminSlotDurationCB,
    AdminTemplateHoursCB,
    AdminTemplateOffCB,
    CalCb,
)
from bot.utils.time_helpers import WEEKDAY_NAMES_RU, format_time

BTN_SCHEDULE = "🗓 График работы"
BTN_BOOKINGS = "📋 Записи"
BTN_DURATION = "⏱ Длительность услуги"
BTN_DAYS_OFF = "🚫 Выходные"

SLOT_DURATION_OPTIONS = [30, 45, 60, 90]


def admin_main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SCHEDULE), KeyboardButton(text=BTN_BOOKINGS)],
            [KeyboardButton(text=BTN_DURATION), KeyboardButton(text=BTN_DAYS_OFF)],
        ],
        resize_keyboard=True,
    )


def template_day_detail_kb(date: dt.date, is_working: bool) -> InlineKeyboardMarkup:
    """Keyboard for the small detail prompt shown after tapping a date in
    the "🗓 График работы" week-calendar: edit/set hours for that weekday
    (at the week-parity implied by the date), toggle it off if currently
    working, and a way back to the week view.
    """
    date_str = date.isoformat()
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Изменить часы" if is_working else "✅ Сделать рабочим",
        callback_data=AdminTemplateHoursCB(date_str=date_str),
    )
    if is_working:
        builder.button(
            text="🚫 Сделать выходным", callback_data=AdminTemplateOffCB(date_str=date_str)
        )
    builder.adjust(1)
    markup = builder.as_markup()
    markup.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к неделе",
                callback_data=CalCb(role="sched", action="back", date_str=date_str).pack(),
            )
        ]
    )
    return markup


def slot_duration_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes in SLOT_DURATION_OPTIONS:
        builder.button(text=f"{minutes} мин", callback_data=AdminSlotDurationCB(minutes=minutes))
    builder.adjust(2)
    return builder.as_markup()


def day_card_kb(
    date: dt.date,
    bookings: Sequence[Booking],
    is_day_off: bool,
    is_working_weekday: bool,
    has_override: bool,
) -> InlineKeyboardMarkup:
    """Keyboard for the admin's per-day card opened from the calendar:
    cancel buttons for that day's bookings, day-off / weekday toggles, a
    custom-hours action, and (if a custom-hours override is active) a way
    to reset it back to the weekly template.
    """
    builder = InlineKeyboardBuilder()
    for booking in bookings:
        builder.button(
            text=f"❌ Отменить {format_time(booking.start_time)}",
            callback_data=AdminCancelBookingCB(booking_id=booking.id),
        )
    builder.adjust(1)
    markup = builder.as_markup()

    date_str = date.isoformat()
    weekday_name = WEEKDAY_NAMES_RU[date.weekday()]

    extra_rows: list[list[InlineKeyboardButton]] = []

    if is_day_off:
        date_toggle_text = "✅ Сделать рабочим (эта дата)"
    else:
        date_toggle_text = "🚫 Сделать выходным (эта дата)"
    extra_rows.append(
        [
            InlineKeyboardButton(
                text=date_toggle_text,
                callback_data=AdminDayToggleCB(scope="date", date_str=date_str).pack(),
            )
        ]
    )

    if is_working_weekday:
        weekday_toggle_text = f"🚫 Выходной каждый {weekday_name}"
    else:
        weekday_toggle_text = f"✅ Сделать рабочим каждый {weekday_name}"
    extra_rows.append(
        [
            InlineKeyboardButton(
                text=weekday_toggle_text,
                callback_data=AdminDayToggleCB(scope="weekday", date_str=date_str).pack(),
            )
        ]
    )

    extra_rows.append(
        [
            InlineKeyboardButton(
                text="⏱ Изменить часы на эту дату",
                callback_data=AdminDayHoursCB(date_str=date_str).pack(),
            )
        ]
    )

    if has_override:
        extra_rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить на стандартный график",
                    callback_data=AdminResetOverrideCB(date_str=date_str).pack(),
                )
            ]
        )

    extra_rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к календарю",
                callback_data=CalCb(role="admin", action="back", date_str=date_str).pack(),
            )
        ]
    )

    markup.inline_keyboard.extend(extra_rows)
    return markup
