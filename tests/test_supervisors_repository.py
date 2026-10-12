"""
Unit tests for SupervisorsRepository (SUPERVISORES sheet).
Columnas: Nombre | Telefono | Sede | Zona | Activo | Ultimo_Recordatorio
"""
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS

SEED_ROWS = [
    {
        "Telefono": "69105312",
        "Nombre": "Julio Cesar",
        "Sede": "SCZ",
        "Activo": "TRUE",
        "Ultimo_Recordatorio": ""
    },
    {
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


def test_columns_layout_has_no_whatsapp_id():
    assert _COLUMNS == ["Nombre", "Telefono", "Sede", "Zona", "Activo", "Ultimo_Recordatorio"]


def test_update_last_reminders_writes_only_that_column_with_one_batch(fake_sheets):
    repo = _repo(fake_sheets)
    fake_sheets.batch_calls = 0
    before = fake_sheets.get_all_records("SUPERVISORES")

    written = repo.update_last_reminders({
        "69105312": "2026-09-19 17:15:00",
        "59170000003": "2026-09-19 17:15:00",   # phones are matched after normalization
    })

    assert written == 2
    assert fake_sheets.batch_calls == 1
    after = fake_sheets.get_all_records("SUPERVISORES")
    assert [r["Ultimo_Recordatorio"] for r in after] == ["2026-09-19 17:15:00"] * 2
    for old, new in zip(before, after):  # nothing else changed
        assert {k: v for k, v in new.items() if k != "Ultimo_Recordatorio"} == \
               {k: v for k, v in old.items() if k != "Ultimo_Recordatorio"}


def test_update_last_reminders_with_nothing_does_not_touch_the_sheet(fake_sheets):
    repo = _repo(fake_sheets)
    fake_sheets.batch_calls = 0

    assert repo.update_last_reminders({}) == 0
    assert repo.update_last_reminders({"79999999": "2026-09-19 17:15:00"}) == 0  # unknown phone
    assert fake_sheets.batch_calls == 0


def test_stamp_in_cache_applies_immediately_without_writing(fake_sheets):
    repo = _repo(fake_sheets)
    repo.read_all()
    fake_sheets.batch_calls = 0

    repo.stamp_last_reminder_in_cache("69105312", "2026-09-19 17:15:00")

    assert repo.find_by_phone("69105312")["Ultimo_Recordatorio"] == "2026-09-19 17:15:00"
    assert fake_sheets.get_all_records("SUPERVISORES")[0]["Ultimo_Recordatorio"] == ""
    assert fake_sheets.batch_calls == 0
