from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    choosing_master = State()
    choosing_date = State()
    choosing_slot = State()
    entering_phone = State()
    confirming = State()
