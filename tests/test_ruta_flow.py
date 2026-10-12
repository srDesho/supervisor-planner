"""
Tests for the planning commands after REGISTRO was removed:
- parser evaluation order (VENTA DIRECTA before RUTA, code, etc.)
- RUTA flow (AWAITING_RUTA_CODE) reusing the seller-code validations
- authenticated supervisors never self-register; unknown phones stay silent
"""
import pytest
from datetime import datetime

from app.business.dates import BOLIVIA_TZ
from app.whatsapp.parser import ParsedWhatsAppMessage, extract_planning_intent
from app.whatsapp.client import WhatsAppClient
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.sheets.masters import MastersService
from app.services.planning_service import PlanningService
from app.services.supervisor_service import SupervisorService
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.whatsapp.templates import (
    MSG_HELP,
    MSG_RUTA_ASK_CODE,
    MSG_RUTA_CODE_INVALID,
    MSG_CANCELLED_NO_CHANGES,
    MSG_RUTA_CODE_NOT_FOUND,
    MSG_RUTA_LIST_OUT_OF_RANGE,
    MSG_RUTA_LIST_EMPTY,
    MSG_RUTA_LIST_BAD_PAGE,
    MSG_SELLER_CODE_NOT_FOUND,
    MSG_SELLER_WRONG_ZONE,
    MSG_SELLER_ALREADY_ASSIGNED,
)

# Miércoles 16:00 -> fecha operativa Jueves (4-JU)
EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)

SUPERVISORS = [
    {"Nombre": "Carlos Mendoza", "Telefono": "70000001", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Nombre": "Maria Suarez", "Telefono": "70000002", "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
    {"Nombre": "Inactivo", "Telefono": "70000003", "Sede": "SCZ", "Zona": "N", "Activo": "FALSE", "Ultimo_Recordatorio": ""},
]

MASTER_ROWS = [
    {"RUTA": "SC-RUTA-1", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR UNO", "CODIGO ERP": "4364", "CODIGO RUTA": "R1"},
    {"RUTA": "SC-RUTA-2", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R2"},
    {"RUTA": "SC-RUTA-3", "ZONA": "N", "DIA": "4-JU", "VENDEDOR": "VENDEDOR DOS", "CODIGO ERP": "4140", "CODIGO RUTA": "R3"},
    {"RUTA": "SC-RUTA-9", "ZONA": "S", "DIA": "4-JU", "VENDEDOR": "VENDEDOR SUR", "CODIGO ERP": "7777", "CODIGO RUTA": "R9"},
]


def _make_service(fake_sheets, mock_wa, master_rows=None):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()

    masters = MastersService()
    masters.update_cache("SCZ", master_rows if master_rows is not None else MASTER_ROWS)

    return PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        masters_service=masters,
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets))
    )


def _msg(body, phone="70000001", message_id="m1"):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone=phone, body=body)


# --- parser ---

@pytest.mark.parametrize("text,expected", [
    ("4521", "code_only"),
    ("  4521  ", "code_only"),
    ("RUTA", "ruta"),
    ("  ruta  ", "ruta"),
    ("Ruta", "ruta"),
    ("VENTA", "unknown"),
    ("venta", "unknown"),
    ("VENTA DIRECTA", "venta_directa"),
    ("venta   directa", "venta_directa"),
    ("  Venta Directa ", "venta_directa"),
    ("OFICINA", "oficina"),
    ("Oficína", "oficina"),
    ("ayuda", "help"),
    ("HELP", "help"),
    ("CONFIRMAR", "confirm"),
    ("corregir", "correct"),
    ("CANCELAR", "cancel"),
    ("ConfirMar", "confirm"),
    ("Confirrmar", "confirm"),
    ("confirma", "confirm"),
    ("Dale", "confirm"),
    ("Listo", "confirm"),
    ("Ok", "confirm"),
    ("okey", "confirm"),
    ("Sí", "confirm"),
    ("si", "confirm"),
    ("Cambiar", "correct"),
    ("cambia", "correct"),
    ("Editar", "correct"),
    ("edito", "correct"),
    ("Salir", "cancel"),
    ("Descartar", "cancel"),
    ("No", "cancel"),
    ("nop", "cancel"),
    ("cancela", "cancel"),
    ("REGISTRO", "unknown"),
    ("nota", "unknown"),
    ("silla", "unknown"),
    ("ventas", "unknown"),
    ("hola", "unknown"),
])
def test_intent_parsing(text, expected):
    assert extract_planning_intent(text)["type"] == expected


