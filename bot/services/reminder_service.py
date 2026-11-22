from __future__ import annotations

import datetime as dt

from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import settings
from bot.services.booking_service import (
    get_bookings_due_for_reminder,
    get_client_by_id,
    mark_reminder_sent,
)
from bot.services.schedule_service import get_master
from bot.utils.logger import get_logger
from bot.utils.time_helpers import format_date_human, format_time, now

logger = get_logger(__name__)

CHECK_INTERVAL = dt.timedelta(minutes=1)


async def check_and_send_reminders(
    bot: Bot, session_factory: async_sessionmaker
) -> None:
    """Scans for active bookings starting ~REMINDER_HOURS_BEFORE from now and
    sends the client a reminder once, flagging reminder_sent so it never
    fires twice for the same booking.

    Intended to be scheduled by APScheduler every CHECK_INTERVAL.
    """
    reminder_delta = dt.timedelta(hours=settings.REMINDER_HOURS_BEFORE)
    current_naive = now().replace(tzinfo=None)
    window_start = current_naive + reminder_delta
    window_end = window_start + CHECK_INTERVAL

    async with session_factory() as session:
        due_bookings = await get_bookings_due_for_reminder(session, window_start, window_end)

        for booking in due_bookings:
            client = await get_client_by_id(session, booking.client_id)
            master = await get_master(session, booking.master_id)
            if client is None or master is None:
                continue

            text = (
                "⏰ Напоминание о записи!\n\n"
                f"Вы записаны к мастеру {master.full_name} на "
                f"{format_date_human(booking.date)} в {format_time(booking.start_time)}.\n"
                "Пожалуйста, не опаздывайте 🙂"
            )
            try:
                await bot.send_message(client.telegram_id, text)
            except Exception:
                logger.warning(
                    "Failed to deliver reminder for booking_id=%s", booking.id
                )
            finally:
                # Mark as sent even on delivery failure (e.g. user blocked
                # the bot) to avoid retrying indefinitely.
                await mark_reminder_sent(session, booking.id)
