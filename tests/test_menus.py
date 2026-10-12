"""
Numbered menus (an additive layer: every text command keeps working).

Menu 1 main, Menu 2 RUTA, Menu 3 confirmation, Menu 4 after CORREGIR, Menu 5 reminder.
A number only means something while the menu that offered it is what the bot
last said (conversation state), and ONLY an exact single digit is a menu option.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.business.dates import BOLIVIA_TZ
from app.core import locks
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService, _STORE
from app.services.planning_service import PlanningService
from app.services.reminder_service import ReminderService
from app.services.supervisor_service import SupervisorService
from app.sheets.audit_repository import AuditRepository, LOG_BOT_COLUMNS
from app.sheets.masters import MastersService
from app.sheets.planning_repository import GoogleSheetsPlanningRepository, _COLUMNS as PLANNING_COLUMNS
from app.sheets.supervisors_repository import SupervisorsRepository, _COLUMNS as SUPERVISORS_COLUMNS
from app.whatsapp.client import WhatsAppClient
from app.whatsapp.parser import ParsedWhatsAppMessage, extract_ruta_input, parse_menu_choice
from app.whatsapp.templates import (
    MSG_ASK_ROUTE_CODE,
    MSG_ASK_SELLER_CODE,
    MSG_CANCELLED_NO_CHANGES,
    MSG_LIST_PICK_INVALID,
    MSG_KEEP_PLAN_OK,
    MSG_MAIN_MENU,
    MSG_MAIN_MENU_COMMANDS_HINT,
    MSG_MAIN_MENU_KEEP,
    MSG_NOTHING_PENDING,
    MSG_NO_PLAN_INFO,
    MSG_REGISTERED_OK,
    MSG_REMINDER_AWAITING_CONFIRMATION,
    MSG_REMINDER_MENU,
    MSG_ROUTE_CODE_INVALID,
    MSG_ROUTE_CODE_NOT_FOUND,
    MSG_RUTA_MENU,
    MSG_SELLER_CODE_INVALID,
    MSG_SELLER_CODE_NOT_FOUND,
)

# Miércoles 16:00 -> fecha operativa Jueves 17/09 (4-JU)
EVAL_DT = datetime(2026, 9, 16, 16, 0, tzinfo=BOLIVIA_TZ)
MAIN_MENU = MSG_MAIN_MENU.format(dia="jueves", fecha="17/09")
KEEP_MENU = MSG_MAIN_MENU_KEEP.format(dia="jueves", fecha="17/09")   # the menu for someone with a saved plan
PHONE = "70000001"

SUPERVISORS = [
    {"Nombre": "Carlos Mendoza", "Telefono": PHONE, "Sede": "SCZ", "Zona": "N", "Activo": "TRUE", "Ultimo_Recordatorio": ""},
]


def _r(ruta, vendedor, erp, codigo, zona="N", dia="4-JU"):
    return {"RUTA": ruta, "ZONA": zona, "DIA": dia, "VENDEDOR": vendedor, "CODIGO ERP": erp, "CODIGO RUTA": codigo}


# Route codes of 2 digits exist in the real masters (10, 98): they must not be read as menu options.
MASTER_ROWS = [
    _r("SC-RUTA-A", "VENDEDOR DIEZ", "5010", "10"),
    _r("SC-RUTA-B", "", "", "98"),
    _r("SC-RUTA-D", "DANVER", "4287", "175"),
    _r("SC-RUTA-C", "JEANNINE", "5001", "226"),
]


def _make_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    fake_sheets.set_headers("LOG_BOT", LOG_BOT_COLUMNS)
    _STORE.clear()
    masters = MastersService()
    masters.update_cache("SCZ", MASTER_ROWS)
    return PlanningService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        masters_service=masters,
        supervisor_service=SupervisorService(repo=SupervisorsRepository(client=fake_sheets)),
        conversation_service=ConversationService(),
        audit_service=AuditService(repo=AuditRepository(client=fake_sheets)),
    )


def _msg(body, message_id):
    return ParsedWhatsAppMessage(event="message", session="default", message_id=message_id, from_phone=PHONE, body=body)


async def _say(svc, *bodies, at=EVAL_DT):
    for i, body in enumerate(bodies):
        await svc.handle_message(_msg(body, f"{id(bodies)}-{i}"), eval_datetime=at)


def _last(mock_wa):
    return mock_wa.sent_messages[-1]["text"]


def _state(svc):
    entry = svc.conversation_svc.get(PHONE)
    return entry["state"] if entry else None


def _draft(svc):
    entry = svc.conversation_svc.get(PHONE)
    assert entry["state"] == "AWAITING_CONFIRMATION"
    return entry["payload"]["draft"]


@pytest.fixture
def setup(fake_sheets):
    mock_wa = WhatsAppClient()
    return _make_service(fake_sheets, mock_wa), mock_wa, fake_sheets


# ---------- parsing: only an exact single digit is a menu option ----------

@pytest.mark.parametrize("text,expected", [
    ("1", 1), (" 2 ", 2), ("3.", 3), ("4)", 4), ("1 .", 1),
    ("10", None), ("12", None), ("0", None), ("11", None), ("1a", None), ("uno", None),
    ("", None), ("4287", None),
    ("1️⃣", 1),   # not required, but a pasted keycap emoji normalizes to its digit
])
def test_parse_menu_choice(text, expected):
    assert parse_menu_choice(text) == expected


def test_ruta_input_tolerates_trailing_punctuation_but_keeps_all_digits():
    assert extract_ruta_input("10.") == {"type": "number", "value": "10"}
    assert extract_ruta_input(" 105) ") == {"type": "number", "value": "105"}
    assert extract_ruta_input("1")["value"] == "1"


# ---------- Menu 1: main ----------

@pytest.mark.asyncio
async def test_ayuda_shows_the_main_menu_with_the_four_options(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA")

    assert _last(wa) == f"{MAIN_MENU}\n\n{MSG_MAIN_MENU_COMMANDS_HINT}"
    for option in ("1️⃣ Acompañar a un vendedor", "2️⃣ Cubrir una ruta tú solo", "3️⃣ Venta directa", "4️⃣ Oficina"):
        assert option in _last(wa)
    assert "¿Qué quieres registrar para el jueves 17/09?" in _last(wa)
    assert "Responde con el número." in _last(wa)
    assert _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
async def test_menu_names_the_target_day_not_today(setup):
    svc, wa, _ = setup
    monday_pm = datetime(2026, 9, 14, 16, 0, tzinfo=BOLIVIA_TZ)   # Monday afternoon -> plans for Tuesday
    await _say(svc, "hola", at=monday_pm)

    assert "¿Qué quieres registrar para el martes 15/09?" in _last(wa)


@pytest.mark.asyncio
async def test_unknown_text_without_a_saved_plan_gets_the_main_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "hola")

    assert _last(wa) == MAIN_MENU
    assert _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
async def test_unknown_text_with_a_saved_plan_stays_silent(setup):
    svc, wa, _ = setup
    await _say(svc, "oficina", "1")                    # saved OFICINA via the confirmation menu
    count = len(wa.sent_messages)

    await _say(svc, "hola")

    assert len(wa.sent_messages) == count


@pytest.mark.asyncio
async def test_main_menu_1_asks_for_the_seller_code_and_then_accompanies(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "1")
    assert _last(wa) == MSG_ASK_SELLER_CODE and _state(svc) == "AWAITING_SELLER_CODE"

    await _say(svc, "4287")

    draft = _draft(svc)
    assert draft["modalidad"] == "ACOMPAÑAMIENTO" and draft["codigo_erp_vendedor"] == "4287"


@pytest.mark.asyncio
async def test_in_the_seller_code_step_any_number_is_a_code_even_1_or_10(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "1", "1")                  # NOT menu option 1: a (non-existent) seller code

    assert _last(wa) == MSG_SELLER_CODE_NOT_FOUND
    assert _state(svc) == "AWAITING_SELLER_CODE"        # can try again

    await _say(svc, "10")
    assert _last(wa) == MSG_SELLER_CODE_NOT_FOUND       # no seller 10 either; still not a menu option
    await _say(svc, "banana")
    assert _last(wa) == MSG_SELLER_CODE_INVALID


@pytest.mark.asyncio
async def test_main_menu_2_opens_the_ruta_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "2")

    assert _last(wa) == MSG_RUTA_MENU
    entry = svc.conversation_svc.get(PHONE)
    assert entry["state"] == "AWAITING_RUTA_CODE" and entry["payload"]["submode"] is None


@pytest.mark.asyncio
async def test_main_menu_3_registers_venta_directa(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "3")

    assert "🏢 Modalidad: VENTA DIRECTA" in _last(wa) and _draft(svc)["modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_main_menu_4_registers_oficina(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "4")

    assert "🏢 Modalidad: OFICINA" in _last(wa) and _draft(svc)["modalidad"] == "OFICINA"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["4", " 4 ", "4.", "4)"])
async def test_menu_answers_tolerate_spaces_and_trailing_punctuation(setup, answer):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", answer)

    assert _draft(svc)["modalidad"] == "OFICINA"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["5", "0", "banana", "ok", "12"])
async def test_main_menu_repeats_itself_for_anything_else(setup, answer):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", answer)

    assert _last(wa) == MAIN_MENU
    assert _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
@pytest.mark.parametrize("command,check", [
    ("oficina", lambda d: d["modalidad"] == "OFICINA"),
    ("OFICINA", lambda d: d["modalidad"] == "OFICINA"),
    ("venta directa", lambda d: d["modalidad"] == "VENTA DIRECTA"),
    ("4287", lambda d: d["modalidad"] == "ACOMPAÑAMIENTO"),
])
async def test_text_commands_work_from_the_main_menu(setup, command, check):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", command)

    assert check(_draft(svc))


@pytest.mark.asyncio
async def test_ruta_word_works_from_the_main_menu_and_cancel_leaves_it(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "ruta")
    assert _last(wa) == MSG_RUTA_MENU

    await _say(svc, "AYUDA", "CANCELAR")
    assert _last(wa) == MSG_CANCELLED_NO_CHANGES and _state(svc) is None


# ---------- IDLE / words keep working without any menu ----------

@pytest.mark.asyncio
async def test_direct_seller_code_and_words_still_work_without_a_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "4287")
    assert _draft(svc)["modalidad"] == "ACOMPAÑAMIENTO"

    await _say(svc, "oficina")
    assert _draft(svc)["modalidad"] == "OFICINA"
    await _say(svc, "confirmar")
    assert _last(wa) == MSG_REGISTERED_OK


@pytest.mark.asyncio
async def test_a_stray_number_without_a_menu_is_just_an_unknown_message(setup):
    svc, wa, _ = setup
    await _say(svc, "3")                                # no menu on screen: NOT "venta directa"

    assert _last(wa) == MAIN_MENU


# ---------- Menu 2: RUTA ----------

@pytest.mark.asyncio
async def test_ruta_word_shows_the_ruta_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA")

    text = _last(wa)
    assert text == MSG_RUTA_MENU
    assert "¿Cómo quieres elegir la ruta?" in text
    assert "1️⃣ Por código de vendedor" in text and "2️⃣ Por código de ruta" in text
    assert "3️⃣ Ver las rutas de todos los vendedores de ese día" in text
    assert "O *CANCELAR* para salir." in text


@pytest.mark.asyncio
async def test_ruta_menu_1_asks_for_a_seller_code_and_only_looks_for_sellers(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "1")
    assert _last(wa) == MSG_ASK_SELLER_CODE

    await _say(svc, "10")                               # a ROUTE code, but this sub-mode wants a seller
    assert _last(wa) == MSG_SELLER_CODE_NOT_FOUND
    await _say(svc, "4287")
    draft = _draft(svc)
    assert draft["modalidad"] == "RUTA" and draft["codigo_erp_vendedor"] == "4287"
    assert draft["ruta_oficial"] == "SC-RUTA-D"


@pytest.mark.asyncio
async def test_ruta_menu_2_asks_for_a_route_code_and_only_looks_for_routes(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "2")
    assert _last(wa) == MSG_ASK_ROUTE_CODE

    await _say(svc, "4287")                             # a SELLER code, but this sub-mode wants a route
    assert _last(wa) == MSG_ROUTE_CODE_NOT_FOUND
    assert _state(svc) == "AWAITING_RUTA_CODE"          # still waiting
    await _say(svc, "10")                               # 2-digit route code: not a menu option
    draft = _draft(svc)
    assert draft["modalidad"] == "RUTA" and draft["ruta_oficial"] == "SC-RUTA-A"
    assert draft["codigo_erp_vendedor"] == "N/A"


@pytest.mark.asyncio
async def test_ruta_menu_3_shows_the_list_and_a_number_picks_from_it(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "3")
    assert _last(wa).startswith("📋 *RUTAS DISPONIBLES — JUEVES 17/09/2026*")
    assert svc.conversation_svc.get(PHONE)["payload"]["list_shown"] is True

    await _say(svc, "3")                                # position 3: 10, 98, 175 -> SC-RUTA-D
    assert _draft(svc)["ruta_oficial"] == "SC-RUTA-D"


@pytest.mark.asyncio
async def test_ruta_then_a_two_digit_code_directly_still_works(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "10")                       # "10" is a code, not option "1"

    assert _draft(svc)["ruta_oficial"] == "SC-RUTA-A"


@pytest.mark.asyncio
async def test_ruta_then_a_seller_code_directly_still_works(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "4287")

    assert _draft(svc)["codigo_erp_vendedor"] == "4287"


@pytest.mark.asyncio
async def test_two_digit_route_code_after_the_list_is_a_code_when_it_is_not_a_position(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "LISTA", "98")              # the list has 4 routes: 98 is not a position

    assert _draft(svc)["ruta_oficial"] == "SC-RUTA-B"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["0", "4", "9"])
async def test_ruta_menu_repeats_for_single_digits_that_are_not_options(setup, answer):
    svc, wa, _ = setup
    await _say(svc, "RUTA", answer)

    assert _last(wa) == MSG_RUTA_MENU


@pytest.mark.asyncio
async def test_unrecognized_text_in_the_ruta_menu_repeats_the_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "banana")

    assert _last(wa) == MSG_RUTA_MENU and _state(svc) == "AWAITING_RUTA_CODE"


@pytest.mark.asyncio
async def test_errors_inside_a_sub_mode_repeat_only_that_step(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "1", "banana")
    assert _last(wa) == MSG_SELLER_CODE_INVALID

    await _say(svc, "RUTA", "2", "banana")
    assert _last(wa) == MSG_ROUTE_CODE_INVALID

    await _say(svc, "RUTA", "3", "banana")
    assert _last(wa) == MSG_LIST_PICK_INVALID


@pytest.mark.asyncio
async def test_lista_works_inside_the_route_code_step(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "2", "LISTA")

    assert _last(wa).startswith("📋 *RUTAS DISPONIBLES")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [["RUTA"], ["RUTA", "1"], ["RUTA", "2"], ["RUTA", "3"], ["AYUDA", "1"]])
async def test_cancel_and_the_other_commands_work_from_every_menu(setup, path):
    svc, wa, _ = setup
    await _say(svc, *path, "CANCELAR")
    assert _last(wa) == MSG_CANCELLED_NO_CHANGES and _state(svc) is None

    await _say(svc, *path, "oficina")                   # a text command from inside the menu
    assert _draft(svc)["modalidad"] == "OFICINA"

    await _say(svc, *path, "venta directa")
    assert _draft(svc)["modalidad"] == "VENTA DIRECTA"


# ---------- Menu 3: confirmation ----------

@pytest.mark.asyncio
async def test_confirmation_summary_ends_with_the_numbered_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "oficina")

    text = _last(wa)
    assert text.endswith("1️⃣ Confirmar\n2️⃣ Corregir\n3️⃣ Cancelar\n\nResponde con el número.")
    assert "CONFIRMAR" not in text and "¿Registrar?" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["1", "1.", " 1 "])
async def test_confirmation_1_confirms(setup, answer):
    svc, wa, sheets = setup
    await _say(svc, "oficina", answer)

    assert _last(wa) == MSG_REGISTERED_OK
    assert sheets.get_all_records("PLANIFICACION_DIARIA")[0]["Modalidad"] == "OFICINA"


@pytest.mark.asyncio
async def test_confirmation_2_corrects_shows_the_saved_plan_and_the_main_menu(setup):
    svc, wa, sheets = setup
    await _say(svc, "oficina", "1", "venta directa", "2")      # saved OFICINA, pending VENTA DIRECTA

    text = _last(wa)
    assert text.startswith("📋 Tu planificación actual es:")
    assert "🏢 Modalidad: OFICINA" in text and "VENTA DIRECTA" not in text
    assert text.endswith(KEEP_MENU)
    assert _state(svc) == "AWAITING_MAIN_MENU"                  # the pending draft was discarded
    assert sheets.get_all_records("PLANIFICACION_DIARIA")[0]["Modalidad"] == "OFICINA"


@pytest.mark.asyncio
async def test_confirmation_3_cancels(setup):
    svc, wa, sheets = setup
    await _say(svc, "oficina", "3")

    assert _last(wa) == MSG_CANCELLED_NO_CHANGES and _state(svc) is None
    assert sheets.get_all_records("PLANIFICACION_DIARIA") == []


@pytest.mark.asyncio
async def test_confirmation_words_and_synonyms_still_work(setup):
    svc, wa, _ = setup
    await _say(svc, "oficina", "ok")
    assert _last(wa) == MSG_REGISTERED_OK

    await _say(svc, "venta directa", "NO")
    assert _last(wa) == MSG_CANCELLED_NO_CHANGES

    await _say(svc, "oficina", "corregir")
    assert _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["4", "9", "10", "banana"])
async def test_confirmation_repeats_the_summary_for_anything_else(setup, answer):
    svc, wa, _ = setup
    await _say(svc, "oficina", answer)

    assert "CONFIRMA TU PLANIFICACIÓN" in _last(wa) and _last(wa).endswith("Responde con el número.")
    assert _draft(svc)["modalidad"] == "OFICINA"


@pytest.mark.asyncio
async def test_a_new_command_while_confirming_still_replaces_the_draft(setup):
    svc, wa, _ = setup
    await _say(svc, "oficina", "venta directa")

    assert _draft(svc)["modalidad"] == "VENTA DIRECTA"


# ---------- Menu 4: after CORREGIR ----------

@pytest.mark.asyncio
async def test_corregir_in_idle_with_a_saved_plan_shows_it_then_the_main_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "oficina", "1", "corregir")

    assert _last(wa) == (
        "📋 Tu planificación actual es:\n\n"
        "🏢 Modalidad: OFICINA\n"
        "📆 Fecha: 17/09/2026 (Jueves - 4-JU)\n"
        "🏢 Sede: SCZ\n"
        "👤 Supervisor: Carlos Mendoza"
        f"\n\n{KEEP_MENU}"
    )
    assert _state(svc) == "AWAITING_MAIN_MENU"

    await _say(svc, "3")                                         # and the menu works: now VENTA DIRECTA
    assert "🏢 Modalidad: VENTA DIRECTA" in _last(wa)
    assert _last(wa).startswith("⚠️ Vas a reemplazar tu planificación anterior.")


@pytest.mark.asyncio
async def test_corregir_without_a_saved_plan_says_so_then_the_main_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "corregir")
    assert _last(wa) == f"{MSG_NO_PLAN_INFO.format(fecha='17/09/2026')}\n\n{MAIN_MENU}"
    assert _state(svc) == "AWAITING_MAIN_MENU"

    await _say(svc, "oficina", "2")                              # CORREGIR while confirming, nothing saved
    assert _last(wa).startswith("📋 No tienes una planificación registrada para el 17/09/2026.")
    assert _last(wa).endswith(MAIN_MENU) and _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
async def test_an_escalation_flag_counts_as_no_plan_for_corregir(setup):
    svc, wa, _ = setup
    svc.sheets_repo.mark_escalated("2026-09-17", "SCZ", "Carlos Mendoza")
    await _say(svc, "corregir")

    assert _last(wa).startswith("📋 No tienes una planificación registrada")


# ---------- AYUDA in the middle of a flow only repeats that step ----------

@pytest.mark.asyncio
async def test_ayuda_while_confirming_repeats_the_summary_so_a_3_cannot_be_misread(setup):
    svc, wa, sheets = setup
    await _say(svc, "oficina", "AYUDA")

    assert "CONFIRMA TU PLANIFICACIÓN" in _last(wa) and "¿Qué quieres registrar" not in _last(wa)
    assert _draft(svc)["modalidad"] == "OFICINA"                 # draft intact

    await _say(svc, "1")                                         # still means "Confirmar"
    assert _last(wa) == MSG_REGISTERED_OK


@pytest.mark.asyncio
async def test_ayuda_inside_the_ruta_flow_repeats_the_current_step(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "AYUDA")
    assert _last(wa) == MSG_RUTA_MENU

    await _say(svc, "1", "AYUDA")
    assert _last(wa) == MSG_ASK_SELLER_CODE

    await _say(svc, "RUTA", "2", "AYUDA")
    assert _last(wa) == MSG_ASK_ROUTE_CODE

    await _say(svc, "RUTA", "3", "AYUDA")
    assert _last(wa).startswith("📋 *RUTAS DISPONIBLES")

    await _say(svc, "CANCELAR", "AYUDA", "1", "AYUDA")            # seller code step opened from the main menu
    assert _last(wa) == MSG_ASK_SELLER_CODE


@pytest.mark.asyncio
async def test_ayuda_in_idle_with_a_saved_plan_still_opens_the_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "oficina", "1", "AYUDA")

    assert _last(wa) == f"{KEEP_MENU}\n\n{MSG_MAIN_MENU_COMMANDS_HINT}"   # with a plan: the menu offers option 5
    assert _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
async def test_ayuda_while_choosing_between_routes_repeats_the_route_choice(setup):
    svc, wa, sheets = setup
    svc.masters_service.update_cache("SCZ", MASTER_ROWS + [_r("SC-RUTA-E", "DANVER", "4287", "300")])
    await _say(svc, "4287")
    assert _state(svc) == "AWAITING_SELECTION"

    await _say(svc, "AYUDA")

    assert "Encontré varias rutas" in _last(wa) and _state(svc) == "AWAITING_SELECTION"


# ---------- Menu 5: reminder ----------

def _reminder_service(fake_sheets, mock_wa):
    fake_sheets.set_headers("PLANIFICACION_DIARIA", PLANNING_COLUMNS)
    fake_sheets.seed_records("SUPERVISORES", SUPERVISORS_COLUMNS, SUPERVISORS)
    return ReminderService(
        whatsapp_client=mock_wa,
        sheets_repo=GoogleSheetsPlanningRepository(client=fake_sheets),
        supervisors_repo=SupervisorsRepository(client=fake_sheets),
    )


@pytest.mark.asyncio
async def test_reminder_ends_with_the_main_menu_and_leaves_it_open_for_two_hours(fake_sheets):
    mock_wa = WhatsAppClient()
    _STORE.clear()
    reminders = _reminder_service(fake_sheets, mock_wa)

    await reminders.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))

    text = _last(mock_wa)
    assert text.startswith("⏰ Aún no hemos recibido tu planificación para el 15/09/2026")
    assert text.endswith(MSG_REMINDER_MENU)
    assert "📋 ¿Qué quieres registrar?" in text and "4️⃣ Oficina" in text
    entry = ConversationService().get(PHONE)
    assert entry["state"] == "AWAITING_MAIN_MENU"
    remaining = entry["expires_at"] - datetime.now(timezone.utc)
    assert timedelta(minutes=119) < remaining <= timedelta(minutes=120)


@pytest.mark.asyncio
async def test_replying_a_number_to_the_reminder_works(fake_sheets):
    mock_wa = WhatsAppClient()
    svc = _make_service(fake_sheets, mock_wa)
    reminders = ReminderService(
        whatsapp_client=mock_wa,
        sheets_repo=svc.sheets_repo,
        supervisors_repo=svc.supervisor_svc.repo,
    )
    await reminders.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))

    await _say(svc, "4", at=datetime(2026, 9, 14, 15, 5, tzinfo=BOLIVIA_TZ))

    assert _draft(svc)["modalidad"] == "OFICINA"
    assert "15/09/2026" in _last(mock_wa)


@pytest.mark.asyncio
async def test_reminder_does_not_override_an_abandoned_flow(fake_sheets):
    mock_wa = WhatsAppClient()
    _STORE.clear()
    reminders = _reminder_service(fake_sheets, mock_wa)
    ConversationService().set(PHONE, "AWAITING_CONFIRMATION", payload={"draft": {}})

    await reminders.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))

    assert _last(mock_wa) == MSG_REMINDER_AWAITING_CONFIRMATION     # no main menu on top of a pending plan
    assert ConversationService().get(PHONE)["state"] == "AWAITING_CONFIRMATION"


@pytest.mark.asyncio
async def test_reminder_menu_is_repeated_on_the_next_reminder(fake_sheets):
    mock_wa = WhatsAppClient()
    _STORE.clear()
    reminders = _reminder_service(fake_sheets, mock_wa)

    await reminders.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 15, 0, tzinfo=BOLIVIA_TZ))
    await reminders.run_reminder_cycle(eval_time=datetime(2026, 9, 14, 16, 0, tzinfo=BOLIVIA_TZ))

    assert [m["text"].endswith(MSG_REMINDER_MENU) for m in mock_wa.sent_messages] == [True, True]


# ---------- Supervisors who already have a saved plan: a way out, no nagging ----------

async def _with_saved_plan(svc):
    await _say(svc, "oficina", "1")      # saved OFICINA (confirmed through the menu)


@pytest.mark.asyncio
async def test_menu_for_someone_with_a_plan_offers_option_5_to_keep_it(setup):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, "corregir")

    text = _last(wa)
    assert text.endswith(KEEP_MENU)
    assert "5️⃣ Dejar mi planificación como está" in text
    assert svc.conversation_svc.get(PHONE)["payload"]["keep_option"] is True


@pytest.mark.asyncio
async def test_option_5_leaves_the_plan_untouched_and_ends_the_menu(setup):
    svc, wa, sheets = setup
    await _with_saved_plan(svc)
    before = sheets.get_all_records("PLANIFICACION_DIARIA")
    await _say(svc, "corregir", "5")

    assert _last(wa) == MSG_KEEP_PLAN_OK
    assert _state(svc) is None
    assert sheets.get_all_records("PLANIFICACION_DIARIA") == before


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["5.", " 5 ", "5)"])
async def test_option_5_tolerates_punctuation(setup, answer):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, "corregir", answer)

    assert _last(wa) == MSG_KEEP_PLAN_OK


@pytest.mark.asyncio
async def test_with_a_plan_unrelated_text_in_the_menu_gets_no_reply(setup):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, "corregir")
    count = len(wa.sent_messages)

    await _say(svc, "Quiero que me ayudes a hacer todo el cambio", "hola", "9")

    assert len(wa.sent_messages) == count                       # not trapped in the menu
    assert _state(svc) == "AWAITING_MAIN_MENU"                  # the options still work:
    await _say(svc, "3")
    assert _draft(svc)["modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
async def test_options_1_to_4_and_cancelar_still_work_in_the_keep_menu(setup):
    svc, wa, _ = setup
    await _with_saved_plan(svc)

    await _say(svc, "corregir", "3")
    assert "🏢 Modalidad: VENTA DIRECTA" in _last(wa) and _last(wa).startswith("⚠️ Vas a reemplazar")

    await _say(svc, "corregir", "CANCELAR")
    assert _last(wa) == MSG_CANCELLED_NO_CHANGES and _state(svc) is None


@pytest.mark.asyncio
async def test_5_means_nothing_in_the_menu_of_someone_without_a_plan(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "5")

    assert _last(wa) == MAIN_MENU                                # plain menu again: there is no plan to keep
    assert "5️⃣" not in MAIN_MENU


@pytest.mark.asyncio
async def test_without_a_plan_the_menu_is_unchanged_and_still_repeats(setup):
    svc, wa, _ = setup
    await _say(svc, "corregir")
    assert _last(wa) == f"{MSG_NO_PLAN_INFO.format(fecha='17/09/2026')}\n\n{MAIN_MENU}"
    assert svc.conversation_svc.get(PHONE)["payload"]["keep_option"] is False

    await _say(svc, "hola")
    assert _last(wa) == MAIN_MENU                                # people without a plan are still guided


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["cancelar", "no", "nop", "salir", "descartar"])
async def test_cancel_words_with_a_plan_and_nothing_pending_get_a_short_answer(setup, word):
    svc, wa, _ = setup
    await _with_saved_plan(svc)

    await _say(svc, word)

    assert _last(wa) == MSG_NOTHING_PENDING                      # not the registration menu
    assert _state(svc) is None


@pytest.mark.asyncio
async def test_cancel_words_without_a_plan_still_show_the_menu(setup):
    svc, wa, _ = setup
    await _say(svc, "cancelar")

    assert _last(wa) == MAIN_MENU


# ---------- Exact matching in every state (a sentence containing a command is NOT that command) ----------

from app.whatsapp.templates import MSG_CANCELLED_NO_CHANGES as _CANCELLED  # noqa: E402,F401
from app.whatsapp.templates import MSG_PLAN_ALREADY_ACTIVE, MSG_RUTA_LIST_BAD_PAGE, MSG_SELECTION_INVALID  # noqa: E402

SENTENCES = [
    "hola",
    "quiero corregir algo",
    "necesito una ayuda",
    "el ok de la reunión",
    "dame la ruta por favor",
    "necesito ir a oficina mañana",
    "venta directa es mejor",
    "confirmo el plan",
    "quiero cancelar",
]


# --- IDLE with a saved plan: total silence unless the message IS a command ---

@pytest.mark.asyncio
@pytest.mark.parametrize("sentence", SENTENCES)
async def test_idle_with_a_plan_stays_silent_for_sentences(setup, sentence):
    svc, wa, sheets = setup
    await _with_saved_plan(svc)
    count = len(wa.sent_messages)
    before = sheets.get_all_records("PLANIFICACION_DIARIA")

    await _say(svc, sentence)

    assert len(wa.sent_messages) == count
    assert _state(svc) is None
    assert sheets.get_all_records("PLANIFICACION_DIARIA") == before


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["ok", "sí", "dale", "listo", "confirmar"])
async def test_idle_with_a_plan_confirm_words_stay_silent(setup, word):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    count = len(wa.sent_messages)

    await _say(svc, word)

    assert len(wa.sent_messages) == count


# --- IDLE with a saved plan: the exact commands still answer ---

@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["CORREGIR", "corregir.", " CORREGIR ", "Corregir", "cambiar", "editar"])
async def test_idle_with_a_plan_corregir_shows_the_plan_and_option_5(setup, text):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, text)

    assert _last(wa).startswith("📋 Tu planificación actual es:") and _last(wa).endswith(KEEP_MENU)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["AYUDA", "ayuda.", "Ayuda", "help"])
async def test_idle_with_a_plan_ayuda_opens_the_menu_with_option_5(setup, text):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, text)

    assert _last(wa) == f"{KEEP_MENU}\n\n{MSG_MAIN_MENU_COMMANDS_HINT}"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["4287", "4287.", " 4287 "])
async def test_idle_with_a_plan_a_direct_seller_code_runs_the_normal_flow(setup, text):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, text)

    draft = _draft(svc)
    assert draft["modalidad"] == "ACOMPAÑAMIENTO" and draft["codigo_erp_vendedor"] == "4287"
    assert _last(wa).startswith("⚠️ Vas a reemplazar")


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["cancelar", "Cancelar.", "no", "nop", "salir", "descartar"])
async def test_idle_with_a_plan_cancel_words_say_nothing_is_pending(setup, word):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, word)

    assert _last(wa) == MSG_NOTHING_PENDING


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["RUTA", "ruta.", "Ruta."])
async def test_idle_with_a_plan_ruta_opens_the_ruta_menu(setup, text):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, text)

    assert _last(wa) == MSG_RUTA_MENU


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["VENTA DIRECTA", "venta    directa", "Venta directa."])
async def test_venta_directa_tolerates_case_spaces_and_final_punctuation(setup, text):
    svc, wa, _ = setup
    await _with_saved_plan(svc)
    await _say(svc, text)

    assert _draft(svc)["modalidad"] == "VENTA DIRECTA"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["OFICINA", "oficina.", "Oficína"])
async def test_oficina_tolerates_case_accents_and_final_punctuation(setup, text):
    svc, wa, _ = setup
    await _say(svc, text)

    assert _draft(svc)["modalidad"] == "OFICINA"


# --- IDLE without a plan: anything unknown gets Menu 1 (and sentences are not commands) ---

@pytest.mark.asyncio
@pytest.mark.parametrize("sentence", SENTENCES)
async def test_idle_without_a_plan_sentences_get_the_main_menu(setup, sentence):
    svc, wa, sheets = setup
    await _say(svc, sentence)

    assert _last(wa) == MAIN_MENU                      # plain Menu 1: not AYUDA's (no commands hint), not a flow
    assert sheets.get_all_records("PLANIFICACION_DIARIA") == []


# --- AWAITING_CONFIRMATION ---

@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["ok pero cambia la ruta", "ok gracias", "quiero cancelar", "confirmo el plan",
                                  "quiero corregir algo", "necesito una ayuda"])
async def test_confirmation_sentences_repeat_the_summary(setup, text):
    svc, wa, sheets = setup
    await _say(svc, "oficina", text)

    assert "CONFIRMA TU PLANIFICACIÓN" in _last(wa) and _last(wa).endswith("Responde con el número.")
    assert _draft(svc)["modalidad"] == "OFICINA"                   # not confirmed, corrected or cancelled
    assert sheets.get_all_records("PLANIFICACION_DIARIA") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["ok", "sí", "si", " SI ", "Confirmar.", "CONFIRMAR", "confirrmar", "listo", "dale", "Ok."])
async def test_confirmation_exact_confirm_words_confirm(setup, text):
    svc, wa, _ = setup
    await _say(svc, "oficina", text)

    assert _last(wa) == MSG_REGISTERED_OK


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["corregir.", " CORREGIR ", "cambiar", "editar", "Corregir"])
async def test_confirmation_exact_correct_words_correct(setup, text):
    svc, wa, _ = setup
    await _say(svc, "oficina", text)

    assert _last(wa).startswith("📋 No tienes una planificación registrada")   # Menu 4
    assert _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["cancelar.", "CANCELAR", "no", "nop", "salir", "descartar"])
async def test_confirmation_exact_cancel_words_cancel(setup, text):
    svc, wa, _ = setup
    await _say(svc, "oficina", text)

    assert _last(wa) == MSG_CANCELLED_NO_CHANGES and _state(svc) is None


# --- AWAITING_MAIN_MENU: only an exact single digit is an option ---

@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["1 de octubre", "10", "11", "1a", "1,5", "uno"])
async def test_main_menu_does_not_take_these_as_option_1(setup, text):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", text)

    assert _last(wa) == MAIN_MENU and _state(svc) == "AWAITING_MAIN_MENU"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["1", " 1 ", "1.", "1)", "1 )"])
async def test_main_menu_option_1_tolerates_spaces_and_punctuation(setup, text):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", text)

    assert _last(wa) == MSG_ASK_SELLER_CODE and _state(svc) == "AWAITING_SELLER_CODE"


# --- RUTA / seller code steps ---

@pytest.mark.asyncio
async def test_after_ruta_a_two_digit_route_code_is_a_code_not_option_1(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "10")

    assert _draft(svc)["ruta_oficial"] == "SC-RUTA-A"


@pytest.mark.asyncio
async def test_a_one_digit_number_in_the_seller_step_is_a_code(setup):
    svc, wa, _ = setup
    await _say(svc, "AYUDA", "1", "1")

    assert _last(wa) == MSG_SELLER_CODE_NOT_FOUND and _state(svc) == "AWAITING_SELLER_CODE"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [["RUTA"], ["RUTA", "1"], ["RUTA", "2"], ["AYUDA", "1"]])
async def test_a_sentence_with_cancelar_does_not_cancel_the_flow(setup, path):
    svc, wa, _ = setup
    await _say(svc, *path, "quiero cancelar algo")

    assert _last(wa) != MSG_CANCELLED_NO_CHANGES
    assert _state(svc) in ("AWAITING_RUTA_CODE", "AWAITING_SELLER_CODE")


@pytest.mark.asyncio
@pytest.mark.parametrize("text,page", [("lista 3", 3), ("Lista  2.", 2)])
async def test_lista_with_a_page_number_in_the_ruta_flow(setup, text, page):
    svc, wa, _ = setup
    await _say(svc, "RUTA", text)

    assert _last(wa) == MSG_RUTA_LIST_BAD_PAGE.format(pages=1)       # only 1 page exists: the number was understood


@pytest.mark.asyncio
async def test_a_direct_code_with_a_final_dot_works_in_the_ruta_flow(setup):
    svc, wa, _ = setup
    await _say(svc, "RUTA", "4287.")

    assert _draft(svc)["codigo_erp_vendedor"] == "4287"


# --- AWAITING_SELECTION: the common normalization, only "cancelar" and numbers ---

async def _two_routes(svc):
    svc.masters_service.update_cache("SCZ", MASTER_ROWS + [_r("SC-RUTA-E", "DANVER", "4287", "300")])
    await _say(svc, "4287")
    assert _state(svc) == "AWAITING_SELECTION"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["cancelar", "CANCELAR", "Cancelar.", " cancelar "])
async def test_selection_cancel_tolerates_case_and_punctuation(setup, text):
    svc, wa, _ = setup
    await _two_routes(svc)
    await _say(svc, text)

    assert _last(wa) == MSG_CANCELLED_NO_CHANGES and _state(svc) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["no", "salir", "quiero cancelar", "cancela", "²²", "1 y 2", "uno"])
async def test_selection_only_accepts_cancelar_and_numbers(setup, text):
    svc, wa, _ = setup
    await _two_routes(svc)
    await _say(svc, text)

    assert _last(wa) == MSG_SELECTION_INVALID and _state(svc) == "AWAITING_SELECTION"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["2", " 2 ", "2.", "2)"])
async def test_selection_numbers_tolerate_spaces_and_punctuation(setup, text):
    svc, wa, _ = setup
    await _two_routes(svc)
    await _say(svc, text)

    assert _draft(svc)["codigo_ruta"] == "300"


@pytest.mark.asyncio
async def test_selection_with_a_superscript_digit_does_not_crash(setup):
    svc, wa, _ = setup
    await _two_routes(svc)
    await _say(svc, "²")                      # str.isdigit() accepts it and int() used to blow up

    assert _state(svc) in ("AWAITING_SELECTION", "AWAITING_CONFIRMATION")
