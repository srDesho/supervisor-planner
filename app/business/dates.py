"""
Date and operational time calculations for Supervisor Planner.
All operational calculations are performed under America/La_Paz timezone.
"""
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from app.config import get_settings


BOLIVIA_TZ = ZoneInfo("America/La_Paz")

WEEKDAY_CODES = {
    0: "1-LU",  # Monday
    1: "2-MA",  # Tuesday
    2: "3-MI",  # Wednesday
    3: "4-JU",  # Thursday
    4: "5-VI",  # Friday
    5: "6-SA",  # Saturday
}


def get_current_bolivia_datetime() -> datetime:
    """Returns the current datetime in America/La_Paz timezone."""
    return datetime.now(BOLIVIA_TZ)


def calculate_work_date(
    now: Optional[datetime] = None,
    monday_cutoff: Optional[str] = None,
    saturday_cutoff: str = "12:00"
) -> date:
    """
    Calculates the target operational work date according to Company business rules.
    Company operates Monday through Saturday; Sunday is not a work day.
    The same rule serves reminders and incoming supervisor messages, at any hour:
    - Monday before `monday_cutoff`: same Monday (Monday AM catch-up).
    - Monday from `monday_cutoff` on: Tuesday.
    - Tuesday, Wednesday, Thursday: next day.
    - Friday: Saturday (+1 day), since Saturday is a work day.
    - Saturday before `saturday_cutoff`: same Saturday.
    - Saturday from `saturday_cutoff` on: next Monday (+2 days), skipping Sunday.
    - Sunday: next Monday (+1 day).

    :param now: datetime to evaluate. If naive, assumed in America/La_Paz. If None, uses current Bolivia time.
    :param monday_cutoff: 'HH:MM' from which Monday plans for Tuesday. Defaults to
        the MONDAY_PM_WINDOW_START setting.
    :param saturday_cutoff: 'HH:MM' from which Saturday plans for Monday (the
        machine is switched off at 12:00 on Saturdays).
    :return: Target work date.
    """
    if now is None:
        now = get_current_bolivia_datetime()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=BOLIVIA_TZ)
    else:
        now = now.astimezone(BOLIVIA_TZ)

    if monday_cutoff is None:
        monday_cutoff = get_settings().MONDAY_PM_WINDOW_START

    monday_cutoff_t = time(*map(int, monday_cutoff.split(":")))
    saturday_cutoff_t = time(*map(int, saturday_cutoff.split(":")))

    current_date = now.date()
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    if weekday == 0:  # Monday
        if now.time() < monday_cutoff_t:
            return current_date
        return current_date + timedelta(days=1)
    elif weekday in (1, 2, 3):  # Tuesday, Wednesday, Thursday
        return current_date + timedelta(days=1)
    elif weekday == 4:  # Friday -> Saturday (+1), Saturday is a work day
        return current_date + timedelta(days=1)
    elif weekday == 5:  # Saturday
        if now.time() < saturday_cutoff_t:
            return current_date
        return current_date + timedelta(days=2)  # Next Monday
    elif weekday == 6:  # Sunday -> Next Monday (+1)
        return current_date + timedelta(days=1)
    else:
        raise ValueError(f"Invalid weekday: {weekday}")


def get_weekday_code(target_date: date) -> str:
    """
    Returns the standardized day code from the master sheet (1-LU, 2-MA, 3-MI, 4-JU, 5-VI, 6-SA).
    Raises ValueError if target_date is a Sunday.
    """
    weekday = target_date.weekday()
    if weekday not in WEEKDAY_CODES:
        raise ValueError(f"La fecha {target_date} es Domingo ({weekday}), el cual no es un día de ruta comercial válido.")
    return WEEKDAY_CODES[weekday]
