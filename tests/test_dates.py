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


def test_monday_before_cutoff():
    """Lunes 08:00 (<= 08:30) debe calcular el mismo lunes."""
    dt = datetime(2026, 9, 14, 8, 0, tzinfo=BOLIVIA_TZ)  # Lunes 14/09/2026
    work_date = calculate_work_date(dt, monday_cutoff="08:30")
    assert work_date == date(2026, 9, 14)


def test_monday_exact_cutoff():
    """Lunes exactamente 08:30:00 (<= 08:30) debe calcular el mismo lunes."""
    dt = datetime(2026, 9, 14, 8, 30, 0, tzinfo=BOLIVIA_TZ)
    work_date = calculate_work_date(dt, monday_cutoff="08:30")
    assert work_date == date(2026, 9, 14)


def test_monday_after_cutoff():
    """Lunes después de 08:30 (08:31) debe calcular el martes."""
    dt = datetime(2026, 9, 14, 8, 31, tzinfo=BOLIVIA_TZ)
    work_date = calculate_work_date(dt, monday_cutoff="08:30")
    assert work_date == date(2026, 9, 15)  # Martes


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


def test_saturday():
    """Sábado debe calcular el próximo lunes."""
    dt = datetime(2026, 9, 19, 11, 0, tzinfo=BOLIVIA_TZ)  # Sábado
    work_date = calculate_work_date(dt)
    assert work_date == date(2026, 9, 21)  # Lunes siguiente (+2 días)


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
