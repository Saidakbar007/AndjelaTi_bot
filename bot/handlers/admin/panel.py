from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.admin_kb import admin_main_menu_kb
from bot.services.schedule_service import get_master_by_telegram_id
from bot.utils.callbacks import NavCB

router = Router(name="admin_panel")


@router.message(Command("admin"))
async def open_admin_panel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    master = await get_master_by_telegram_id(session, message.from_user.id)
    if master is None:
        await message.answer("Профиль мастера не найден. Перезапустите бота.")
        return

    await message.answer(
        f"👋 Панель управления, {master.full_name}.\nВыберите раздел:",
        reply_markup=admin_main_menu_kb(),
    )


@router.callback_query(NavCB.filter(F.action == "admin_home"))
async def admin_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Главное меню панели управления ниже 👇")
    await call.answer()
