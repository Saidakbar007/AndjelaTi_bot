from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MasterCB(CallbackData, prefix="master"):
    master_id: int


class CalCb(CallbackData, prefix="cal"):
    """Single calendar component shared by the client and the admin panel.

    role: "client" | "admin" — which flow should handle the click.
    action: "day" (a real day was tapped) | "prev" / "next" (month nav) |
            "ignore" (header/weekday/padding cell, or an unavailable day for
            the client — just acknowledged, no navigation) | "back" (return
            to the calendar for the month containing date_str).
    date_str: "YYYY-MM-DD". For "prev"/"next" it's the 1st of the month to
            jump to; for everything else it's the concrete day in question.
    """

    role: str
    action: str
    date_str: str


# Slot/confirm time values are encoded as "HHMM" (no colon!) because
# aiogram's CallbackData uses ":" as the field separator — packing a value
# that itself contains ":" raises ValueError. This is what used to break
# "choose time" after picking a date.
class SlotCB(CallbackData, prefix="slot"):
    master_id: int
    date: str
    time: str  # "HHMM"


class ConfirmBookingCB(CallbackData, prefix="confirm_bk"):
    master_id: int
    date: str
    time: str  # "HHMM"


class CancelOwnBookingCB(CallbackData, prefix="cancel_own"):
    booking_id: int


class AdminCancelBookingCB(CallbackData, prefix="adm_cancel"):
    booking_id: int


class AdminSlotDurationCB(CallbackData, prefix="adm_dur"):
    minutes: int


class AdminTemplateHoursCB(CallbackData, prefix="adm_tpl_hrs"):
    """Edit/set the weekly-template hours for the weekday+week-parity
    implied by this concrete date (from the "🗓 График работы" week view).
    """

    date_str: str


class AdminTemplateOffCB(CallbackData, prefix="adm_tpl_off"):
    """Remove the weekly-template row for the weekday+week-parity implied
    by this concrete date, making that recurring slot a rest day.
    """

    date_str: str


class AdminDayToggleCB(CallbackData, prefix="adm_day_tog"):
    scope: str  # "date" | "weekday"
    date_str: str  # anchor date; weekday is derived from it when scope="weekday"


class AdminDayHoursCB(CallbackData, prefix="adm_day_hrs"):
    date_str: str


class AdminResetOverrideCB(CallbackData, prefix="adm_day_rst"):
    date_str: str


class NavCB(CallbackData, prefix="nav"):
    action: str
