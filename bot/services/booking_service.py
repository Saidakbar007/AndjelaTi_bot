from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Booking, BookingStatus, Client, Master
from bot.utils.logger import get_logger
from bot.utils.time_helpers import today

logger = get_logger(__name__)


class SlotAlreadyTakenError(Exception):
    """Raised when a slot was booked by someone else a moment earlier."""


@dataclass
class BookingResult:
    booking: Booking
    master: Master
    client: Client


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

async def get_or_create_client(
    session: AsyncSession, telegram_id: int, full_name: str, username: str | None
) -> Client:
    result = await session.execute(select(Client).where(Client.telegram_id == telegram_id))
    client = result.scalar_one_or_none()
    if client is None:
        client = Client(telegram_id=telegram_id, full_name=full_name, username=username)
        session.add(client)
        await session.commit()
    else:
        changed = False
        if client.full_name != full_name:
            client.full_name = full_name
            changed = True
        if client.username != username:
            client.username = username
            changed = True
        if changed:
            await session.commit()
    return client


async def update_client_phone(session: AsyncSession, client_id: int, phone: str) -> None:
    result = await session.execute(select(Client).where(Client.id == client_id))
    client = result.scalar_one_or_none()
    if client is None:
        return
    client.phone = phone
    await session.commit()


async def get_client_by_id(session: AsyncSession, client_id: int) -> Client | None:
    result = await session.execute(select(Client).where(Client.id == client_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

async def create_booking(
    session: AsyncSession,
    master_id: int,
    client_id: int,
    date: dt.date,
    start_time: dt.time,
    end_time: dt.time,
) -> Booking:
    """Create a new active booking.

    Race-condition safety: the DB has a partial unique index on
    (master_id, date, start_time) for ACTIVE bookings. Two concurrent
    requests for the same slot will both attempt the INSERT; only one
    commits successfully, the other hits IntegrityError and is turned
    into a friendly SlotAlreadyTakenError for the handler to display.
    """
    booking = Booking(
        master_id=master_id,
        client_id=client_id,
        date=date,
        start_time=start_time,
        end_time=end_time,
        status=BookingStatus.ACTIVE,
    )
    session.add(booking)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.info("Booking conflict detected for master_id=%s date=%s", master_id, date)
        raise SlotAlreadyTakenError()
    return booking


async def get_booking(session: AsyncSession, booking_id: int) -> Booking | None:
    result = await session.execute(select(Booking).where(Booking.id == booking_id))
    return result.scalar_one_or_none()


async def get_client_active_bookings(
    session: AsyncSession, client_id: int
) -> Sequence[Booking]:
    result = await session.execute(
        select(Booking)
        .where(
            Booking.client_id == client_id,
            Booking.status == BookingStatus.ACTIVE,
            Booking.date >= today(),
        )
        .order_by(Booking.date, Booking.start_time)
    )
    return result.scalars().all()


async def cancel_booking(
    session: AsyncSession, booking_id: int, by: str
) -> Booking | None:
    """Cancels a booking, freeing the slot. `by` is 'client' or 'master'."""
    booking = await get_booking(session, booking_id)
    if booking is None or booking.status != BookingStatus.ACTIVE:
        return None

    booking.status = (
        BookingStatus.CANCELLED_BY_CLIENT if by == "client" else BookingStatus.CANCELLED_BY_MASTER
    )
    await session.commit()
    return booking


async def get_bookings_for_master_on_date(
    session: AsyncSession, master_id: int, date: dt.date
) -> Sequence[Booking]:
    result = await session.execute(
        select(Booking)
        .where(
            Booking.master_id == master_id,
            Booking.date == date,
            Booking.status == BookingStatus.ACTIVE,
        )
        .order_by(Booking.start_time)
    )
    return result.scalars().all()


async def get_bookings_due_for_reminder(
    session: AsyncSession, window_start: dt.datetime, window_end: dt.datetime
) -> Sequence[Booking]:
    """Active, not-yet-reminded bookings whose start falls within the window.

    Dates/times are naive in the DB (local wall-clock), so callers pass in
    naive window bounds already converted to the configured timezone.
    """
    result = await session.execute(
        select(Booking).where(
            Booking.status == BookingStatus.ACTIVE,
            Booking.reminder_sent == False,  # noqa: E712
            Booking.date >= window_start.date(),
            Booking.date <= window_end.date(),
        )
    )
    bookings = result.scalars().all()

    due: list[Booking] = []
    for booking in bookings:
        start_dt = dt.datetime.combine(booking.date, booking.start_time)
        if window_start <= start_dt <= window_end:
            due.append(booking)
    return due


async def mark_reminder_sent(session: AsyncSession, booking_id: int) -> None:
    booking = await get_booking(session, booking_id)
    if booking is None:
        return
    booking.reminder_sent = True
    await session.commit()
