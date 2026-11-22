from __future__ import annotations

import datetime as dt

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.client.states import BookingStates
from bot.keyboards.calendar_kb import build_month_calendar
from bot.keyboards.client_kb import (
    BTN_BOOK,
    confirm_booking_kb,
    contact_request_kb,
    main_menu_kb,
    masters_kb,
    slots_kb,
)
from bot.services.booking_service import (
    SlotAlreadyTakenError,
    create_booking,
    get_or_create_client,
    update_client_phone,
)
from bot.services.schedule_service import (
    get_active_masters,
    get_client_month_availability,
    get_free_slots,
    get_master,
)
from bot.utils.callbacks import CalCb, ConfirmBookingCB, MasterCB, SlotCB
from bot.utils.logger import get_logger
from bot.utils.time_helpers import format_date_human, format_time, today

router = Router(name="client_booking")
logger = get_logger(__name__)


def _add_minutes(time_value: dt.time, minutes: int) -> dt.time:
    base = dt.datetime.combine(dt.date.today(), time_value)
    return (base + dt.timedelta(minutes=minutes)).time()


def _parse_time(value: str) -> dt.time:
    return dt.datetime.strptime(value, "%H%M").time()


async def _show_calendar(
    target_message: Message,
    state: FSMContext,
    session: AsyncSession,
    master_id: int,
    year: int,
    month: int,
    edit: bool,
) -> None:
    availability = await get_client_month_availability(session, master_id, year, month)

    def decorate(date: dt.date) -> tuple[str, bool]:
        if date < today():
            return "·", False
        status = availability.get(date.day, "unavailable")
        if status == "available":
            return str(date.day), True
        if status == "day_off":
            return "❌", False
        return "·", False

    markup = build_month_calendar("client", year, month, decorate)

    await state.update_data(master_id=master_id)
    await state.set_state(BookingStates.choosing_date)

    text = "Выберите дату для записи (· — нет мест, ❌ — выходной):"
    if edit:
        await target_message.edit_text(text, reply_markup=markup)
    else:
        await target_message.answer(text, reply_markup=markup)


