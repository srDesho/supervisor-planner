"""
Date and operational time calculations for Supervisor Planner.
All operational calculations are performed under America/La_Paz timezone.
"""
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from typing import Optional


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
    monday_cutoff: str = "08:30"
) -> date:
    """
    Calculates the target operational work date according to Company business rules.
    Company operates Monday through Saturday; Sunday is not a work day.
    - Monday 00:00 to 08:30 (inclusive): same Monday.
    - Monday after 08:30: Tuesday.
    - Tuesday: Wednesday.
    - Wednesday: Thursday.
    - Thursday: Friday.
    - Friday: Saturday (+1 day), since Saturday is a work day.
    - Saturday: Next Monday (+2 days), skipping Sunday.
    - Sunday: Next Monday (+1 day).

    :param now: datetime to evaluate. If naive, assumed in America/La_Paz. If None, uses current Bolivia time.
    :param monday_cutoff: Cutoff time string in 'HH:MM' format (default '08:30').
    :return: Target work date.
    """
    if now is None:
        now = get_current_bolivia_datetime()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=BOLIVIA_TZ)
    else:
        now = now.astimezone(BOLIVIA_TZ)

    # Parse cutoff time
    cutoff_hour, cutoff_minute = map(int, monday_cutoff.split(":"))
    cutoff_t = time(cutoff_hour, cutoff_minute)

    current_date = now.date()
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    if weekday == 0:  # Monday
        if now.time() <= cutoff_t:
            return current_date
        else:
            return current_date + timedelta(days=1)
    elif weekday in (1, 2, 3):  # Tuesday, Wednesday, Thursday
        return current_date + timedelta(days=1)
    elif weekday == 4:  # Friday -> Saturday (+1), Saturday is a work day
        return current_date + timedelta(days=1)
    elif weekday == 5:  # Saturday -> Next Monday (+2)
        return current_date + timedelta(days=2)
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
