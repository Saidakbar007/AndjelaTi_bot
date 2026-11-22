from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import settings
from bot.database.engine import async_session_factory, init_db
from bot.handlers.admin import get_admin_router
from bot.handlers.client import get_client_router
from bot.middlewares.db_session import DbSessionMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.reminder_service import check_and_send_reminders
from bot.services.schedule_service import sync_masters_from_admin_ids
from bot.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


async def on_startup(bot: Bot) -> None:
    await init_db()
    async with async_session_factory() as session:
        await sync_masters_from_admin_ids(session)

    me = await bot.get_me()
    logger.info("Database ready, masters synced. Bot @%s started.", me.username)


async def main() -> None:
    setup_logging()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # One DB session per update, shared across all handlers for that update.
    dp.update.outer_middleware(DbSessionMiddleware(async_session_factory))

    # Flood protection on both plain messages and inline button clicks.
    # One shared instance (not two separate ones) so its per-user timer
    # applies across both event kinds — otherwise a user could dodge the
    # limit by alternating a message and a button click.
    throttling = ThrottlingMiddleware(rate_limit=0.4)
    dp.message.middleware(throttling)
    dp.callback_query.middleware(throttling)

    dp.include_router(get_admin_router())
    dp.include_router(get_client_router())

    dp.startup.register(on_startup)

    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
    scheduler.add_job(
        check_and_send_reminders,
        trigger="interval",
        seconds=60,
        args=[bot, async_session_factory],
        id="reminder_check",
        misfire_grace_time=30,
        max_instances=1,
    )

    try:
        scheduler.start()
        logger.info("Starting bot polling...")
        # start_polling handles SIGTERM/SIGINT and closes the bot's HTTP
        # session on shutdown by default (handle_signals=True,
        # close_bot_session=True) — this is what gives systemd a clean
        # `systemctl stop` / Restart=always lifecycle for free.
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
