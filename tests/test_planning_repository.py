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


def test_read_active_index_matches_find_active_with_a_single_read(fake_sheets):
    repo = _repo(fake_sheets)
    repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})
    repo.upsert("2026-09-18", "SCZ", "Maria Suarez", {"Modalidad": "OFICINA"})
    repo.cancel("2026-09-18", "SCZ", "Maria Suarez")
    repo.mark_escalated("2026-09-18", "CBBA", "Juan Perez")

    reads = []
    original = fake_sheets.get_all_records
    fake_sheets.get_all_records = lambda name: (reads.append(name), original(name))[1]

    index = repo.read_active_index()

    assert len(reads) == 1
    assert set(index) == {
        ("2026-09-18", "SCZ", "Carlos Mendoza"),   # active planning
        ("2026-09-18", "CBBA", "Juan Perez"),       # escalation flag counts as an active row
    }                                               # the cancelled one is excluded
    for key in index:
        expected = repo.find_active(*key)
        assert index[key]["ID_Registro"] == expected["ID_Registro"]
        assert index[key]["__row_index"] == expected["__row_index"]


def test_upsert_skip_if_unchanged_writes_nothing_for_identical_content(fake_sheets):
    repo = _repo(fake_sheets)
    content = {"Modalidad": "OFICINA", "Vendedor_Apoyo": "N/A", "Codigo_ERP_Vendedor": "N/A",
               "Ruta_Oficial": "N/A", "Zona": "N/A", "Codigo_Ruta": "N/A", "DIA": "N/A"}
    first = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", content)
    before = fake_sheets.get_all_records("PLANIFICACION_DIARIA")

    again = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {**content, "ID_Mensaje_WA": "other"},
                        skip_if_unchanged=True)

    assert again["__unchanged"] is True
    assert again["ID_Registro"] == first["ID_Registro"]
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == before   # not even Es_Cambio changed


def test_upsert_skip_if_unchanged_still_updates_when_content_differs(fake_sheets):
    repo = _repo(fake_sheets)
    repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})

    result = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {"Modalidad": "VENTA DIRECTA"},
                         skip_if_unchanged=True)

    assert "__unchanged" not in result
    assert result["Es_Cambio"] == "TRUE" and result["Modalidad"] == "VENTA DIRECTA"


def test_upsert_default_still_rewrites_identical_content(fake_sheets):
    repo = _repo(fake_sheets)
    repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})

    result = repo.upsert("2026-09-18", "SCZ", "Carlos Mendoza", {"Modalidad": "OFICINA"})

    assert result["Es_Cambio"] == "TRUE"   # unchanged behavior for callers that don't opt in
