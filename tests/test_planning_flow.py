"""
Unit tests for the full planning confirmation flow (Part 10.5).
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.whatsapp.parser import ParsedWhatsAppMessage
from app.whatsapp.client import WhatsAppClient
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.sheets.masters import MastersService
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE

EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)  # Miércoles -> Jueves (4-JU)

SUPERVISORS = [
    {"Telefono": "70000001", "Nombre": "Carlos Mendoza", "Sede": "SCZ", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()
    return PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        masters_service=MastersService(),
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets))
    )


def _msg(body, message_id="m1"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone="70000001", body=body)


@pytest.mark.asyncio
async def test_venta_directa_fields_are_na(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("venta directa"), eval_datetime=EVAL_DT)
    entry = svc.conversation_svc.get("70000001")
    draft = entry["payload"]["draft"]

    assert draft["modalidad"] == "VENTA DIRECTA"
    assert draft["vendedor_apoyo"] == "VENTA DIRECTA"
    assert draft["codigo_erp_vendedor"] == "N/A"
    assert draft["ruta_oficial"] == "N/A"
    assert draft["zona"] == "N/A"
    assert draft["codigo_ruta"] == "N/A"
    assert draft["dia"] == "N/A"


@pytest.mark.asyncio
async def test_oficina_fields_are_na(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina"), eval_datetime=EVAL_DT)
    entry = svc.conversation_svc.get("70000001")
    draft = entry["payload"]["draft"]

    assert draft["modalidad"] == "OFICINA"
    assert draft["vendedor_apoyo"] == "N/A"
    assert draft["ruta_oficial"] == "N/A"


@pytest.mark.asyncio
async def test_confirm_first_time_sets_es_cambio_false(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m2"), eval_datetime=EVAL_DT)

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1
    assert records[0]["Es_Cambio"] == "FALSE"
    assert records[0]["Estado"] == "REGISTRADO"

    entry = svc.conversation_svc.get("70000001")
    assert entry is None


@pytest.mark.asyncio
async def test_second_planning_same_day_updates_same_row(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m2"), eval_datetime=EVAL_DT)
    first_id = fake_sheets.get_all_records("PLANIFICACION_DIARIA")[0]["ID_Registro"]

    await svc.handle_message(_msg("venta directa", "m3"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m4"), eval_datetime=EVAL_DT)

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 1  # misma fila, no una nueva
    assert records[0]["ID_Registro"] == first_id
    assert records[0]["Es_Cambio"] == "TRUE"
    assert records[0]["Estado"] == "MODIFICADO"
    assert records[0]["Modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_cancel_clears_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("cancelar", "m2"), eval_datetime=EVAL_DT)

    entry = svc.conversation_svc.get("70000001")
    assert entry is None

    records = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(records) == 0


# --- summary adapted to the modality ---

from datetime import date
from app.business.planning_rules import build_confirmation_summary, build_confirmation_summary_update

_FECHA = date(2026, 9, 17)  # Jueves


def _plan(modalidad, **extra):
    plan = {
        "modalidad": modalidad, "vendedor_apoyo": "N/A", "codigo_erp_vendedor": "N/A",
        "ruta_oficial": "N/A", "zona": "N/A", "codigo_ruta": "N/A", "dia": "N/A",
        "fecha_trabajo": "2026-09-17", "sede": "SCZ", "supervisor": "Carlos Mendoza",
    }
    plan.update(extra)
    return plan


def test_oficina_summary_is_minimal():
    summary = build_confirmation_summary(_FECHA, "4-JU", _plan("OFICINA"))
    assert summary == (
        "📋 *CONFIRMA TU PLANIFICACIÓN*\n\n"
        "🏢 Modalidad: OFICINA\n"
        "📆 Fecha: 17/09/2026 (Jueves - 4-JU)\n"
        "🏢 Sede: SCZ\n"
        "👤 Supervisor: Carlos Mendoza\n\n"
        "¿Registrar?\n\n"
        "✅ CONFIRMAR\n"
        "❌ CORREGIR"
    )


def test_venta_directa_summary_is_minimal():
    summary = build_confirmation_summary(_FECHA, "4-JU", _plan("VENTA DIRECTA", vendedor_apoyo="VENTA DIRECTA"))
    assert "🏢 Modalidad: VENTA DIRECTA" in summary
    for hidden in ("Vendedor", "ERP", "Ruta", "Zona", "Código ruta", "N/A"):
        assert hidden not in summary


def test_acompanamiento_summary_is_full():
    plan = _plan("ACOMPAÑAMIENTO", vendedor_apoyo="VENDEDOR UNO", codigo_erp_vendedor="4364",
                 ruta_oficial="SC-RUTA-1", zona="N", codigo_ruta="R1")
    summary = build_confirmation_summary(_FECHA, "4-JU", plan)
    for shown in ("👤 Vendedor: VENDEDOR UNO", "🆔 ERP: 4364", "🗺️ Ruta: SC-RUTA-1",
                  "🧭 Zona: N", "🔑 Código ruta: R1", "Sede: SCZ", "Supervisor: Carlos Mendoza"):
        assert shown in summary
    assert "Modalidad" not in summary


def test_ruta_summary_with_seller():
    plan = _plan("RUTA", vendedor_apoyo="", vendedor_nombre="JEANNINE ARIANA CASTEDO VON BOECK",
                 ruta_oficial="SC-DTS-RUTA-75", zona="N", codigo_ruta="226")
    summary = build_confirmation_summary(_FECHA, "4-JU", plan)
    assert summary == (
        "📋 *CONFIRMA TU PLANIFICACIÓN*\n\n"
        "🚗 Modalidad: RUTA (cubres la ruta solo)\n"
        "🗺️ Ruta: SC-DTS-RUTA-75\n"
        "👤 JEANNINE ARIANA CASTEDO VON BOECK\n"
        "🔑 Código ruta: 226\n"
        "📆 Fecha: 17/09/2026 (Jueves - 4-JU)\n\n"
        "🏢 Sede: SCZ\n"
        "👤 Supervisor: Carlos Mendoza\n\n"
        "¿Registrar?\n\n"
        "✅ CONFIRMAR\n"
        "❌ CORREGIR"
    )


@pytest.mark.parametrize("seller", ["", "N/A", None])
def test_ruta_summary_without_seller_omits_the_line(seller):
    plan = _plan("RUTA", vendedor_apoyo="", vendedor_nombre=seller,
                 ruta_oficial="SC-DTS-RUTA-32", zona="N", codigo_ruta="400")
    summary = build_confirmation_summary(_FECHA, "4-JU", plan)
    assert "🗺️ Ruta: SC-DTS-RUTA-32\n🔑 Código ruta: 400" in summary
    assert "ERP" not in summary and "Zona" not in summary and "Vendedor" not in summary
    assert summary.count("👤") == 1  # only the supervisor


@pytest.mark.parametrize("modalidad", ["OFICINA", "VENTA DIRECTA", "ACOMPAÑAMIENTO", "RUTA"])
def test_update_summary_is_notice_plus_same_summary(modalidad):
    plan = _plan(modalidad, vendedor_nombre="X")
    update = build_confirmation_summary_update(_FECHA, "4-JU", plan)
    base = build_confirmation_summary(_FECHA, "4-JU", plan)
    assert update == f"⚠️ Vas a reemplazar tu planificación anterior.\n\n{base}"


@pytest.mark.asyncio
async def test_replacing_an_existing_planning_shows_replace_notice(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("oficina", "m1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("confirmar", "m2"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("venta directa", "m3"), eval_datetime=EVAL_DT)

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("⚠️ Vas a reemplazar tu planificación anterior.\n\n")
    assert "🏢 Modalidad: VENTA DIRECTA" in text


# --- CORREGIR shows the SAVED plan; identical plans are detected ---

from app.whatsapp.templates import (  # noqa: E402
    MSG_CANCELLED_NO_CHANGES,
    MSG_NO_PLAN_CANCEL_HINT,
    MSG_PLAN_ALREADY_ACTIVE,
    MSG_REGISTERED_OK,
    MSG_UPDATED_OK,
)

REPLACE_NOTICE = "Vas a reemplazar tu planificación anterior"


async def _say(svc, *bodies, start=1):
    for i, body in enumerate(bodies, start=start):
        await svc.handle_message(_msg(body, f"c{i}"), eval_datetime=EVAL_DT)


def _write_counter(fake_sheets):
    """Counts the writes (append/update) that reach PLANIFICACION_DIARIA (not the LOG_BOT audit rows)."""
    counter = {"writes": 0}
    for name in ("append_row", "update_row"):
        original = getattr(fake_sheets, name)

        def wrapped(*args, _original=original, **kwargs):
            if args[0] == "PLANIFICACION_DIARIA":
                counter["writes"] += 1
            return _original(*args, **kwargs)

        setattr(fake_sheets, name, wrapped)
    return counter


@pytest.mark.asyncio
async def test_corregir_with_saved_plan_shows_the_saved_plan_not_the_draft(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar")                 # saved plan: OFICINA
    await _say(svc, "venta directa", start=3)               # pending draft: VENTA DIRECTA

    await _say(svc, "corregir", start=4)

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("📋 Tu planificación actual es:")
    assert "🏢 Modalidad: OFICINA" in text                  # the saved one...
    assert "VENTA DIRECTA" not in text                      # ...not the draft
    assert "CONFIRMA TU PLANIFICACIÓN" not in text and "¿Registrar?" not in text
    assert "✍️ Envía la nueva planificación para reemplazarla." in text
    assert "CANCELAR* para dejarla como está." in text

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "VENTA DIRECTA"  # draft untouched

    await _say(svc, "confirmar", start=5)                   # the draft can still be confirmed
    assert mock_wa.sent_messages[-1]["text"] == MSG_UPDATED_OK
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA")[0]["Modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_corregir_without_saved_plan_says_there_is_none(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina")

    await _say(svc, "corregir", start=2)

    text = mock_wa.sent_messages[-1]["text"]
    assert text == f"{MSG_NO_PLAN_INFO.format(fecha='17/09/2026')}\n{MSG_NO_PLAN_CANCEL_HINT}"
    assert text.startswith("📋 No tienes una planificación registrada para el 17/09/2026.")
    assert text.endswith("O *CANCELAR* para descartar la planificación pendiente.")
    assert "CONFIRMA TU PLANIFICACIÓN" not in text and "Modalidad" not in text   # the draft is not shown again
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"


@pytest.mark.asyncio
async def test_an_escalation_flag_is_not_a_saved_plan_for_corregir(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.sheets_repo.mark_escalated("2026-09-17", "SCZ", "Carlos Mendoza")
    await _say(svc, "oficina", "corregir")

    assert "No tienes una planificación registrada" in mock_wa.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_corregir_then_cancelar_keeps_the_saved_plan(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar", "venta directa", "corregir", "cancelar")

    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA")[0]["Modalidad"] == "OFICINA"


@pytest.mark.asyncio
async def test_confirming_a_plan_identical_to_the_saved_one_writes_nothing(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina")                              # draft OFICINA pending...
    svc.sheets_repo.upsert("2026-09-17", "SCZ", "Carlos Mendoza", {  # ...and the same plan gets saved meanwhile
        "Modalidad": "OFICINA", "Vendedor_Apoyo": "N/A", "Codigo_ERP_Vendedor": "N/A",
        "Ruta_Oficial": "N/A", "Zona": "N/A", "Codigo_Ruta": "N/A", "DIA": "N/A",
    })
    before = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    writes = _write_counter(fake_sheets)

    await _say(svc, "confirmar", start=2)

    assert mock_wa.sent_messages[-1]["text"] == MSG_PLAN_ALREADY_ACTIVE
    assert writes["writes"] == 0
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == before
    assert svc.conversation_svc.get("70000001") is None
    log = [r for r in fake_sheets.get_all_records("LOG_BOT") if r["accion"] == "CONFIRM_PLANNING"]
    assert log[-1]["resultado"] == "NO_CHANGES"


@pytest.mark.asyncio
async def test_confirming_a_different_plan_updates_and_writes(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar")
    writes = _write_counter(fake_sheets)

    await _say(svc, "venta directa", "confirmar", start=3)

    assert mock_wa.sent_messages[-1]["text"] == MSG_UPDATED_OK
    assert writes["writes"] == 1
    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(rows) == 1 and rows[0]["Modalidad"] == "VENTA DIRECTA" and rows[0]["Es_Cambio"] == "TRUE"


@pytest.mark.asyncio
async def test_first_confirmation_is_still_a_registration(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await _say(svc, "oficina", "confirmar")

    assert mock_wa.sent_messages[-1]["text"] == MSG_REGISTERED_OK


@pytest.mark.asyncio
async def test_new_command_identical_to_the_saved_plan_does_not_ask_to_replace(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar")
    count = len(mock_wa.sent_messages)

    await _say(svc, "oficina", start=3)

    assert len(mock_wa.sent_messages) == count + 1
    assert mock_wa.sent_messages[-1]["text"] == MSG_PLAN_ALREADY_ACTIVE
    assert REPLACE_NOTICE not in mock_wa.sent_messages[-1]["text"]
    assert svc.conversation_svc.get("70000001") is None     # no AWAITING_CONFIRMATION


@pytest.mark.asyncio
async def test_new_command_different_from_the_saved_plan_asks_to_replace(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar")

    await _say(svc, "venta directa", start=3)

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("⚠️ Vas a reemplazar tu planificación anterior.")
    assert "🏢 Modalidad: VENTA DIRECTA" in text            # the summary of the NEW plan
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"


@pytest.mark.asyncio
async def test_new_command_with_no_saved_plan_has_no_replace_notice(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await _say(svc, "oficina")

    assert REPLACE_NOTICE not in mock_wa.sent_messages[-1]["text"]
    assert "CONFIRMA TU PLANIFICACIÓN" in mock_wa.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_new_command_while_awaiting_confirmation_replaces_the_draft(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await _say(svc, "oficina", "venta directa")             # no CORREGIR in between

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "VENTA DIRECTA"
    assert "🏢 Modalidad: VENTA DIRECTA" in mock_wa.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_new_command_identical_to_saved_discards_the_pending_draft(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar", "venta directa")     # draft pending over a saved OFICINA

    await _say(svc, "oficina", start=4)                          # back to exactly what is saved

    assert mock_wa.sent_messages[-1]["text"] == MSG_PLAN_ALREADY_ACTIVE
    assert svc.conversation_svc.get("70000001") is None


def test_same_planning_compares_trimmed_text_so_gspread_numbers_match():
    from app.sheets.planning_repository import same_planning

    saved = {"Estado": "REGISTRADO", "Modalidad": "ACOMPAÑAMIENTO", "Vendedor_Apoyo": "V UNO",
             "Codigo_ERP_Vendedor": 4364, "Ruta_Oficial": "R1", "Zona": "N", "Codigo_Ruta": 226, "DIA": "4-JU"}
    draft = {"Modalidad": "ACOMPAÑAMIENTO", "Vendedor_Apoyo": "V UNO", "Codigo_ERP_Vendedor": "4364",
             "Ruta_Oficial": "R1", "Zona": "N", "Codigo_Ruta": "226", "DIA": "4-JU"}

    assert same_planning(saved, draft) is True
    assert same_planning(saved, {**draft, "Codigo_Ruta": "227"}) is False
    assert same_planning(saved, {**draft, "Modalidad": "OFICINA"}) is False
    assert same_planning({**saved, "Estado": "PENDIENTE_ESCALADO"}, draft) is False  # a flag is not a plan
    assert same_planning(None, draft) is False


# --- CORREGIR with nothing pending (IDLE) ---

from app.whatsapp.templates import MSG_NO_PLAN_INFO  # noqa: E402


@pytest.mark.asyncio
async def test_idle_corregir_with_saved_plan_shows_it_and_stays_idle(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar")                 # saved; conversation back to IDLE
    assert svc.conversation_svc.get("70000001") is None
    count = len(mock_wa.sent_messages)

    await _say(svc, "corregir", start=3)

    assert len(mock_wa.sent_messages) == count + 1
    assert mock_wa.sent_messages[-1]["text"] == (
        "📋 Tu planificación actual es:\n\n"
        "🏢 Modalidad: OFICINA\n"
        "📆 Fecha: 17/09/2026 (Jueves - 4-JU)\n"
        "🏢 Sede: SCZ\n"
        "👤 Supervisor: Carlos Mendoza\n\n"
        "✍️ Envía la nueva planificación para reemplazarla."
    )
    assert "CANCELAR" not in mock_wa.sent_messages[-1]["text"]   # nothing pending to cancel
    assert svc.conversation_svc.get("70000001") is None          # still IDLE
    assert len(fake_sheets.get_all_records("PLANIFICACION_DIARIA")) == 1  # nothing written


@pytest.mark.asyncio
async def test_idle_corregir_without_plan_explains_how_to_register(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await _say(svc, "corregir")

    assert mock_wa.sent_messages[-1]["text"] == MSG_NO_PLAN_INFO.format(fecha="17/09/2026")
    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("📋 No tienes una planificación registrada para el 17/09/2026.")
    for command in ("código de un vendedor", "ruta", "venta directa", "oficina", "AYUDA"):
        assert command in text
    assert svc.conversation_svc.get("70000001") is None


@pytest.mark.asyncio
async def test_idle_corregir_treats_an_escalation_flag_as_no_plan(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.sheets_repo.mark_escalated("2026-09-17", "SCZ", "Carlos Mendoza")

    await _say(svc, "corregir")

    assert mock_wa.sent_messages[-1]["text"] == MSG_NO_PLAN_INFO.format(fecha="17/09/2026")


@pytest.mark.asyncio
async def test_new_command_after_idle_corregir_works_normally(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar", "corregir")

    await _say(svc, "venta directa", start=4)

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("⚠️ Vas a reemplazar tu planificación anterior.")
    assert "🏢 Modalidad: VENTA DIRECTA" in text
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"

    await _say(svc, "confirmar", start=5)
    assert mock_wa.sent_messages[-1]["text"] == MSG_UPDATED_OK


@pytest.mark.asyncio
async def test_idle_corregir_without_plan_then_register_works(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "corregir")

    await _say(svc, "oficina", "confirmar", start=2)

    assert mock_wa.sent_messages[-1]["text"] == MSG_REGISTERED_OK


@pytest.mark.asyncio
async def test_awaiting_confirmation_corregir_is_unchanged(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar", "venta directa", "corregir")

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("📋 Tu planificación actual es:")
    assert "O *CANCELAR* para dejarla como está." in text   # the hint IS there while a draft is pending
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"

    await _say(svc, "cancelar", "corregir", start=5)         # back to IDLE: now the IDLE answer
    assert "CANCELAR" not in mock_wa.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_unknown_messages_in_idle_with_a_saved_plan_stay_silent(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    await _say(svc, "oficina", "confirmar")
    count = len(mock_wa.sent_messages)

    await _say(svc, "hola buenas", "ok", start=3)

    assert len(mock_wa.sent_messages) == count   # the silence rule is untouched
