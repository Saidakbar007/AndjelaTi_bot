from aiogram import Router

from bot.handlers.admin import bookings, panel, schedule
from bot.utils.filters import IsAdmin


def get_admin_router() -> Router:
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())

    router.include_router(panel.router)
    router.include_router(schedule.router)
    router.include_router(bookings.router)
    return router
