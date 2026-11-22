from aiogram import Router

from bot.handlers.client import booking, menu, my_bookings


def get_client_router() -> Router:
    router = Router(name="client")
    router.include_router(menu.router)
    router.include_router(booking.router)
    router.include_router(my_bookings.router)
    return router
