from __future__ import annotations

import datetime as dt
import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.admin.states import AdminScheduleStates
from bot.keyboards.admin_kb import BTN_BOOKINGS, BTN_DAYS_OFF, admin_main_menu_kb, day_card_kb
from bot.keyboards.calendar_kb import build_month_calendar
from bot.services.booking_service import (
    cancel_booking,
    get_booking,
    get_bookings_for_master_on_date,
    get_client_by_id,
)
from bot.services.schedule_service import (
    add_day_off,
    get_admin_month_overview,
    get_date_override,
    get_master_by_telegram_id,
    get_working_hours_for_date,
    is_day_off,
    remove_date_override,
    remove_day_off,
    remove_working_day,
    set_date_override,
    week_parity_for_date,
)
from bot.utils.callbacks import (
    AdminCancelBookingCB,
    AdminDayHoursCB,
    AdminDayToggleCB,
    AdminResetOverrideCB,
    CalCb,
)
from bot.utils.logger import get_logger
from bot.utils.time_helpers import WEEKDAY_NAMES_RU, format_date_human, format_time, today

router = Router(name="admin_bookings")
logger = get_logger(__name__)


async def _show_admin_calendar(
    target_message: Message, session: AsyncSession, master_id: int, year: int, month: int, edit: bool
) -> None:
    overview = await get_admin_month_overview(session, master_id, year, month)

    def decorate(date: dt.date) -> tuple[str, bool]:
        info = overview.get(date.day)
        if info is None:
            return str(date.day), True
        if info["is_day_off"]:
            return f"{date.day}🚫", True
        if info["bookings_count"] > 0:
            return f"{date.day}({info['bookings_count']})", True
        return str(date.day), True

    markup = build_month_calendar("admin", year, month, decorate)
    text = "Календарь. 🚫 — выходной, (N) — число активных записей.\nВыберите число:"
    if edit:
        await target_message.edit_text(text, reply_markup=markup)
    else:
        await target_message.answer(text, reply_markup=markup)


async def _show_day_card(
    target_message: Message, session: AsyncSession, master_id: int, date: dt.date, edit: bool
) -> None:
    bookings = await get_bookings_for_master_on_date(session, master_id, date)
    day_off_flag = await is_day_off(session, master_id, date)
    override = await get_date_override(session, master_id, date)
    wh = await get_working_hours_for_date(session, master_id, date)
    is_working_weekday = wh is not None and wh.is_working_day

    lines = [f"<b>{format_date_human(date)}</b>"]
    if day_off_flag:
        lines.append("🚫 Выходной день")
    elif override is not None:
        lines.append(
            f"⏱ Индивидуальные часы: {format_time(override.start_time)}–{format_time(override.end_time)}"
        )
    elif is_working_weekday:
        parity_note = f" (неделя {wh.week_parity + 1})" if wh.week_parity is not None else ""
        lines.append(
            f"🕒 Рабочие часы (шаблон недели){parity_note}: "
            f"{format_time(wh.start_time)}–{format_time(wh.end_time)}"
        )
    else:
        lines.append("🚫 Нерабочий день (по шаблону недели)")

    if bookings:
        lines.append(f"\n<b>Записи ({len(bookings)}):</b>")
        for booking in bookings:
            client = await get_client_by_id(session, booking.client_id)
            # Client-controlled (Telegram display name / phone) — must be
            # HTML-escaped before going into a parse_mode="HTML" message,
            # otherwise a crafted name (e.g. a stray "<" or "&") breaks
            # Telegram's entity parser and the whole day card fails to
            # render for the admin.
            name = html.escape(client.full_name) if client else "—"
            phone = html.escape(client.phone) if client and client.phone else "—"
            lines.append(f"🕒 {format_time(booking.start_time)} — {name} ({phone})")
    else:
        lines.append("\nЗаписей нет.")

    markup = day_card_kb(date, bookings, day_off_flag, is_working_weekday, override is not None)
    text = "\n".join(lines)
    if edit:
        await target_message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target_message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(F.text.in_({BTN_BOOKINGS, BTN_DAYS_OFF}))
async def open_admin_calendar(message: Message, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, message.from_user.id)
    if master is None:
        return
    now_date = today()
    await _show_admin_calendar(message, session, master.id, now_date.year, now_date.month, edit=False)


