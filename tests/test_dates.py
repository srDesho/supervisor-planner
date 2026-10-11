"""
Unit tests for operational date and weekday calculations (SPEC.md Sections 6, 7, 8).
"""
import pytest
from datetime import datetime, date
from zoneinfo import ZoneInfo

from app.business.dates import (
    calculate_work_date,
    get_weekday_code,
    BOLIVIA_TZ
)


def test_monday_am_targets_same_monday():
    """Lunes antes del corte (15:00) calcula el mismo lunes (catch-up AM)."""
    dt = datetime(2026, 9, 14, 9, 0, tzinfo=BOLIVIA_TZ)  # Lunes 14/09/2026
    assert calculate_work_date(dt, monday_cutoff="15:00") == date(2026, 9, 14)


def test_monday_just_before_cutoff():
    dt = datetime(2026, 9, 14, 14, 59, tzinfo=BOLIVIA_TZ)
    assert calculate_work_date(dt, monday_cutoff="15:00") == date(2026, 9, 14)


def test_monday_exact_cutoff_targets_tuesday():
    """Lunes a las 15:00 en punto ya planifica el martes."""
    dt = datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ)
    assert calculate_work_date(dt, monday_cutoff="15:00") == date(2026, 9, 15)


def test_monday_pm_targets_tuesday():
    dt = datetime(2026, 9, 14, 19, 0, tzinfo=BOLIVIA_TZ)
    assert calculate_work_date(dt) == date(2026, 9, 15)


def test_monday_cutoff_defaults_to_setting():
    """Sin monday_cutoff explícito se usa MONDAY_PM_WINDOW_START."""
    assert calculate_work_date(datetime(2026, 9, 14, 14, 0, tzinfo=BOLIVIA_TZ)) == date(2026, 9, 14)
    assert calculate_work_date(datetime(2026, 9, 14, 16, 0, tzinfo=BOLIVIA_TZ)) == date(2026, 9, 15)


def test_tuesday():
    """Martes a cualquier hora debe calcular el miércoles."""
    dt = datetime(2026, 9, 15, 14, 0, tzinfo=BOLIVIA_TZ)  # Martes
    work_date = calculate_work_date(dt)
    assert work_date == date(2026, 9, 16)  # Miércoles


def test_wednesday():
    """Miércoles debe calcular el jueves."""
    dt = datetime(2026, 9, 16, 17, 30, tzinfo=BOLIVIA_TZ)  # Miércoles
    work_date = calculate_work_date(dt)
    assert work_date == date(2026, 9, 17)  # Jueves


def test_thursday():
    """Jueves debe calcular el viernes."""
    dt = datetime(2026, 9, 17, 10, 0, tzinfo=BOLIVIA_TZ)  # Jueves
    work_date = calculate_work_date(dt)
    assert work_date == date(2026, 9, 18)  # Viernes


def test_friday():
    """Viernes debe calcular el sábado (Company trabaja de lunes a sábado)."""
    dt = datetime(2026, 9, 18, 16, 0, tzinfo=BOLIVIA_TZ)  # Viernes
    work_date = calculate_work_date(dt)
    assert work_date == date(2026, 9, 19)  # Sábado (+1 día)


def test_saturday_am_targets_same_saturday():
    """Sábado antes de las 12:00 calcula el mismo sábado."""
    dt = datetime(2026, 9, 19, 11, 0, tzinfo=BOLIVIA_TZ)  # Sábado
    assert calculate_work_date(dt) == date(2026, 9, 19)


def test_saturday_from_noon_targets_monday():
    """Sábado desde las 12:00 calcula el próximo lunes."""
    dt = datetime(2026, 9, 19, 12, 0, tzinfo=BOLIVIA_TZ)
    assert calculate_work_date(dt) == date(2026, 9, 21)  # Lunes siguiente (+2 días)


def test_sunday():
    """Domingo debe calcular el próximo lunes."""
    dt = datetime(2026, 9, 20, 20, 0, tzinfo=BOLIVIA_TZ)  # Domingo
    work_date = calculate_work_date(dt)
    assert work_date == date(2026, 9, 21)  # Lunes siguiente (+1 día)


def test_get_weekday_codes():
    """Verifica la generación de códigos exactos 1-LU a 6-SA."""
    assert get_weekday_code(date(2026, 9, 14)) == "1-LU"  # Lunes
    assert get_weekday_code(date(2026, 9, 15)) == "2-MA"  # Martes
    assert get_weekday_code(date(2026, 9, 16)) == "3-MI"  # Miércoles
    assert get_weekday_code(date(2026, 9, 17)) == "4-JU"  # Jueves
    assert get_weekday_code(date(2026, 9, 18)) == "5-VI"  # Viernes
    assert get_weekday_code(date(2026, 9, 19)) == "6-SA"  # Sábado


def test_sunday_raises_error():
    """Domingo debe generar ValueError al solicitar código de ruta del maestro."""
    with pytest.raises(ValueError, match="no es un día de ruta comercial válido"):
        get_weekday_code(date(2026, 9, 20))  # Domingo
