> ⚠️ **DOCUMENTO OBSOLETO.** Se conserva solo como referencia histórica del diseño inicial. El estado actual del proyecto está en el código y en REQUIREMENTS.md.

# PROGRESS.md - Bitácora de Progreso y Roadmap de Implementación
## Proyecto: Supervisor Planner (Bot de Planificación Comercial WhatsApp)

---

### 1. Estado Actual del Proyecto

| Métrica | Estado |
| :--- | :--- |
| **Fase Actual** | **FASE 2 COMPLETADA: Construcción de la Base Real del Proyecto** |
| **Siguiente Fase** | **FASE 3: Integración de Clientes Externos (Google Sheets gspread, WAHA API y Gemini SDK)** |
| **Tests Automatizados** | **33 tests PASSED (100% de éxito)** |
| **FastAPI /health** | **200 OK verificado** |
| **Docker Base** | `Dockerfile` y `docker-compose.yml` listos y configurados |

---

### 2. Entregables Realizados en Fase 2

#### 2.1. Arquitectura y Código Fuente
* ✅ **Estructura de carpetas completa:** `app/api`, `app/whatsapp`, `app/ai`, `app/business`, `app/sheets`, `app/database`, `app/services`, `config`, `tests`, `data`, `logs`.
* ✅ **`app/main.py`:** Aplicación FastAPI con Lifespan, inicialización de base de datos SQLite y registro de routers.
* ✅ **`app/config.py`:** Configuración centralizada con `pydantic-settings` y logging estructurado (consola y archivo).
* ✅ **`app/dependencies.py`:** Inyección de dependencias para FastAPI (sesiones DB, repositorios, servicios).
* ✅ **`app/api/health.py`:** Endpoint `GET /health` con verificación real de conectividad a la base de datos SQLite y reporte de timezone.
* ✅ **`app/api/webhook.py`:** Endpoint `POST /webhook/waha` con acuse `200 OK` inmediato y procesamiento en background.
* ✅ **`app/database/`:** Motor SQLite (`database.py`), modelos SQLAlchemy (`models.py`) para las 6 tablas requeridas (`supervisors`, `conversation_states`, `planning_states`, `processed_messages`, `reminders`, `audit_logs`) y capa de repositorios (`repositories.py`). Seeding automático desde `config/supervisors.json`.
* ✅ **`app/business/dates.py`:** Lógica operacional de `calculate_work_date` (regla de Lunes 08:30 y avance a siguiente día o próximo lunes) y `get_weekday_code` (`1-LU` a `6-SA`) bajo `America/La_Paz`.
* ✅ **`app/business/matching.py`:** Pipeline determinístico de normalización (tildes, mayúsculas, guiones) y RapidFuzz con alineación multi-token y deduplicación para evitar falsas ambigüedades.
* ✅ **`app/business/validation.py`:** Validación dura de negocio: correspondencia Ruta vs Día en maestro, reglas de `ACOMPAÑAMIENTO`, `VENTA DIRECTA` y `OFICINA`.
* ✅ **`app/business/states.py`:** FSM estricta con control de transiciones legales entre los 10 estados y prevención de saltos inválidos.
* ✅ **`app/business/planning_rules.py`:** Generadores de resumen de confirmación y rechazos informativos con preservación de planificación previa.
* ✅ **`app/ai/`:** Esquemas Pydantic (`schemas.py`), prompts de dominio (`prompts.py`) y cliente desacoplado `GeminiClient` (`gemini_client.py`) con fallback determinístico para operar sin conexión o con API key pendiente.
* ✅ **`app/sheets/`:** Abstracciones de cliente (`client.py`), catálogo maestro en memoria para SCZ, LPZ-EA y CBBA (`masters.py`) y repositorio de planificación con simulación de UPSERT y cancelación (`planning_repository.py`).
* ✅ **`app/whatsapp/`:** Parser de eventos WAHA (`parser.py`), plantillas de mensajes oficiales (`templates.py`), cliente asíncrono HTTP (`client.py`) y dispatcher con control de idempotencia (`handlers.py`).
* ✅ **`app/services/`:** Orquestación de supervisores (`supervisor_service.py`), contexto conversacional con TTL (`conversation_service.py`), ciclo de planificación (`planning_service.py`), recordatorios periódicos cada 15 min y escalamiento a las 20:00 (`reminder_service.py`), auditoría (`audit_service.py`) y planificador APScheduler (`scheduler_service.py`).