@router.callback_query(CalCb.filter(F.role == "admin"))
async def admin_calendar_click(call: CallbackQuery, callback_data: CalCb, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return

    if callback_data.action == "ignore":
        await call.answer()
        return

    if callback_data.action in ("prev", "next", "back"):
        anchor = dt.date.fromisoformat(callback_data.date_str)
        await _show_admin_calendar(call.message, session, master.id, anchor.year, anchor.month, edit=True)
        await call.answer()
        return

    if callback_data.action == "day":
        date = dt.date.fromisoformat(callback_data.date_str)
        await _show_day_card(call.message, session, master.id, date, edit=True)
        await call.answer()
        return

    await call.answer()


@router.callback_query(AdminCancelBookingCB.filter())
async def admin_cancel_booking(
    call: CallbackQuery, callback_data: AdminCancelBookingCB, session: AsyncSession, bot: Bot
) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return

    # Callback data only ever carries booking IDs this admin's own day card
    # displayed, but Telegram clients can submit arbitrary callback_data
    # for any button a bot has sent them — so ownership must be checked
    # server-side, not assumed from "we only showed them their own IDs".
    existing = await get_booking(session, callback_data.booking_id)
    if existing is None or existing.master_id != master.id:
        await call.answer("Запись не найдена", show_alert=True)
        return

    booking = await cancel_booking(session, callback_data.booking_id, by="master")
    if booking is None:
        await call.answer("Запись уже отменена или не найдена", show_alert=True)
        return

    client = await get_client_by_id(session, booking.client_id)
    await _show_day_card(call.message, session, master.id, booking.date, edit=True)
    await call.answer("Отменено")

    if client is not None:
        try:
            await bot.send_message(
                client.telegram_id,
                "⚠️ Мастер отменил вашу запись:\n"
                f"📅 {format_date_human(booking.date)}\n"
                f"🕒 {format_time(booking.start_time)}\n\n"
                "Пожалуйста, выберите другое время в разделе «Записаться».",
            )
        except Exception:
            logger.warning("Failed to notify client_id=%s about master cancellation", client.id)


@router.callback_query(AdminDayToggleCB.filter())
async def day_toggle(
    call: CallbackQuery, callback_data: AdminDayToggleCB, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return

    date = dt.date.fromisoformat(callback_data.date_str)

    if callback_data.scope == "date":
        if await is_day_off(session, master.id, date):
            await remove_day_off(session, master.id, date)
            toast = "Теперь рабочий день"
        else:
            affected_bookings = await add_day_off(session, master.id, date)
            toast = "Теперь выходной"
            for booking in affected_bookings:
                cancelled = await cancel_booking(session, booking.id, by="master")
                if cancelled is None:
                    continue
                client = await get_client_by_id(session, booking.client_id)
                if client is None:
                    continue
                try:
                    await bot.send_message(
                        client.telegram_id,
                        "⚠️ Ваша запись отменена мастером (выходной день):\n"
                        f"📅 {format_date_human(date)}\n"
                        f"🕒 {format_time(booking.start_time)}\n\n"
                        "Пожалуйста, выберите другое время в разделе «Записаться».",
                    )
                except Exception:
                    logger.warning(
                        "Failed to notify client_id=%s about day-off cancellation", client.id
                    )
        await _show_day_card(call.message, session, master.id, date, edit=True)
        await call.answer(toast)
        return

    # scope == "weekday": toggles the weekly-template row that actually
    # applies to THIS date (respecting alternating-week parity if the
    # master uses it), not necessarily every week with that weekday name.
    parity = week_parity_for_date(master, date)
    wh = await get_working_hours_for_date(session, master.id, date)
    is_working_weekday = wh is not None and wh.is_working_day

    if is_working_weekday:
        await remove_working_day(session, master.id, date.weekday(), wh.week_parity)
        await _show_day_card(call.message, session, master.id, date, edit=True)
        await call.answer(f"{WEEKDAY_NAMES_RU[date.weekday()]} теперь нерабочий день недели")
    else:
        await state.set_state(AdminScheduleStates.entering_hours)
        await state.update_data(weekday=date.weekday(), week_parity=parity)
        parity_note = f" (неделя {parity + 1})" if parity is not None else ""
        await call.message.edit_text(
            f"Укажите время работы для <b>{WEEKDAY_NAMES_RU[date.weekday()]}</b>{parity_note} "
            "в формате <b>10:00-20:00</b>.",
            parse_mode="HTML",
        )
        await call.answer()


@router.callback_query(AdminDayHoursCB.filter())
async def day_hours_requested(call: CallbackQuery, callback_data: AdminDayHoursCB, state: FSMContext) -> None:
    await state.set_state(AdminScheduleStates.entering_date_hours)
    await state.update_data(date_str=callback_data.date_str)
    date = dt.date.fromisoformat(callback_data.date_str)
    await call.message.edit_text(
        f"Укажите часы работы на <b>{format_date_human(date)}</b> в формате <b>12:00-15:00</b>.",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AdminScheduleStates.entering_date_hours)
async def date_hours_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    date_str = data.get("date_str")
    master = await get_master_by_telegram_id(session, message.from_user.id)
    if master is None or date_str is None:
        await state.clear()
        return
    date = dt.date.fromisoformat(date_str)

    text = (message.text or "").strip()
    try:
        start_str, end_str = text.split("-")
        start_time = dt.datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = dt.datetime.strptime(end_str.strip(), "%H:%M").time()
        if start_time >= end_time:
            raise ValueError("start must be before end")
    except ValueError:
        await message.answer(
            "Неверный формат. Пример: <b>12:00-15:00</b>. Попробуйте снова.", parse_mode="HTML"
        )
        return

    await set_date_override(session, master.id, date, start_time, end_time)
    await state.clear()
    await message.answer(
        f"✅ На {format_date_human(date)} установлены часы {start_str.strip()}–{end_str.strip()}.",
        reply_markup=admin_main_menu_kb(),
    )
    await _show_day_card(message, session, master.id, date, edit=False)


@router.callback_query(AdminResetOverrideCB.filter())
async def reset_override(call: CallbackQuery, callback_data: AdminResetOverrideCB, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return
    date = dt.date.fromisoformat(callback_data.date_str)
    await remove_date_override(session, master.id, date)
    await _show_day_card(call.message, session, master.id, date, edit=True)
    await call.answer("Сброшено на стандартный график")
