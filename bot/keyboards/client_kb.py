from __future__ import annotations

import datetime as dt
from typing import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Booking, Master
from bot.utils.callbacks import CalCb, CancelOwnBookingCB, ConfirmBookingCB, MasterCB, SlotCB
from bot.utils.time_helpers import format_date_human, format_time

BTN_BOOK = "📅 Записаться"
BTN_MY_BOOKINGS = "🗂 Мои записи"
BTN_INFO = "ℹ️ График / Контакты"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BOOK)],
            [KeyboardButton(text=BTN_MY_BOOKINGS)],
            [KeyboardButton(text=BTN_INFO)],
        ],
        resize_keyboard=True,
    )


def contact_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def masters_kb(masters: Sequence[Master]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for master in masters:
        builder.button(text=f"💈 {master.full_name}", callback_data=MasterCB(master_id=master.id))
    builder.adjust(1)
    return builder.as_markup()


def slots_kb(master_id: int, date: dt.date, slots: Sequence[dt.time]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(
            text=format_time(slot),
            callback_data=SlotCB(master_id=master_id, date=date.isoformat(), time=slot.strftime("%H%M")),
        )
    builder.adjust(3)
    markup = builder.as_markup()
    markup.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к календарю",
                callback_data=CalCb(role="client", action="back", date_str=date.isoformat()).pack(),
            )
        ]
    )
    return markup


def confirm_booking_kb(master_id: int, date: dt.date, time: dt.time) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Подтвердить",
        callback_data=ConfirmBookingCB(
            master_id=master_id, date=date.isoformat(), time=time.strftime("%H%M")
        ),
    )
    builder.button(
        text="❌ Отмена",
        callback_data=CalCb(role="client", action="back", date_str=date.isoformat()),
    )
    builder.adjust(1)
    return builder.as_markup()


def cancel_booking_inline_kb(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить запись", callback_data=CancelOwnBookingCB(booking_id=booking_id))
    return builder.as_markup()


def my_bookings_kb(bookings: Sequence[Booking]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for booking in bookings:
        label = f"❌ {format_date_human(booking.date)} {format_time(booking.start_time)}"
        builder.button(text=label, callback_data=CancelOwnBookingCB(booking_id=booking.id))
    builder.adjust(1)
    return builder.as_markup()
