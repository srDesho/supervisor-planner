"""
Unit tests for SupervisorsRepository (SUPERVISORES sheet).
Columnas: WhatsApp_ID | Telefono | Nombre | Sede | Activo | Ultimo_Recordatorio
"""
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS

SEED_ROWS = [
    {
        "WhatsApp_ID": "88283556139076@lid",
        "Telefono": "69105312",
        "Nombre": "Julio Cesar",
        "Sede": "SCZ",
        "Activo": "TRUE",
        "Ultimo_Recordatorio": ""
    },
    {
        "WhatsApp_ID": "",
        "Telefono": "70000003",
        "Nombre": "Juan Perez",
        "Sede": "LPZ",
        "Activo": "FALSE",
        "Ultimo_Recordatorio": ""
    },
]


def _repo(fake_sheets):
    fake_sheets.seed_records("SUPERVISORES", _COLUMNS, SEED_ROWS)
    return SupervisorsRepository(client=fake_sheets)


def test_find_by_phone_matches_local_8_digit_number(fake_sheets):
    repo = _repo(fake_sheets)
    row = repo.find_by_phone("69105312")
    assert row is not None
    assert row["Nombre"] == "Julio Cesar"


def test_find_by_phone_matches_full_number_with_country_code(fake_sheets):
    repo = _repo(fake_sheets)
    row = repo.find_by_phone("59169105312")
    assert row is not None
    assert row["Nombre"] == "Julio Cesar"


def test_find_by_phone_returns_none_for_unknown_number(fake_sheets):
    repo = _repo(fake_sheets)
    assert repo.find_by_phone("70009999") is None


def test_update_last_reminder_persists_timestamp(fake_sheets):
    repo = _repo(fake_sheets)
    updated = repo.update_last_reminder("69105312", "2026-09-19 17:15:00")

    assert updated is not None
    assert updated["Ultimo_Recordatorio"] == "2026-09-19 17:15:00"

    row = repo.find_by_phone("69105312")
    assert row["Ultimo_Recordatorio"] == "2026-09-19 17:15:00"


def test_update_whatsapp_id_persists_chat_id(fake_sheets):
    repo = _repo(fake_sheets)
    updated = repo.update_whatsapp_id("70000003", "59170000003@c.us")

    assert updated is not None
    assert updated["WhatsApp_ID"] == "59170000003@c.us"

    row = repo.find_by_phone("70000003")
    assert row["WhatsApp_ID"] == "59170000003@c.us"