def test_code_intent_extracts_code():
    assert extract_planning_intent(" 4521 ")["codigo_erp"] == "4521"


# --- no more REGISTRO ---

@pytest.mark.asyncio
async def test_registro_is_just_an_unknown_message_for_authenticated_supervisor(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("REGISTRO"), eval_datetime=EVAL_DT)

    assert [m["text"] for m in mock_wa.sent_messages] == [MSG_HELP]
    assert all(r["accion"] != "SELF_REGISTER" for r in fake_sheets.get_all_records("LOG_BOT"))


@pytest.mark.asyncio
async def test_inactive_supervisor_is_silent(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA", phone="70000003"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages == []
    assert fake_sheets.get_all_records("LOG_BOT") == []


# --- RUTA flow ---

@pytest.mark.asyncio
async def test_ruta_asks_for_code_and_enters_awaiting_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA"), eval_datetime=EVAL_DT)

    assert [m["text"] for m in mock_wa.sent_messages] == [MSG_RUTA_ASK_CODE]
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_ruta_seller_code_proposes_ruta_plan_and_confirm_writes_sheet(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("ruta"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4364", message_id="m2"), eval_datetime=EVAL_DT)

    summary = mock_wa.sent_messages[-1]["text"]
    assert "CONFIRMA TU PLANIFICACIÓN" in summary
    assert "RUTA" in summary and "👤 VENDEDOR UNO" in summary
    assert "Vendedor:" not in summary

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "RUTA"
    assert entry["payload"]["draft"]["vendedor_apoyo"] == ""

    await svc.handle_message(_msg("CONFIRMAR", message_id="m3"), eval_datetime=EVAL_DT)

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(rows) == 1
    assert rows[0]["Modalidad"] == "RUTA"
    assert rows[0]["Vendedor_Apoyo"] == ""
    assert rows[0]["Codigo_ERP_Vendedor"] == "4364"
    assert rows[0]["Ruta_Oficial"] == "SC-RUTA-1"


@pytest.mark.asyncio
async def test_code_alone_still_means_acompanamiento(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("4364"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("CONFIRMAR", message_id="m2"), eval_datetime=EVAL_DT)

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert rows[0]["Modalidad"] == "ACOMPAÑAMIENTO"
    assert rows[0]["Vendedor_Apoyo"] == "VENDEDOR UNO"


@pytest.mark.asyncio
async def test_ruta_with_multiple_routes_goes_through_selection_keeping_modalidad(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4140", message_id="m2"), eval_datetime=EVAL_DT)
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_SELECTION"

    await svc.handle_message(_msg("2", message_id="m3"), eval_datetime=EVAL_DT)

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    assert entry["payload"]["draft"]["modalidad"] == "RUTA"
    assert entry["payload"]["draft"]["codigo_ruta"] == "R3"


@pytest.mark.asyncio
async def test_ruta_cancel_exits_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("CANCELAR", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None


@pytest.mark.asyncio
async def test_ruta_invalid_input_keeps_state(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("oficina", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_CODE_INVALID
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_ruta_unknown_code_keeps_state_for_retry(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("9999", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_CODE_NOT_FOUND
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_ruta_wrong_zone_is_rejected(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("RUTA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("7777", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_SELLER_WRONG_ZONE.format(
        codigo="7777", vendedor="VENDEDOR SUR", zona_vendedor="S"
    )
    records = fake_sheets.get_all_records("LOG_BOT")
    assert records[-1]["accion"] == "REJECTED_WRONG_ZONE"


@pytest.mark.asyncio
async def test_ruta_duplicate_seller_names_the_seller_not_na(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    # Maria registers RUTA on 4364 first (Vendedor_Apoyo is empty in the Sheet).
    await svc.handle_message(_msg("RUTA", phone="70000002"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4364", phone="70000002", message_id="m2"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("CONFIRMAR", phone="70000002", message_id="m3"), eval_datetime=EVAL_DT)

    # Carlos now tries the same seller.
    await svc.handle_message(_msg("RUTA", phone="70000001", message_id="m4"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("4364", phone="70000001", message_id="m5"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_SELLER_ALREADY_ASSIGNED.format(
        vendedor="VENDEDOR UNO", fecha="17/09/2026", otro_supervisor="Maria Suarez"
    )


@pytest.mark.asyncio
async def test_venta_directa_not_confused_with_ruta(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("VENTA DIRECTA"), eval_datetime=EVAL_DT)

    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"
    assert svc.conversation_svc.get("70000001")["payload"]["draft"]["modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_new_ruta_while_awaiting_confirmation_restarts_flow(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    await svc.handle_message(_msg("OFICINA"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("RUTA", message_id="m2"), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_ASK_CODE
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


# --- short synonyms only count as the WHOLE message ---

@pytest.mark.parametrize("text,expected", [
    ("no", "cancel"),
    (" No. ", "cancel"),
    ("salgo!", "cancel"),
    ("ok", "confirm"),
    ("Ok.", "confirm"),
    ("  sí  ", "confirm"),
    ("confirmo", "confirm"),
    ("cancelo", "cancel"),
    ("no, mejor mañana", "unknown"),
    ("no tengo ruta para hoy", "unknown"),
    ("ok gracias", "unknown"),
    ("si quieres", "unknown"),
    ("salgo a ruta", "unknown"),
    ("dale que si", "unknown"),
    ("listo para salir", "unknown"),
    ("no cancelar", "cancel"),  # long words still match anywhere
    ("quiero cancelar", "cancel"),
    ("confirmo el plan", "confirm"),
    ("quiero cambiar la ruta", "correct"),
])
def test_short_synonyms_need_whole_message(text, expected):
    assert extract_planning_intent(text)["type"] == expected


_DRAFT = {
    "modalidad": "OFICINA", "vendedor_apoyo": "N/A", "codigo_erp_vendedor": "N/A",
    "ruta_oficial": "N/A", "zona": "N/A", "codigo_ruta": "N/A", "dia": "N/A",
    "fecha_trabajo": "2026-09-17", "sede": "SCZ", "supervisor": "Carlos Mendoza",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["no tengo ruta para hoy", "ok gracias"])
async def test_sentences_do_not_cancel_or_confirm_a_pending_plan(fake_sheets, body):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    svc.conversation_svc.set("70000001", "AWAITING_CONFIRMATION", payload={"draft": dict(_DRAFT)})

    await svc.handle_message(_msg(body), eval_datetime=EVAL_DT)

    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []
    assert "pendiente de confirmación" in mock_wa.sent_messages[-1]["text"]


@pytest.mark.asyncio
async def test_lone_no_cancels_and_lone_ok_confirms(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)

    svc.conversation_svc.set("70000001", "AWAITING_CONFIRMATION", payload={"draft": dict(_DRAFT)})
    await svc.handle_message(_msg("no"), eval_datetime=EVAL_DT)
    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None

    svc.conversation_svc.set("70000001", "AWAITING_CONFIRMATION", payload={"draft": dict(_DRAFT)})
    await svc.handle_message(_msg("ok", message_id="m2"), eval_datetime=EVAL_DT)
    assert len(fake_sheets.get_all_records("PLANIFICACION_DIARIA")) == 1


# --- required scenarios with a pending plan (AWAITING_CONFIRMATION) ---

def _pending(svc):
    svc.conversation_svc.set("70000001", "AWAITING_CONFIRMATION", payload={"draft": dict(_DRAFT)})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["ok", "confirmo"])
async def test_lone_confirm_word_confirms_pending_plan(fake_sheets, body):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    _pending(svc)

    await svc.handle_message(_msg(body), eval_datetime=EVAL_DT)

    assert len(fake_sheets.get_all_records("PLANIFICACION_DIARIA")) == 1
    assert svc.conversation_svc.get("70000001") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["no", "cancelo", "quiero cancelar"])
async def test_cancel_words_cancel_pending_plan(fake_sheets, body):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    _pending(svc)

    await svc.handle_message(_msg(body), eval_datetime=EVAL_DT)

    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["ok gracias", "no, mejor mañana"])
async def test_short_word_inside_a_sentence_leaves_pending_plan_untouched(fake_sheets, body):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    _pending(svc)

    await svc.handle_message(_msg(body), eval_datetime=EVAL_DT)

    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_CONFIRMATION"
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []
    assert "pendiente de confirmación" in mock_wa.sent_messages[-1]["text"]


# --- RUTA: LISTA, route code, seller-vs-route priority ---

def _r(ruta, zona, dia, vendedor, erp, codigo):
    return {"RUTA": ruta, "ZONA": zona, "DIA": dia, "VENDEDOR": vendedor, "CODIGO ERP": erp, "CODIGO RUTA": codigo}


LIST_ROWS = [
    _r("SC-DTS-RUTA-75", "N", "4-JU", "JEANNINE ARIANA CASTEDO VON BOECK", "5001", "226"),
    _r("SC-DTS-RUTA-24", "N", "4-JU", "DANVER DANIEL RAMIREZ RODRIGUEZ", "5002", "175"),
    _r("SC-DTS-RUTA-126", "N", "4-JU", "JEANNINE ARIANA CASTEDO VON BOECK", "5001", "105"),
    _r("SC-DTS-RUTA-134", "N", "4-JU", "JEANNINE ARIANA CASTEDO VON BOECK", "5001", "1055"),
    _r("SC-DTS-RUTA-32", "N", "4-JU", "", "", "400"),                       # route without seller
    _r("SC-DTS-RUTA-77", "N", "4-JU", "VENDEDOR DOBLE", "700", "800"),      # seller code 700 ...
    _r("SC-DTS-RUTA-78", "N", "4-JU", "OTRO VENDEDOR", "900", "700"),       # ... is also a route code
    _r("SC-DTS-MERC-26-DE-ABRIL", "N", "4-JU", "VENDEDOR MERCADO", "6000", "300"),  # market: excluded
    _r("SC-DTS-RUTA-90", "S", "4-JU", "VENDEDOR SUR", "7777", "500"),       # other zone
    _r("SC-DTS-RUTA-91", "N", "5-VI", "VENDEDOR VIERNES", "8000", "600"),   # other day
]
# Thursday, zone N, no MERC, sorted by CODIGO RUTA (numeric):
# 105, 175, 226, 400, 700, 800, 1055
LIST_EXPECTED = ["SC-DTS-RUTA-126", "SC-DTS-RUTA-24", "SC-DTS-RUTA-75", "SC-DTS-RUTA-32",
                 "SC-DTS-RUTA-78", "SC-DTS-RUTA-77", "SC-DTS-RUTA-134"]


def _list_service(fake_sheets, mock_wa, rows=None):
    return _make_service(fake_sheets, mock_wa, master_rows=rows if rows is not None else LIST_ROWS)


async def _say(svc, *bodies):
    for i, body in enumerate(bodies):
        await svc.handle_message(_msg(body, message_id=f"x{i}"), eval_datetime=EVAL_DT)


def _draft(svc):
    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_CONFIRMATION"
    return entry["payload"]["draft"]


def test_masters_routes_by_zone_and_day_filters_and_sorts():
    masters = MastersService()
    masters.update_cache("SCZ", LIST_ROWS)

    routes = masters.get_routes_by_zone_and_day("SCZ", "n", "4-JU")  # zone is case-insensitive

    assert [r["RUTA"] for r in routes] == LIST_EXPECTED
    assert [r["CODIGO RUTA"] for r in routes] == ["105", "175", "226", "400", "700", "800", "1055"]  # numeric, not string order


def test_masters_route_by_code_uses_same_filters():
    masters = MastersService()
    masters.update_cache("SCZ", LIST_ROWS)

    assert masters.get_route_by_code("SCZ", "N", "4-JU", "226")["RUTA"] == "SC-DTS-RUTA-75"
    assert masters.get_route_by_code("SCZ", "N", "4-JU", "300") is None   # MERC excluded
    assert masters.get_route_by_code("SCZ", "N", "4-JU", "500") is None   # other zone
    assert masters.get_route_by_code("SCZ", "N", "4-JU", "600") is None   # other day


@pytest.mark.asyncio
async def test_ruta_asks_for_vendor_route_or_lista(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA")

    text = mock_wa.sent_messages[-1]["text"]
    assert text == MSG_RUTA_ASK_CODE
    assert "LISTA" in text and "código del vendedor" in text and "código de la ruta" in text


@pytest.mark.asyncio
async def test_ruta_seller_code_gives_ruta_plan_with_that_sellers_route(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "5002", "CONFIRMAR")

    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert len(rows) == 1
    assert rows[0]["Modalidad"] == "RUTA"
    assert rows[0]["Vendedor_Apoyo"] == ""
    assert rows[0]["Codigo_ERP_Vendedor"] == "5002"
    assert rows[0]["Ruta_Oficial"] == "SC-DTS-RUTA-24"
    assert rows[0]["Zona"] == "N"
    assert rows[0]["Codigo_Ruta"] == "175"
    assert rows[0]["DIA"] == "4-JU"


@pytest.mark.asyncio
async def test_ruta_lista_shows_only_zone_and_day_routes_sorted_without_merc(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "LISTA")

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("📋 *RUTAS DISPONIBLES — JUEVES 17/09/2026*")
    lines = [l for l in text.splitlines() if l[:1].isdigit()]
    assert lines == [
        "1. SC-DTS-RUTA-126 · JEANNINE ARIANA CASTEDO VON BOECK · 105",
        "2. SC-DTS-RUTA-24 · DANVER DANIEL RAMIREZ RODRIGUEZ · 175",
        "3. SC-DTS-RUTA-75 · JEANNINE ARIANA CASTEDO VON BOECK · 226",
        "4. SC-DTS-RUTA-32 · (sin vendedor) · 400",
        "5. SC-DTS-RUTA-78 · OTRO VENDEDOR · 700",
        "6. SC-DTS-RUTA-77 · VENDEDOR DOBLE · 800",
        "7. SC-DTS-RUTA-134 · JEANNINE ARIANA CASTEDO VON BOECK · 1055",
    ]
    for hidden in ("MERC", "RUTA-90", "RUTA-91", "Zona", "ERP"):
        assert hidden not in text
    assert "CANCELAR" in text

    entry = svc.conversation_svc.get("70000001")
    assert entry["state"] == "AWAITING_RUTA_CODE"
    assert entry["payload"]["list_shown"] is True


@pytest.mark.asyncio
async def test_ruta_lista_then_number_picks_that_position(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "LISTA", "3")

    summary = mock_wa.sent_messages[-1]["text"]
    assert "🚗 Modalidad: RUTA (cubres la ruta solo)" in summary
    assert "🗺️ Ruta: SC-DTS-RUTA-75" in summary
    assert "👤 JEANNINE ARIANA CASTEDO VON BOECK" in summary
    assert "🔑 Código ruta: 226" in summary
    assert "ERP" not in summary and "Zona" not in summary

    await _say(svc, "CONFIRMAR")
    rows = fake_sheets.get_all_records("PLANIFICACION_DIARIA")
    assert rows[0]["Modalidad"] == "RUTA"
    assert rows[0]["Vendedor_Apoyo"] == ""
    assert rows[0]["Codigo_ERP_Vendedor"] == "N/A"
    assert rows[0]["Ruta_Oficial"] == "SC-DTS-RUTA-75"
    assert rows[0]["Zona"] == "N"
    assert rows[0]["Codigo_Ruta"] == "226"
    assert rows[0]["DIA"] == "4-JU"


@pytest.mark.asyncio
async def test_ruta_lista_route_without_seller_omits_seller_line(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "LISTA", "4")

    summary = mock_wa.sent_messages[-1]["text"]
    assert "🗺️ Ruta: SC-DTS-RUTA-32\n🔑 Código ruta: 400" in summary
    assert "(sin vendedor)" not in summary
    assert _draft(svc)["vendedor_apoyo"] == ""


@pytest.mark.asyncio
async def test_ruta_lista_number_out_of_range(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "LISTA", "99")

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_LIST_OUT_OF_RANGE.format(total=7)
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"

    await _say(svc, "0")
    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_LIST_OUT_OF_RANGE.format(total=7)


@pytest.mark.asyncio
async def test_ruta_lista_then_long_code_is_still_a_code(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "LISTA", "5002")

    assert _draft(svc)["ruta_oficial"] == "SC-DTS-RUTA-24"


@pytest.mark.asyncio
async def test_ruta_direct_route_code(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "105")

    draft = _draft(svc)
    assert draft["modalidad"] == "RUTA"
    assert draft["ruta_oficial"] == "SC-DTS-RUTA-126"
    assert draft["codigo_ruta"] == "105"
    assert draft["codigo_erp_vendedor"] == "N/A"
    assert draft["vendedor_apoyo"] == ""


@pytest.mark.asyncio
async def test_ruta_code_matching_seller_and_route_prefers_seller(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "700")  # seller 700 (route SC-DTS-RUTA-77) vs route code 700 (SC-DTS-RUTA-78)

    draft = _draft(svc)
    assert draft["ruta_oficial"] == "SC-DTS-RUTA-77"
    assert draft["codigo_erp_vendedor"] == "700"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["500", "300", "600"])  # other zone route / MERC / other day
async def test_ruta_route_code_outside_zone_day_or_market_is_not_found(fake_sheets, code):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", code)

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_CODE_NOT_FOUND
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_ruta_cancel_and_lista_cancel(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "CANCELAR")
    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None

    await _say(svc, "RUTA", "LISTA", "CANCELAR")
    assert mock_wa.sent_messages[-1]["text"] == MSG_CANCELLED_NO_CHANGES
    assert svc.conversation_svc.get("70000001") is None
    assert fake_sheets.get_all_records("PLANIFICACION_DIARIA") == []


@pytest.mark.asyncio
async def test_ruta_invalid_input_message(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "quiero la ruta norte")

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_CODE_INVALID
    assert "LISTA" in MSG_RUTA_CODE_INVALID and "CANCELAR" in MSG_RUTA_CODE_INVALID
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_ruta_lista_with_no_routes_for_the_day(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa, rows=[_r("SC-DTS-RUTA-91", "N", "5-VI", "V", "1", "600")])

    await _say(svc, "RUTA", "LISTA")

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_LIST_EMPTY.format(dia="17/09/2026 (4-JU)")
    assert svc.conversation_svc.get("70000001")["state"] == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_ruta_lista_is_paginated_beyond_25_routes(fake_sheets):
    mock_wa = WhatsAppClient()
    rows = [_r(f"SC-DTS-RUTA-{n}", "N", "4-JU", f"VEND {n}", str(2000 + n), str(100 + n)) for n in range(1, 31)]
    svc = _list_service(fake_sheets, mock_wa, rows=rows)

    await _say(svc, "RUTA", "LISTA")
    page1 = mock_wa.sent_messages[-1]["text"]
    assert "25. SC-DTS-RUTA-25" in page1 and "26." not in page1
    assert "Página 1 de 2" in page1 and "LISTA 2" in page1

    await _say(svc, "LISTA 2")
    page2 = mock_wa.sent_messages[-1]["text"]
    assert "26. SC-DTS-RUTA-26" in page2 and "30. SC-DTS-RUTA-30" in page2 and "25." not in page2

    await _say(svc, "27")
    assert _draft(svc)["ruta_oficial"] == "SC-DTS-RUTA-27"


@pytest.mark.asyncio
async def test_ruta_lista_bad_page(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "RUTA", "LISTA 5")

    assert mock_wa.sent_messages[-1]["text"] == MSG_RUTA_LIST_BAD_PAGE.format(pages=1)


@pytest.mark.asyncio
async def test_lista_outside_ruta_flow_is_not_a_command(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "LISTA")

    assert mock_wa.sent_messages[-1]["text"] == MSG_HELP
    assert svc.conversation_svc.get("70000001") is None


@pytest.mark.asyncio
async def test_old_venta_command_no_longer_starts_a_flow(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "VENTA")

    assert mock_wa.sent_messages[-1]["text"] == MSG_HELP
    assert svc.conversation_svc.get("70000001") is None


@pytest.mark.asyncio
async def test_other_commands_still_work(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)

    await _say(svc, "OFICINA")
    assert _draft(svc)["modalidad"] == "OFICINA"
    await _say(svc, "VENTA DIRECTA")
    assert _draft(svc)["modalidad"] == "VENTA DIRECTA"
    await _say(svc, "5002")
    assert _draft(svc)["modalidad"] == "ACOMPAÑAMIENTO"
    assert _draft(svc)["vendedor_apoyo"] == "DANVER DANIEL RAMIREZ RODRIGUEZ"


@pytest.mark.asyncio
async def test_ruta_lista_prints_seller_exactly_as_in_master(fake_sheets):
    mock_wa = WhatsAppClient()
    rows = [
        _r("SC-DTS-RUTA-32", "N", "4-JU", "VENDEDOR 10", "1010", "400"),
        _r("SC-DTS-RUTA-33", "N", "4-JU", "N/A", "1011", "401"),
        _r("SC-DTS-RUTA-34", "N", "4-JU", "", "", "402"),
    ]
    svc = _list_service(fake_sheets, mock_wa, rows=rows)

    await _say(svc, "RUTA", "LISTA")

    lines = [l for l in mock_wa.sent_messages[-1]["text"].splitlines() if l[:1].isdigit()]
    assert lines == [
        "1. SC-DTS-RUTA-32 · VENDEDOR 10 · 400",
        "2. SC-DTS-RUTA-33 · N/A · 401",
        "3. SC-DTS-RUTA-34 · (sin vendedor) · 402",
    ]


@pytest.mark.asyncio
async def test_corregir_shows_the_saved_ruta_plan_with_the_sellers_name(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)
    await _say(svc, "RUTA", "LISTA", "3", "CONFIRMAR")          # saved: RUTA SC-DTS-RUTA-75
    await _say(svc, "OFICINA")                                    # a different draft is pending

    await svc.handle_message(_msg("corregir", message_id="z1"), eval_datetime=EVAL_DT)

    text = mock_wa.sent_messages[-1]["text"]
    assert text.startswith("📋 Tu planificación actual es:")
    assert "🚗 Modalidad: RUTA (cubres la ruta solo)" in text
    assert "🗺️ Ruta: SC-DTS-RUTA-75" in text
    assert "👤 JEANNINE ARIANA CASTEDO VON BOECK" in text      # looked up in the masters by route code
    assert "🔑 Código ruta: 226" in text
    assert "OFICINA" not in text


@pytest.mark.asyncio
async def test_same_ruta_chosen_again_is_reported_as_already_active(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _list_service(fake_sheets, mock_wa)
    await _say(svc, "RUTA", "5002", "CONFIRMAR")

    await svc.handle_message(_msg("RUTA", message_id="y1"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("175", message_id="y2"), eval_datetime=EVAL_DT)  # by route code: SC-DTS-RUTA-24 / ERP "N/A"

    # Picked by route code the plan differs from the one saved by seller code (ERP N/A vs 5002): replace notice.
    assert mock_wa.sent_messages[-1]["text"].startswith("⚠️ Vas a reemplazar")

    await svc.handle_message(_msg("CONFIRMAR", message_id="y3"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("RUTA", message_id="y4"), eval_datetime=EVAL_DT)
    await svc.handle_message(_msg("175", message_id="y5"), eval_datetime=EVAL_DT)
    assert mock_wa.sent_messages[-1]["text"] == "✅ Esa planificación ya está activa. No hay cambios."
