from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message, TelegramObject

from bot.config import settings


class IsAdmin(BaseFilter):
    """Restricts a handler to users listed in ADMIN_IDS only.

    This is the single source of truth for admin access — client handlers
    must never be reachable by admin-only callback data, and vice versa,
    callback data namespaces are also kept distinct (adm_* vs plain) as a
    second layer of defense.
    """

    async def __call__(self, obj: TelegramObject) -> bool:
        user = getattr(obj, "from_user", None)
        if user is None:
            return False
        return user.id in settings.admin_ids
