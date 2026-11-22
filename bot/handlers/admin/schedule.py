from __future__ import annotations

import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.admin.states import AdminScheduleStates
from bot.keyboards.admin_kb import (
    BTN_DURATION,
    BTN_SCHEDULE,
    admin_main_menu_kb,
    slot_duration_kb,
    template_day_detail_kb,
)
from bot.keyboards.calendar_kb import build_week_calendar
from bot.services.schedule_service import (
    get_master_by_telegram_id,
    get_week_schedule_overview,
    get_working_hours_for_date,
    remove_working_day,
    set_slot_duration,
    set_working_hours,
    week_parity_for_date,
)
from bot.utils.callbacks import (
    AdminSlotDurationCB,
    AdminTemplateHoursCB,
    AdminTemplateOffCB,
    CalCb,
)
from bot.utils.time_helpers import WEEKDAY_NAMES_RU, format_date_human, format_time, today

router = Router(name="admin_schedule")


def _parity_label(week_parity: int | None) -> str:
    if week_parity is None:
        return ""
    return f" (неделя {week_parity + 1})"


def _monday_of(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


async def _show_week_schedule(
    target_message: Message, session: AsyncSession, master_id: int, monday_date: dt.date, edit: bool
) -> None:
    overview = await get_week_schedule_overview(session, master_id, monday_date)

    def decorate(date: dt.date) -> str:
        info = overview.get(date)
        if info is None or not info["is_working"]:
            return f"{date.day}🚫"
        return str(date.day)

    markup = build_week_calendar("sched", monday_date, decorate)
    text = (
        "<b>График работы</b> — ближайшая неделя.\n"
        "🚫 — выходной день.\n"
        "Нажмите на число, чтобы посмотреть или изменить часы работы на этот день недели:"
    )
    if edit:
        await target_message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target_message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(F.text == BTN_SCHEDULE)
async def schedule_menu(message: Message, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, message.from_user.id)
    if master is None:
        return
    await _show_week_schedule(message, session, master.id, _monday_of(today()), edit=False)


@router.callback_query(CalCb.filter(F.role == "sched"))
async def sched_calendar_click(call: CallbackQuery, callback_data: CalCb, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return

    if callback_data.action == "ignore":
        await call.answer()
        return

    if callback_data.action in ("week_prev", "week_next", "back"):
        date = dt.date.fromisoformat(callback_data.date_str)
        monday = date if callback_data.action != "back" else _monday_of(date)
        await _show_week_schedule(call.message, session, master.id, monday, edit=True)
        await call.answer()
        return

    if callback_data.action == "day":
        date = dt.date.fromisoformat(callback_data.date_str)
        overview = await get_week_schedule_overview(session, master.id, _monday_of(date))
        info = overview.get(date, {})

        wh = await get_working_hours_for_date(session, master.id, date)
        template_is_working = wh is not None and wh.is_working_day

        lines = [f"<b>{WEEKDAY_NAMES_RU[date.weekday()]}, {format_date_human(date)}</b>"]
        if info.get("is_day_off"):
            lines.append("🚫 Выходной (отдельная дата, поверх шаблона)")
        elif info.get("is_override"):
            lines.append(
                f"⏱ Индивидуальные часы на эту дату: "
                f"{format_time(info['start_time'])}–{format_time(info['end_time'])}"
            )
        elif template_is_working:
            lines.append(
                f"🕒 Рабочие часы{_parity_label(wh.week_parity)}: "
                f"{format_time(wh.start_time)}–{format_time(wh.end_time)}"
            )
        else:
            lines.append("🚫 Выходной день")

        await call.message.edit_text(
            "\n".join(lines),
            reply_markup=template_day_detail_kb(date, template_is_working),
            parse_mode="HTML",
        )
        await call.answer()
        return

    await call.answer()


@router.callback_query(AdminTemplateHoursCB.filter())
async def template_hours_requested(
    call: CallbackQuery, callback_data: AdminTemplateHoursCB, state: FSMContext, session: AsyncSession
) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return

    date = dt.date.fromisoformat(callback_data.date_str)
    weekday = date.weekday()
    week_parity = week_parity_for_date(master, date)

    await state.set_state(AdminScheduleStates.entering_hours)
    await state.update_data(weekday=weekday, week_parity=week_parity, return_to_week=date.isoformat())
    await call.message.edit_text(
        f"Укажите время работы для <b>{WEEKDAY_NAMES_RU[weekday]}</b>{_parity_label(week_parity)} "
        "в формате <b>10:00-20:00</b>.",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(AdminTemplateOffCB.filter())
async def template_off(call: CallbackQuery, callback_data: AdminTemplateOffCB, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return

    date = dt.date.fromisoformat(callback_data.date_str)
    week_parity = week_parity_for_date(master, date)
    await remove_working_day(session, master.id, date.weekday(), week_parity)

    await _show_week_schedule(call.message, session, master.id, _monday_of(date), edit=True)
    await call.answer(f"{WEEKDAY_NAMES_RU[date.weekday()]} теперь нерабочий день")


@router.message(AdminScheduleStates.entering_hours)
async def hours_entered(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    weekday = data.get("weekday")
    week_parity = data.get("week_parity")
    return_to_week = data.get("return_to_week")
    master = await get_master_by_telegram_id(session, message.from_user.id)
    if master is None or weekday is None:
        await state.clear()
        return

    text = (message.text or "").strip().lower()
    label = f"{WEEKDAY_NAMES_RU[weekday]}{_parity_label(week_parity)}"

    if text in ("выходной", "вых", "off"):
        await remove_working_day(session, master.id, weekday, week_parity)
        await state.clear()
        await message.answer(f"✅ {label} теперь нерабочий день.", reply_markup=admin_main_menu_kb())
        if return_to_week:
            await _show_week_schedule(
                message, session, master.id, _monday_of(dt.date.fromisoformat(return_to_week)), edit=False
            )
        return

    try:
        start_str, end_str = text.split("-")
        start_time = dt.datetime.strptime(start_str.strip(), "%H:%M").time()
        end_time = dt.datetime.strptime(end_str.strip(), "%H:%M").time()
        if start_time >= end_time:
            raise ValueError("start must be before end")
    except ValueError:
        await message.answer(
            "Неверный формат. Пример: <b>10:00-20:00</b>. Попробуйте снова.", parse_mode="HTML"
        )
        return

    await set_working_hours(session, master.id, weekday, start_time, end_time, week_parity)
    await state.clear()
    await message.answer(
        f"✅ {label}: {start_str.strip()}–{end_str.strip()}",
        reply_markup=admin_main_menu_kb(),
    )
    if return_to_week:
        await _show_week_schedule(
            message, session, master.id, _monday_of(dt.date.fromisoformat(return_to_week)), edit=False
        )


@router.message(F.text == BTN_DURATION)
async def duration_menu(message: Message, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, message.from_user.id)
    if master is None:
        return
    await message.answer(
        f"Текущая длительность услуги: {master.slot_duration_minutes} мин.\nВыберите новую:",
        reply_markup=slot_duration_kb(),
    )


@router.callback_query(AdminSlotDurationCB.filter())
async def duration_chosen(call: CallbackQuery, callback_data: AdminSlotDurationCB, session: AsyncSession) -> None:
    master = await get_master_by_telegram_id(session, call.from_user.id)
    if master is None:
        await call.answer()
        return
    await set_slot_duration(session, master.id, callback_data.minutes)
    await call.message.edit_text(f"✅ Длительность услуги: {callback_data.minutes} мин.")
    await call.answer()
