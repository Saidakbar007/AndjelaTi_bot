from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BookingStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED_BY_CLIENT = "cancelled_by_client"
    CANCELLED_BY_MASTER = "cancelled_by_master"
    COMPLETED = "completed"


class Master(Base):
    """A barber/hairdresser. Scalable to many masters via master_id everywhere."""

    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="Мастер")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Anchor Monday for alternating (every-other-week) schedules: the Monday
    # of whatever week counts as "week 1" (week_parity=0 on WorkingHours).
    # NULL means this master doesn't use alternating weeks — every
    # WorkingHours row simply applies every week.
    week1_anchor_monday: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    working_hours: Mapped[list["WorkingHours"]] = relationship(
        back_populates="master", cascade="all, delete-orphan"
    )
    days_off: Mapped[list["DayOff"]] = relationship(
        back_populates="master", cascade="all, delete-orphan"
    )
    date_overrides: Mapped[list["DateOverride"]] = relationship(
        back_populates="master", cascade="all, delete-orphan"
    )
    bookings: Mapped[list["Booking"]] = relationship(back_populates="master")


class WorkingHours(Base):
    """Weekly template: for each weekday (0=Mon..6=Sun) the master's working
    window. `week_parity` makes a row apply only on alternating weeks:
    NULL = every week, 0 = "week 1" weeks, 1 = "week 2" weeks (relative to
    Master.week1_anchor_monday). A weekday may have up to one NULL row plus
    one row per parity.
    """

    __tablename__ = "working_hours"
    __table_args__ = (
        UniqueConstraint(
            "master_id", "weekday", "week_parity", name="uq_master_weekday_parity"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon ... 6=Sun
    week_parity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    master: Mapped["Master"] = relationship(back_populates="working_hours")


class DayOff(Base):
    """A specific calendar date excluded from booking (vacation, sick day, holiday)."""

    __tablename__ = "days_off"
    __table_args__ = (
        UniqueConstraint("master_id", "date", name="uq_master_dayoff_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    master: Mapped["Master"] = relationship(back_populates="days_off")


class DateOverride(Base):
    """Custom working hours for one specific date, overriding the weekly
    WorkingHours template for that date only (e.g. shorter hours on a
    particular day) without touching the template itself. Takes effect only
    when the date is not also marked as a DayOff.
    """

    __tablename__ = "date_overrides"
    __table_args__ = (
        UniqueConstraint("master_id", "date", name="uq_master_date_override"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)

    master: Mapped["Master"] = relationship(back_populates="date_overrides")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    bookings: Mapped[list["Booking"]] = relationship(back_populates="client")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus), default=BookingStatus.ACTIVE, nullable=False
    )
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    master: Mapped["Master"] = relationship(back_populates="bookings")
    client: Mapped["Client"] = relationship(back_populates="bookings")


# DB-level protection against double-booking the same master/date/time.
# Only ACTIVE bookings participate in the uniqueness check, so a cancelled
# slot can be freely rebooked. Works as a partial unique index on both
# SQLite and PostgreSQL. Combined with transaction-level IntegrityError
# handling in booking_service, this closes the race-condition window where
# two clients could otherwise grab the same slot at the same time.
Index(
    "uq_active_master_slot",
    Booking.master_id,
    Booking.date,
    Booking.start_time,
    unique=True,
    sqlite_where=(Booking.status == BookingStatus.ACTIVE),
    postgresql_where=(Booking.status == BookingStatus.ACTIVE),
)
