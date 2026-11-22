from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.client_kb import BTN_MY_BOOKINGS, my_bookings_kb
from bot.services.booking_service import (
    cancel_booking,
    get_booking,
    get_client_active_bookings,
    get_or_create_client,
)
from bot.services.schedule_service import get_master
from bot.utils.callbacks import CancelOwnBookingCB
from bot.utils.logger import get_logger
from bot.utils.time_helpers import format_date_human, format_time

router = Router(name="client_my_bookings")
logger = get_logger(__name__)


@router.message(F.text == BTN_MY_BOOKINGS)
async def show_my_bookings(message: Message, session: AsyncSession) -> None:
    client = await get_or_create_client(
        session, message.from_user.id, message.from_user.full_name, message.from_user.username
    )
    bookings = await get_client_active_bookings(session, client.id)
    if not bookings:
        await message.answer("У вас пока нет активных записей.")
        return

    await message.answer(
        "Ваши активные записи:",
        reply_markup=my_bookings_kb(bookings),
    )


@router.callback_query(CancelOwnBookingCB.filter())
async def cancel_own_booking(
    call: CallbackQuery, callback_data: CancelOwnBookingCB, session: AsyncSession, bot: Bot
) -> None:
    booking = await get_booking(session, callback_data.booking_id)
    if booking is None:
        await call.answer("Запись не найдена", show_alert=True)
        return

    client = await get_or_create_client(
        session, call.from_user.id, call.from_user.full_name, call.from_user.username
    )
    if booking.client_id != client.id:
        # A client must never be able to cancel someone else's booking.
        await call.answer("Это не ваша запись", show_alert=True)
        return

    cancelled = await cancel_booking(session, booking.id, by="client")
    if cancelled is None:
        await call.answer("Эту запись уже отменили", show_alert=True)
        return

    await call.message.edit_text(
        f"❌ Запись на {format_date_human(booking.date)} {format_time(booking.start_time)} отменена."
    )
    await call.answer("Запись отменена")

    master = await get_master(session, booking.master_id)
    if master is not None:
        try:
            await bot.send_message(
                master.telegram_id,
                "⚠️ Клиент отменил запись:\n"
                f"📅 {format_date_human(booking.date)}\n"
                f"🕒 {format_time(booking.start_time)}\n"
                f"👤 {client.full_name}",
            )
        except Exception:
            logger.warning("Failed to notify master_id=%s about cancellation", master.id)
