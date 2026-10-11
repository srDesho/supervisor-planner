"""
Unit tests for GoogleSheetsPlanningRepository (PLANIFICACION_DIARIA sheet):
upsert (insert then update), cancel, and find_active.
"""
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS


def _repo(fake_sheets):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", _COLUMNS)
    return GoogleSheetsPlanningRepository(client=fake_sheets)


def test_upsert_first_time_inserts_with_es_cambio_false(fake_sheets):
    repo = _repo(fake_sheets)

    result = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {
        "Modalidad": "ACOMPAÑAMIENTO",
        "Vendedor_Apoyo": "SELLER_ALPHA",
        "Ruta_Oficial": "ROUTE-001"
    })

    assert result["Es_Cambio"] == "FALSE"
    assert result["Estado"] == "REGISTRADO"
    assert result["ID_Registro"]

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1


def test_upsert_second_time_updates_same_row_with_es_cambio_true(fake_sheets):
    repo = _repo(fake_sheets)

    first = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {
        "Modalidad": "ACOMPAÑAMIENTO",
        "Vendedor_Apoyo": "SELLER_ALPHA",
        "Ruta_Oficial": "ROUTE-001"
    })

    second = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {
        "Modalidad": "ACOMPAÑAMIENTO",
        "Vendedor_Apoyo": "SELLER_GAMMA",
        "Ruta_Oficial": "ROUTE-002"
    })

    assert second["Es_Cambio"] == "TRUE"
    assert second["Estado"] == "MODIFICADO"
    assert second["ID_Registro"] == first["ID_Registro"]
    assert second["Vendedor_Apoyo"] == "SELLER_GAMMA"

    # Never two active rows for the same logical key.
    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1


def test_cancel_marks_cancelado_without_deleting_row(fake_sheets):
    repo = _repo(fake_sheets)
    repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {
        "Modalidad": "OFICINA"
    })

    cancelled = repo.cancel("2026-09-18", "SCZ", "Carlos Mendoza")

    assert cancelled is not None
    assert cancelled["Estado"] == "CANCELADO"

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1
    assert records[0]["Estado"] == "CANCELADO"


def test_find_active_excludes_cancelled_rows(fake_sheets):
    repo = _repo(fake_sheets)
    repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})
    repo.cancel("2026-09-18", "SCZ", "Carlos Mendoza")

    active = repo.find_active("2026-09-18", "SCZ", "Carlos Mendoza")

    assert active is None


def test_find_active_returns_none_when_no_planning_exists(fake_sheets):
    repo = _repo(fake_sheets)
    assert repo.find_active("2026-09-18", "SCZ", "Nadie") is None