#### 2.2. Configuración, Despliegue y Pruebas
* ✅ **`requirements.txt`:** Dependencias estrictamente fijadas (`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `rapidfuzz`, `httpx`, `apscheduler`, `pytest`, etc.).
* ✅ **`.env.example`:** Plantilla exhaustiva con todos los parámetros de configuración.
* ✅ **`.gitignore`:** Reglas para ignorar `.env`, `*.db`, `credentials/`, `__pycache__/`, `.pytest_cache/`, `logs/`.
* ✅ **`config/supervisors.json`:** Lista oficial inicial con los 5 supervisores de Company en SCZ, LPZ-EA y CBBA.
* ✅ **`Dockerfile` y `docker-compose.yml`:** Contenedores de producción con Python 3.11-slim, timezone `America/La_Paz`, volúmenes persistentes y servicio WAHA preparado.
* ✅ **`README.md`:** Documentación paso a paso de instalación, configuración, pruebas y ejecución.
* ✅ **`tests/`:** 33 pruebas automatizadas ejecutadas y aprobadas:
  * `test_dates.py`: 11 tests (8 casuísticas de fecha, corte 08:30, códigos `1-LU` a `6-SA`, excepción de domingo).
  * `test_states.py`: 4 tests (transiciones válidas, excepciones en saltos ilegales, elegibilidad de recordatorios, estados terminales).
  * `test_matching.py`: 7 tests (normalización, extracción de números de ruta, coincidencia exacta, fuzzy typos, ambigüedad, no encontrado).
  * `test_validation.py`: 5 tests (acompañamiento, ruta/día inválido, oficina, venta directa, vendedor faltante).
  * `test_health.py`: 2 tests (`GET /health` y `GET /`).
  * `test_e2e_flows.py`: 4 tests (flujo E2E nuevo, modificación inválida que protege el plan previo, idempotencia de mensajes duplicados, rechazo de remitente desconocido).

---

### 3. Matriz de Cobertura de Requisitos de `SPEC.md`

| # | Requisito / Sección de SPEC | Estado Fase 1 | Estado Fase 2 |
| :-: | :--- | :-: | :-: |
| **1-3** | Objetivo, 5 supervisores, 3 sedes (SCZ, LPZ, CBBA) | ✅ Analizado | ✅ Implementado (`config/supervisors.json` + SQLite) |
| **2** | Autoridad Python vs Asistente IA | ✅ Analizado | ✅ Implementado (`validation.py` + `dates.py`) |
| **4-5** | Maestros Google Sheets (`SCZ`, `LPZ`, `CBBA`) | ✅ Analizado | ✅ Preparado (`masters.py` con caché en memoria) |
| **6-7** | Zona Horaria `America/La_Paz` y `Fecha_Trabajo` | ✅ Analizado | ✅ Implementado y probado (`dates.py`, 8 casos) |
| **8** | Códigos de Día (`1-LU` a `6-SA`) | ✅ Analizado | ✅ Implementado y probado (`dates.py`) |
| **9** | Validación Ruta vs Día de Maestro | ✅ Analizado | ✅ Implementado y probado (`validation.py`) |
| **10-11**| Formato y Modalidades (Acompañamiento, Venta Directa, Oficina) | ✅ Analizado | ✅ Implementado y probado (`validation.py`) |
| **12** | Matching Determinístico Escalonado (RapidFuzz) | ✅ Analizado | ✅ Implementado y probado (`matching.py`) |
| **13** | Gemini API Desacoplado | ✅ Analizado | ✅ Implementado (`gemini_client.py` con fallback) |
| **14** | Estados del Sistema (10 estados) | ✅ Analizado | ✅ Implementado y probado (`states.py`) |
| **15** | Confirmación por el Supervisor | ✅ Analizado | ✅ Implementado y probado (`planning_service.py`) |
| **16** | Identificación de Remitente (Whitelist) | ✅ Analizado | ✅ Implementado y probado (`supervisor_service.py`) |
| **17** | Idempotencia de Mensajes de WhatsApp | ✅ Analizado | ✅ Implementado y probado (`handlers.py` + SQLite) |
| **18-21**| Planificación Activa y UPSERT | ✅ Analizado | ✅ Implementado y probado (`planning_repository.py`) |
| **22** | Cancelación Segura de Planificación | ✅ Analizado | ✅ Implementado (`planning_service.py`) |
| **23-24**| Mensajes Incompletos y Contexto Conversacional | ✅ Analizado | ✅ Implementado (`conversation_service.py`) |
| **25-28**| Scheduler de Recordatorios (15 min y corte 20:00) | ✅ Analizado | ✅ Implementado (`reminder_service.py`, `scheduler_service.py`) |
| **29** | Grupo de Monitoreo / Resumen Diario | ✅ Analizado | ✅ Implementado (`reminder_service.py`, `templates.py`) |
| **30-31**| Estructura Google Sheets Output y `LOG_BOT` | ✅ Analizado | ✅ Implementado (`planning_repository.py`, `audit_service.py`) |
| **32-34**| SQLite, Transaccionalidad y Reintentos | ✅ Analizado | ✅ Implementado (`models.py`, `database.py`) |
| **35-41**| Docker, Configuración `.env`, WAHA y Seguridad | ✅ Analizado | ✅ Implementado (`Dockerfile`, `docker-compose.yml`, `.env.example`) |
| **42** | Estrategia Integral de Pruebas | ✅ Analizado | ✅ Implementado (33 tests automáticos) |

---

### 4. Roadmap de Siguientes Fases

```
  ┌──────────────────────────────────────────────────────────┐
  │ FASE 1: Análisis Técnico y Preparación de la Base       │
  │ [x] Lectura profunda y validación de SPEC.md             │
  │ [x] Creación de ARCHITECTURE.md y PROGRESS.md            │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ FASE 2: Base Real del Proyecto (EJECUTADA CON ÉXITO)    │
  │ [x] Estructura de carpetas y paquetes Python             │
  │ [x] FastAPI, Pydantic Settings, Logging y /health        │
  │ [x] SQLite: 6 tablas, modelos, repositorios y seed       │
  │ [x] Core de negocio: fechas, códigos de día, reglas      │
  │ [x] Matching RapidFuzz con deduplicación y FSM           │
  │ [x] Clientes desacoplados (WAHA, Sheets, Gemini)         │
  │ [x] Dockerfile, docker-compose.yml, .gitignore y README  │
  │ [x] Suite de pruebas pytest: 33 tests PASSED             │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ FASE 3: Integración de Clientes Externos                 │
  │ [ ] Conexión en vivo con Google Sheets API (gspread)     │
  │ [ ] Descarga y caché periódico de los 3 maestros reales  │
  │ [ ] Conexión y autenticación con Gemini API (google-genai)│
  │ [ ] Conexión y gestión de sesiones con WAHA              │
  │ [ ] Scripts de verificación de conectividad externa      │
  └────────────────────────────┬─────────────────────────────┘
                               │
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │ FASE 4: Pruebas de Carga, Validación en Servidor y Cierre│
  │ [ ] Validación de webhook en vivo con WAHA en Docker     │
  │ [ ] Comprobación de corte de las 20:00 y alertas Admin   │
  │ [ ] Manual operativo para despliegue en VPS Linux        │
  └──────────────────────────────────────────────────────────┘
```
