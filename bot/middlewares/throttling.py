from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.utils.logger import get_logger

logger = get_logger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Rate-limits rapid-fire messages/clicks from the same user.

    Keeps a tiny in-memory map of user_id -> last_event_timestamp. If a new
    event arrives sooner than `rate_limit` seconds after the previous one,
    it is silently dropped (callback queries get a lightweight "wait"
    popup so the user understands why nothing happened).

    No personal data is logged — only the fact that a throttle triggered.
    """

    def __init__(self, rate_limit: float = 0.5) -> None:
        self.rate_limit = rate_limit
        self._last_event: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        now_ts = time.monotonic()
        last_ts = self._last_event.get(user.id)
        self._last_event[user.id] = now_ts

        if last_ts is not None and (now_ts - last_ts) < self.rate_limit:
            logger.debug("Throttled a rapid event from user_id=%s", user.id)
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Пожалуйста, не так быстро 🙂", cache_time=1)
                except Exception:
                    pass
            return None

        return await handler(event, data)