@router.message(F.text == BTN_BOOK)
async def start_booking(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    masters = await get_active_masters(session)
    if not masters:
        await message.answer("Мастера пока не настроены. Загляните позже.")
        return

    now_date = today()
    if len(masters) == 1:
        await _show_calendar(message, state, session, masters[0].id, now_date.year, now_date.month, edit=False)
    else:
        await state.set_state(BookingStates.choosing_master)
        await message.answer("Выберите мастера:", reply_markup=masters_kb(masters))


@router.callback_query(BookingStates.choosing_master, MasterCB.filter())
async def master_chosen(call: CallbackQuery, callback_data: MasterCB, state: FSMContext, session: AsyncSession) -> None:
    now_date = today()
    await _show_calendar(
        call.message, state, session, callback_data.master_id, now_date.year, now_date.month, edit=True
    )
    await call.answer()


@router.callback_query(CalCb.filter(F.role == "client"))
async def client_calendar_click(call: CallbackQuery, callback_data: CalCb, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    master_id = data.get("master_id")

    if callback_data.action == "ignore":
        if callback_data.date_str != "-":
            await call.answer("На эту дату нет свободных мест")
        else:
            await call.answer()
        return

    if master_id is None:
        await call.answer("Сессия устарела, начните заново: «Записаться»", show_alert=True)
        return

    if callback_data.action in ("prev", "next"):
        anchor = dt.date.fromisoformat(callback_data.date_str)
        await _show_calendar(call.message, state, session, master_id, anchor.year, anchor.month, edit=True)
        await call.answer()
        return

    if callback_data.action == "back":
        anchor = dt.date.fromisoformat(callback_data.date_str)
        await _show_calendar(call.message, state, session, master_id, anchor.year, anchor.month, edit=True)
        await call.answer()
        return

    if callback_data.action == "day":
        date = dt.date.fromisoformat(callback_data.date_str)
        slots = await get_free_slots(session, master_id, date)
        if not slots:
            await call.answer("На эту дату уже нет свободных слотов", show_alert=True)
            await _show_calendar(call.message, state, session, master_id, date.year, date.month, edit=True)
            return

        await state.update_data(master_id=master_id, date=callback_data.date_str)
        await state.set_state(BookingStates.choosing_slot)
        await call.message.edit_text(
            f"Доступное время на {format_date_human(date)}:",
            reply_markup=slots_kb(master_id, date, slots),
        )
        await call.answer()
        return

    await call.answer()


@router.callback_query(BookingStates.choosing_slot, SlotCB.filter())
async def slot_chosen(call: CallbackQuery, callback_data: SlotCB, state: FSMContext, session: AsyncSession) -> None:
    master_id = callback_data.master_id
    date = dt.date.fromisoformat(callback_data.date)
    time_value = _parse_time(callback_data.time)

    current_slots = await get_free_slots(session, master_id, date)
    if time_value not in current_slots:
        if current_slots:
            await call.message.edit_text(
                "Это время уже заняли. Доступное время:",
                reply_markup=slots_kb(master_id, date, current_slots),
            )
        else:
            await _show_calendar(call.message, state, session, master_id, date.year, date.month, edit=True)
        await call.answer("Этот слот уже занят, выберите другой", show_alert=True)
        return

    await state.update_data(time=callback_data.time)

    client = await get_or_create_client(
        session, call.from_user.id, call.from_user.full_name, call.from_user.username
    )

    if not client.phone:
        await state.set_state(BookingStates.entering_phone)
        await call.message.edit_text(
            f"📅 {format_date_human(date)} 🕒 {format_time(time_value)}\n\n"
            "Для подтверждения записи отправьте номер телефона."
        )
        await call.message.answer(
            "Нажмите кнопку ниже, чтобы отправить номер:",
            reply_markup=contact_request_kb(),
        )
        await call.answer()
        return

    await state.set_state(BookingStates.confirming)
    await call.message.edit_text(
        f"Подтвердите запись:\n📅 {format_date_human(date)}\n🕒 {format_time(time_value)}",
        reply_markup=confirm_booking_kb(master_id, date, time_value),
    )
    await call.answer()


@router.message(BookingStates.entering_phone, F.contact)
async def phone_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
    phone = message.contact.phone_number
    client = await get_or_create_client(
        session, message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    await update_client_phone(session, client.id, phone)

    data = await state.get_data()
    master_id = data.get("master_id")
    date_str = data.get("date")
    time_str = data.get("time")
    if not all([master_id, date_str, time_str]):
        await state.clear()
        await message.answer("Сессия записи истекла, начните заново.", reply_markup=main_menu_kb())
        return

    date = dt.date.fromisoformat(date_str)
    time_value = _parse_time(time_str)

    await state.set_state(BookingStates.confirming)
    await message.answer("Спасибо! Номер сохранён ✅", reply_markup=main_menu_kb())
    await message.answer(
        f"Подтвердите запись:\n📅 {format_date_human(date)}\n🕒 {format_time(time_value)}",
        reply_markup=confirm_booking_kb(master_id, date, time_value),
    )


@router.message(BookingStates.entering_phone)
async def phone_not_received(message: Message) -> None:
    await message.answer(
        "Пожалуйста, отправьте номер телефона кнопкой ниже 👇",
        reply_markup=contact_request_kb(),
    )


@router.callback_query(BookingStates.confirming, ConfirmBookingCB.filter())
async def confirm_booking(
    call: CallbackQuery, callback_data: ConfirmBookingCB, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    master_id = callback_data.master_id
    date = dt.date.fromisoformat(callback_data.date)
    time_value = _parse_time(callback_data.time)

    master = await get_master(session, master_id)
    if master is None:
        await call.answer("Мастер не найден", show_alert=True)
        await state.clear()
        return

    client = await get_or_create_client(
        session, call.from_user.id, call.from_user.full_name, call.from_user.username
    )
    end_time = _add_minutes(time_value, master.slot_duration_minutes)

    try:
        await create_booking(session, master_id, client.id, date, time_value, end_time)
    except SlotAlreadyTakenError:
        slots = await get_free_slots(session, master_id, date)
        if slots:
            await state.set_state(BookingStates.choosing_slot)
            await call.message.edit_text(
                "Выберите другое время:", reply_markup=slots_kb(master_id, date, slots)
            )
        else:
            await _show_calendar(call.message, state, session, master_id, date.year, date.month, edit=True)
        await call.answer("Это время только что заняли 😔 Выберите другое.", show_alert=True)
        return

    await state.clear()
    await call.message.edit_text(
        f"✅ Вы записаны!\n📅 {format_date_human(date)}\n🕒 {format_time(time_value)}\n\n"
        "Отменить запись можно в разделе «Мои записи»."
    )
    await call.answer("Запись подтверждена!")

    try:
        await bot.send_message(
            master.telegram_id,
            "🆕 Новая запись!\n"
            f"📅 {format_date_human(date)}\n"
            f"🕒 {format_time(time_value)}\n"
            f"👤 {client.full_name}\n"
            f"📞 {client.phone or '—'}",
        )
    except Exception:
        logger.warning("Failed to notify master_id=%s about a new booking", master.id)
