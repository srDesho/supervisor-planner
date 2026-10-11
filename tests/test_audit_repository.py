"""
Unit tests for AuditRepository (LOG_BOT sheet).
"""
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS


def test_ensure_sheet_creates_missing_worksheet(fake_sheets):
    repo = AuditRepository(client=fake_sheets)

    already_existed = repo.ensure_sheet()

    assert already_existed is False
    assert fake_sheets.worksheet_exists("LOG_BOT") is True
    assert fake_sheets._headers["LOG_BOT"] == LOG_BOT_COLUMNS


def test_ensure_sheet_detects_existing_worksheet(fake_sheets):
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    repo = AuditRepository(client=fake_sheets)

    already_existed = repo.ensure_sheet()

    assert already_existed is True


def test_append_log_writes_row_with_correct_columns(fake_sheets):
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    repo = AuditRepository(client=fake_sheets)

    repo.append_log({
        "telefono_resuelto": "69105312",
        "whatsapp_id": "88283556139076@lid",
        "nombre": "Julio Cesar",
        "sede": "SCZ",
        "wa_msg_id": "msg_001",
        "mensaje_original": "PLANIFICACION...",
        "intencion": "NEW_PLANNING",
        "estado_antes": None,
        "estado_despues": "REGISTRADO",
        "accion": "CONFIRM_PLANNING",
        "resultado": "SUCCESS",
        "error": None,
        "detalles": "Sheet row id: abc-123"
    })

    records = fake_sheets.get_all_records("LOG_BOT")
    assert len(records) == 1
    row = records[0]
    assert row["telefono_resuelto"] == "69105312"
    assert row["whatsapp_id"] == "88283556139076@lid"
    assert row["accion"] == "CONFIRM_PLANNING"
    assert row["resultado"] == "SUCCESS"
    assert row["timestamp"]  # auto-filled
