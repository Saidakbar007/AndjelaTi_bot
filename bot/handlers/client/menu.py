from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.client_kb import BTN_INFO, main_menu_kb
from bot.services.booking_service import get_or_create_client
from bot.services.schedule_service import get_active_masters, get_working_hours_rows
from bot.utils.time_helpers import WEEKDAY_NAMES_RU, format_time

router = Router(name="client_menu")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await get_or_create_client(
        session,
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )
    await message.answer(
        "Привет! 👋 Я помогу записаться к мастеру.\n\n"
        "Выберите действие в меню ниже.",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == BTN_INFO)
async def show_info(message: Message, session: AsyncSession) -> None:
    masters = await get_active_masters(session)
    if not masters:
        await message.answer("Мастера пока не настроены. Загляните позже.")
        return

    chunks = []
    for master in masters:
        rows_by_weekday = await get_working_hours_rows(session, master.id)
        lines = [f"💈 <b>{html.escape(master.full_name)}</b>"]
        if master.phone:
            lines.append(f"📞 {html.escape(master.phone)}")
        if rows_by_weekday:
            lines.append("\nГрафик работы:")
            for weekday in range(7):
                rows = rows_by_weekday.get(weekday, [])
                if not rows or all(not r.is_working_day for r in rows):
                    lines.append(f"{WEEKDAY_NAMES_RU[weekday]}: выходной")
                    continue
                for row in rows:
                    if not row.is_working_day:
                        continue
                    suffix = (
                        f" (неделя {row.week_parity + 1})" if row.week_parity is not None else ""
                    )
                    lines.append(
                        f"{WEEKDAY_NAMES_RU[weekday]}: {format_time(row.start_time)}–{format_time(row.end_time)}{suffix}"
                    )
        else:
            lines.append("\nГрафик пока не настроен.")
        chunks.append("\n".join(lines))

    await message.answer("\n\n".join(chunks), parse_mode="HTML")
