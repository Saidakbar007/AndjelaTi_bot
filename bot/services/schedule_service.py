from __future__ import annotations

import calendar as calendar_module
import datetime as dt
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.models import Booking, BookingStatus, DateOverride, DayOff, Master, WorkingHours
from bot.utils.time_helpers import now, today

BOOKING_HORIZON_DAYS = 21


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------

async def sync_masters_from_admin_ids(session: AsyncSession) -> None:
    """Ensure every ADMIN_IDS entry has a corresponding Master row.

    Called on startup so the admin panel / booking logic always has a
    master_id to work with, without any manual setup step.
    """
    result = await session.execute(select(Master.telegram_id))
    existing_ids = {row[0] for row in result.all()}

    for admin_id in settings.admin_ids:
        if admin_id not in existing_ids:
            session.add(Master(telegram_id=admin_id, full_name="Мастер"))
    await session.commit()


async def get_master_by_telegram_id(session: AsyncSession, telegram_id: int) -> Master | None:
    result = await session.execute(select(Master).where(Master.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_master(session: AsyncSession, master_id: int) -> Master | None:
    result = await session.execute(select(Master).where(Master.id == master_id))
    return result.scalar_one_or_none()


async def get_active_masters(session: AsyncSession) -> Sequence[Master]:
    result = await session.execute(select(Master).where(Master.is_active == True))  # noqa: E712
    return result.scalars().all()


async def update_master_profile(
    session: AsyncSession, master_id: int, full_name: str | None = None, phone: str | None = None
) -> None:
    master = await get_master(session, master_id)
    if master is None:
        return
    if full_name is not None:
        master.full_name = full_name
    if phone is not None:
        master.phone = phone
    await session.commit()


async def set_slot_duration(session: AsyncSession, master_id: int, minutes: int) -> None:
    master = await get_master(session, master_id)
    if master is None:
        return
    master.slot_duration_minutes = minutes
    await session.commit()


async def set_week1_anchor(session: AsyncSession, master_id: int, monday_date: dt.date) -> None:
    """Defines the Monday that starts "week 1" for this master's alternating
    (every-other-week) schedule. `monday_date` must be a Monday.
    """
    master = await get_master(session, master_id)
    if master is None:
        return
    master.week1_anchor_monday = monday_date
    await session.commit()


# ---------------------------------------------------------------------------
# Working hours (weekly template, optionally alternating every other week)
# ---------------------------------------------------------------------------

def week_parity_for_date(master: Master, date: dt.date) -> int | None:
    """0 = "week 1", 1 = "week 2", relative to master.week1_anchor_monday.

    Returns None if the master has no anchor configured, meaning alternating
    weeks are not in use — every WorkingHours row then simply applies to
    every week (week_parity=None rows only).
    """
    if master.week1_anchor_monday is None:
        return None
    monday_of_week = date - dt.timedelta(days=date.weekday())
    weeks_diff = (monday_of_week - master.week1_anchor_monday).days // 7
    return weeks_diff % 2


async def get_working_hours_rows(
    session: AsyncSession, master_id: int
) -> dict[int, list[WorkingHours]]:
    """weekday -> all configured rows for it (there can be one "every week"
    row and/or one row per week parity).
    """
    result = await session.execute(
        select(WorkingHours).where(WorkingHours.master_id == master_id)
    )
    grouped: dict[int, list[WorkingHours]] = {}
    for row in result.scalars().all():
        grouped.setdefault(row.weekday, []).append(row)
    return grouped


def pick_working_hours_row(
    rows_for_weekday: Sequence[WorkingHours], parity: int | None
) -> WorkingHours | None:
    """From the rows configured for one weekday, pick the one that applies
    on a date with the given week parity: an exact parity match wins, else
    fall back to the "every week" (parity=None) row, else none configured.
    """
    if parity is not None:
        for row in rows_for_weekday:
            if row.week_parity == parity:
                return row
    for row in rows_for_weekday:
        if row.week_parity is None:
            return row
    return None


async def get_working_hours_for_date(
    session: AsyncSession, master_id: int, date: dt.date
) -> WorkingHours | None:
    master = await get_master(session, master_id)
    if master is None:
        return None
    rows = await get_working_hours_rows(session, master_id)
    parity = week_parity_for_date(master, date)
    return pick_working_hours_row(rows.get(date.weekday(), []), parity)


async def set_working_hours(
    session: AsyncSession,
    master_id: int,
    weekday: int,
    start_time: dt.time,
    end_time: dt.time,
    week_parity: int | None = None,
) -> None:
    result = await session.execute(
        select(WorkingHours).where(
            WorkingHours.master_id == master_id,
            WorkingHours.weekday == weekday,
            WorkingHours.week_parity == week_parity,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = WorkingHours(
            master_id=master_id,
            weekday=weekday,
            week_parity=week_parity,
            start_time=start_time,
            end_time=end_time,
        )
        session.add(row)
    else:
        row.start_time = start_time
        row.end_time = end_time
        row.is_working_day = True
    await session.commit()


async def remove_working_day(
    session: AsyncSession, master_id: int, weekday: int, week_parity: int | None = None
) -> None:
    result = await session.execute(
        select(WorkingHours).where(
            WorkingHours.master_id == master_id,
            WorkingHours.weekday == weekday,
            WorkingHours.week_parity == week_parity,
        )
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()


# ---------------------------------------------------------------------------
# Days off
# ---------------------------------------------------------------------------

async def get_future_days_off(session: AsyncSession, master_id: int) -> Sequence[DayOff]:
    result = await session.execute(
        select(DayOff)
        .where(DayOff.master_id == master_id, DayOff.date >= today())
        .order_by(DayOff.date)
    )
    return result.scalars().all()


async def get_active_bookings_on_date(
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


async def add_day_off(
    session: AsyncSession, master_id: int, date: dt.date, reason: str | None = None
) -> Sequence[Booking]:
    """Marks `date` as a day off. Returns the active bookings on that date
    (if any) so the caller can warn the master and let clients know.
    """
    existing_bookings = await get_active_bookings_on_date(session, master_id, date)

    result = await session.execute(
        select(DayOff).where(DayOff.master_id == master_id, DayOff.date == date)
    )
    if result.scalar_one_or_none() is None:
        session.add(DayOff(master_id=master_id, date=date, reason=reason))
        await session.commit()

    return existing_bookings


async def remove_day_off(session: AsyncSession, master_id: int, date: dt.date) -> None:
    result = await session.execute(
        select(DayOff).where(DayOff.master_id == master_id, DayOff.date == date)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()


async def is_day_off(session: AsyncSession, master_id: int, date: dt.date) -> bool:
    result = await session.execute(
        select(DayOff.id).where(DayOff.master_id == master_id, DayOff.date == date)
    )
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Date-specific overrides (custom hours for one date, on top of the weekly
# template, without touching the template itself)
# ---------------------------------------------------------------------------

async def get_date_override(
    session: AsyncSession, master_id: int, date: dt.date
) -> DateOverride | None:
    result = await session.execute(
        select(DateOverride).where(DateOverride.master_id == master_id, DateOverride.date == date)
    )
    return result.scalar_one_or_none()


async def set_date_override(
    session: AsyncSession, master_id: int, date: dt.date, start_time: dt.time, end_time: dt.time
) -> None:
    existing = await get_date_override(session, master_id, date)
    if existing is None:
        session.add(
            DateOverride(master_id=master_id, date=date, start_time=start_time, end_time=end_time)
        )
    else:
        existing.start_time = start_time
        existing.end_time = end_time
    # Custom hours imply the date is a working day, so any day-off flag on
    # it would be contradictory — clear it.
    await remove_day_off(session, master_id, date)
    await session.commit()


async def remove_date_override(session: AsyncSession, master_id: int, date: dt.date) -> None:
    existing = await get_date_override(session, master_id, date)
    if existing is not None:
        await session.delete(existing)
        await session.commit()


# ---------------------------------------------------------------------------
# Slot generation
# ---------------------------------------------------------------------------

def _generate_slot_starts(
    start_time: dt.time, end_time: dt.time, slot_minutes: int
) -> list[dt.time]:
    slots: list[dt.time] = []
    anchor_date = dt.date.today()
    cursor = dt.datetime.combine(anchor_date, start_time)
    end_dt = dt.datetime.combine(anchor_date, end_time)
    step = dt.timedelta(minutes=slot_minutes)
    while cursor + step <= end_dt:
        slots.append(cursor.time())
        cursor += step
    return slots


async def get_free_slots(
    session: AsyncSession, master_id: int, date: dt.date
) -> list[dt.time]:
    """Free, future slot start times for `master_id` on `date`.

    Already booked (active) slots and past slots (if date is today) are
    excluded. A per-date override (if any) takes precedence over the
    weekly template; a day-off always wins over both.
    """
    master = await get_master(session, master_id)
    if master is None or not master.is_active:
        return []

    if await is_day_off(session, master_id, date):
        return []

    override = await get_date_override(session, master_id, date)
    if override is not None:
        start_time, end_time = override.start_time, override.end_time
    else:
        wh = await get_working_hours_for_date(session, master_id, date)
        if wh is None or not wh.is_working_day:
            return []
        start_time, end_time = wh.start_time, wh.end_time

    all_slots = _generate_slot_starts(start_time, end_time, master.slot_duration_minutes)

    booked_result = await session.execute(
        select(Booking.start_time).where(
            Booking.master_id == master_id,
            Booking.date == date,
            Booking.status == BookingStatus.ACTIVE,
        )
    )
    booked_times = {row[0] for row in booked_result.all()}

    free_slots = [s for s in all_slots if s not in booked_times]

    if date == today():
        current_time = now().time()
        free_slots = [s for s in free_slots if s > current_time]

    return free_slots


async def get_day_schedule_grid(
    session: AsyncSession, master_id: int, date: dt.date
) -> list[dict]:
    """Full visual timeline of `date`: every slot start within working
    hours (template or date override), stepped by the master's own slot
    duration, each tagged with a status — "booked" (with the Booking row),
    "past" (today, already gone, never booked), or "free" — so callers can
    render the whole day at a glance like a master's own paper schedule,
    instead of only a list of free times.

    Returns [] for a day off / non-working day, mirroring get_free_slots.
    """
    master = await get_master(session, master_id)
    if master is None or not master.is_active:
        return []

    if await is_day_off(session, master_id, date):
        return []

    override = await get_date_override(session, master_id, date)
    if override is not None:
        start_time, end_time = override.start_time, override.end_time
    else:
        wh = await get_working_hours_for_date(session, master_id, date)
        if wh is None or not wh.is_working_day:
            return []
        start_time, end_time = wh.start_time, wh.end_time

    slot_starts = _generate_slot_starts(start_time, end_time, master.slot_duration_minutes)
    bookings = await get_active_bookings_on_date(session, master_id, date)
    booking_by_start = {b.start_time: b for b in bookings}

    current_time = now().time() if date == today() else None

    grid: list[dict] = []
    for slot_start in slot_starts:
        booking = booking_by_start.get(slot_start)
        if booking is not None:
            status = "booked"
        elif current_time is not None and slot_start <= current_time:
            status = "past"
        else:
            status = "free"
        grid.append({"start_time": slot_start, "booking": booking, "status": status})
    return grid


def upcoming_dates(horizon_days: int = BOOKING_HORIZON_DAYS) -> list[dt.date]:
    """Plain list of the next `horizon_days` calendar dates (today included),
    with no filtering by working hours / availability. Used by the admin
    panel to let the master pick any date, even non-working ones.
    """
    start_date = today()
    return [start_date + dt.timedelta(days=i) for i in range(horizon_days)]


async def get_available_dates(
    session: AsyncSession, master_id: int, horizon_days: int = BOOKING_HORIZON_DAYS
) -> list[dt.date]:
    """Dates within the booking horizon that have at least one free slot."""
    start_date = today()
    candidate_dates = [start_date + dt.timedelta(days=i) for i in range(horizon_days)]

    available: list[dt.date] = []
    for date in candidate_dates:
        slots = await get_free_slots(session, master_id, date)
        if slots:
            available.append(date)
    return available


def _month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    first = dt.date(year, month, 1)
    last = dt.date(year, month, calendar_module.monthrange(year, month)[1])
    return first, last


async def get_client_month_availability(
    session: AsyncSession, master_id: int, year: int, month: int
) -> dict[int, str]:
    """day-of-month -> "available" | "day_off" | "unavailable", for the
    whole calendar month in one batch of queries (instead of calling
    get_free_slots once per day), used to render the client's monthly
    calendar.
    """
    first_day, last_day = _month_range(year, month)
    start_date = max(first_day, today())
    if start_date > last_day:
        return {}

    master = await get_master(session, master_id)
    if master is None or not master.is_active:
        return {}

    working_hours_rows = await get_working_hours_rows(session, master_id)

    days_off_result = await session.execute(
        select(DayOff.date).where(
            DayOff.master_id == master_id, DayOff.date >= start_date, DayOff.date <= last_day
        )
    )
    days_off_set = {row[0] for row in days_off_result.all()}

    overrides_result = await session.execute(
        select(DateOverride).where(
            DateOverride.master_id == master_id,
            DateOverride.date >= start_date,
            DateOverride.date <= last_day,
        )
    )
    overrides_map = {row.date: row for row in overrides_result.scalars().all()}

    booked_result = await session.execute(
        select(Booking.date, Booking.start_time).where(
            Booking.master_id == master_id,
            Booking.status == BookingStatus.ACTIVE,
            Booking.date >= start_date,
            Booking.date <= last_day,
        )
    )
    booked_map: dict[dt.date, set[dt.time]] = {}
    for booked_date, booked_time in booked_result.all():
        booked_map.setdefault(booked_date, set()).add(booked_time)

    current_time = now().time()
    availability: dict[int, str] = {}
    cursor = start_date
    while cursor <= last_day:
        if cursor in days_off_set:
            availability[cursor.day] = "day_off"
            cursor += dt.timedelta(days=1)
            continue

        override = overrides_map.get(cursor)
        if override is not None:
            start_time, end_time = override.start_time, override.end_time
        else:
            parity = week_parity_for_date(master, cursor)
            wh = pick_working_hours_row(working_hours_rows.get(cursor.weekday(), []), parity)
            if wh is None or not wh.is_working_day:
                availability[cursor.day] = "unavailable"
                cursor += dt.timedelta(days=1)
                continue
            start_time, end_time = wh.start_time, wh.end_time

        all_slots = _generate_slot_starts(start_time, end_time, master.slot_duration_minutes)
        free_slots = [s for s in all_slots if s not in booked_map.get(cursor, set())]
        if cursor == today():
            free_slots = [s for s in free_slots if s > current_time]

        availability[cursor.day] = "available" if free_slots else "unavailable"
        cursor += dt.timedelta(days=1)

    return availability


async def get_admin_month_overview(
    session: AsyncSession, master_id: int, year: int, month: int
) -> dict[int, dict]:
    """day-of-month -> {is_day_off, is_working, has_override, bookings_count}
    for the whole calendar month in one batch of queries, used to render
    the admin's monthly calendar with per-day status/load badges.
    """
    first_day, last_day = _month_range(year, month)
    master = await get_master(session, master_id)
    if master is None:
        return {}
    working_hours_rows = await get_working_hours_rows(session, master_id)

    days_off_result = await session.execute(
        select(DayOff.date).where(
            DayOff.master_id == master_id, DayOff.date >= first_day, DayOff.date <= last_day
        )
    )
    days_off_set = {row[0] for row in days_off_result.all()}

    overrides_result = await session.execute(
        select(DateOverride.date).where(
            DateOverride.master_id == master_id,
            DateOverride.date >= first_day,
            DateOverride.date <= last_day,
        )
    )
    overrides_set = {row[0] for row in overrides_result.all()}

    bookings_result = await session.execute(
        select(Booking.date, func.count(Booking.id))
        .where(
            Booking.master_id == master_id,
            Booking.status == BookingStatus.ACTIVE,
            Booking.date >= first_day,
            Booking.date <= last_day,
        )
        .group_by(Booking.date)
    )
    bookings_count_map = {row[0]: row[1] for row in bookings_result.all()}

    overview: dict[int, dict] = {}
    cursor = first_day
    while cursor <= last_day:
        is_day_off_flag = cursor in days_off_set
        has_override = cursor in overrides_set
        if is_day_off_flag:
            is_working = False
        elif has_override:
            is_working = True
        else:
            parity = week_parity_for_date(master, cursor)
            wh = pick_working_hours_row(working_hours_rows.get(cursor.weekday(), []), parity)
            is_working = wh is not None and wh.is_working_day

        overview[cursor.day] = {
            "is_day_off": is_day_off_flag,
            "is_working": is_working,
            "has_override": has_override,
            "bookings_count": bookings_count_map.get(cursor, 0),
        }
        cursor += dt.timedelta(days=1)

    return overview


async def get_week_schedule_overview(
    session: AsyncSession, master_id: int, monday_date: dt.date
) -> dict[dt.date, dict]:
    """date -> {is_working, start_time, end_time, is_day_off, is_override,
    week_parity, bookings_count} for exactly the 7 days starting at
    `monday_date` (which may span a month boundary) — used to render the
    "🗓 График работы" week-calendar view.
    """
    last_day = monday_date + dt.timedelta(days=6)
    master = await get_master(session, master_id)
    if master is None:
        return {}

    working_hours_rows = await get_working_hours_rows(session, master_id)

    days_off_result = await session.execute(
        select(DayOff.date).where(
            DayOff.master_id == master_id, DayOff.date >= monday_date, DayOff.date <= last_day
        )
    )
    days_off_set = {row[0] for row in days_off_result.all()}

    overrides_result = await session.execute(
        select(DateOverride).where(
            DateOverride.master_id == master_id,
            DateOverride.date >= monday_date,
            DateOverride.date <= last_day,
        )
    )
    overrides_map = {row.date: row for row in overrides_result.scalars().all()}

    bookings_result = await session.execute(
        select(Booking.date, func.count(Booking.id))
        .where(
            Booking.master_id == master_id,
            Booking.status == BookingStatus.ACTIVE,
            Booking.date >= monday_date,
            Booking.date <= last_day,
        )
        .group_by(Booking.date)
    )
    bookings_count_map = {row[0]: row[1] for row in bookings_result.all()}

    overview: dict[dt.date, dict] = {}
    cursor = monday_date
    while cursor <= last_day:
        bookings_count = bookings_count_map.get(cursor, 0)

        if cursor in days_off_set:
            overview[cursor] = {
                "is_working": False,
                "is_day_off": True,
                "is_override": False,
                "start_time": None,
                "end_time": None,
                "week_parity": None,
                "bookings_count": bookings_count,
            }
            cursor += dt.timedelta(days=1)
            continue

        override = overrides_map.get(cursor)
        if override is not None:
            overview[cursor] = {
                "is_working": True,
                "is_day_off": False,
                "is_override": True,
                "start_time": override.start_time,
                "end_time": override.end_time,
                "week_parity": None,
                "bookings_count": bookings_count,
            }
            cursor += dt.timedelta(days=1)
            continue

        parity = week_parity_for_date(master, cursor)
        wh = pick_working_hours_row(working_hours_rows.get(cursor.weekday(), []), parity)
        if wh is not None and wh.is_working_day:
            overview[cursor] = {
                "is_working": True,
                "is_day_off": False,
                "is_override": False,
                "start_time": wh.start_time,
                "end_time": wh.end_time,
                "week_parity": wh.week_parity,
                "bookings_count": bookings_count,
            }
        else:
            overview[cursor] = {
                "is_working": False,
                "is_day_off": False,
                "is_override": False,
                "start_time": None,
                "end_time": None,
                "week_parity": parity,
                "bookings_count": bookings_count,
            }
        cursor += dt.timedelta(days=1)

    return overview
