from aiogram.fsm.state import State, StatesGroup


class AdminScheduleStates(StatesGroup):
    entering_hours = State()
    entering_date_hours = State()
