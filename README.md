# Supervisor Planner

Bot de WhatsApp para automatizar la recepción, validación, confirmación y consolidación de la planificación diaria de supervisores comerciales. El supervisor escribe por WhatsApp cómo va a trabajar el día siguiente; el bot valida las reglas de negocio, pide confirmación y registra el resultado en Google Sheets.

## Comandos del bot

> Guía completa para supervisores y analistas: [docs/manual-de-usuario.html](docs/manual-de-usuario.html) (también en [PDF](docs/manual-de-usuario.pdf) y [Markdown](docs/manual-de-usuario.md)).

Todo se puede hacer con palabras o respondiendo con el número del menú que muestra el bot (1️⃣ Acompañar, 2️⃣ Ruta, 3️⃣ Venta directa, 4️⃣ Oficina; y 1️⃣ Confirmar, 2️⃣ Corregir, 3️⃣ Cancelar). Los números solo valen mientras el menú que los ofreció es lo último que dijo el bot.

El administrador pre-carga a los supervisores en la hoja `SUPERVISORES`; quien no esté ahí (o tenga `Activo` distinto de `TRUE`) no recibe respuesta.

| Mensaje | Qué hace |
|---|---|
| `<código del vendedor>` (ej. `4287`) | Acompañar a ese vendedor en su ruta del día |
| `RUTA` | Cubrir una ruta tú solo. El bot pide el código del vendedor, el código de la ruta, o `LISTA` para ver todas las rutas del día de tu zona y elegir una por su número |
| `VENTA DIRECTA` | Venta directa, sin vendedor ni ruta |
| `OFICINA` | Día en oficina |
| `CONFIRMAR` / `CORREGIR` / `CANCELAR` | Responder al resumen pendiente |
| `AYUDA` | Abre el menú principal (dentro de un flujo, repite el paso actual) |

## Stack

- Python 3.11+ y FastAPI
- WAHA (WhatsApp HTTP API) con motor GOWS
- Google Sheets (gspread) como única capa de persistencia
- APScheduler para recordatorios y escalamiento
- Docker Compose

## Requisitos

- Python 3.11+
- Docker Desktop
- Una cuenta de servicio de Google con acceso de edición al Google Sheet
- Un número de WhatsApp dedicado para el bot

## Instalación

1. Clona el repositorio y entra en la carpeta.
2. Crea y activa un entorno virtual:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Copia la plantilla de variables de entorno y edítala:
   ```bash
   cp .env.example .env             # Windows: copy .env.example .env
   ```

### 5. Configurar credenciales de Google

El bot necesita una cuenta de servicio de Google para leer y escribir en Google Sheets.

1. Entra a [Google Cloud Console](https://console.cloud.google.com).
2. Crea un proyecto nuevo (o usa uno existente).
3. En "APIs & Services" → "Library", habilita:
   - **Google Sheets API**
   - **Google Drive API**
4. En "IAM & Admin" → "Service Accounts", crea una cuenta de servicio.
5. Dentro de la cuenta, ve a "Keys" → "Add Key" → "Create new key" → **JSON**.
6. Se descargará un archivo `.json`. Renómbralo a `credentials.json` y colócalo en la carpeta `credentials/` del proyecto (esa carpeta está en `.gitignore` y nunca se sube al repo).
7. Abre el JSON descargado y copia el valor del campo `client_email` (algo como `bot@proyecto.iam.gserviceaccount.com`).
8. Comparte tu Google Sheet con ese email, dándole permisos de **Editor**.
9. Copia el ID del Sheet desde la URL (`https://docs.google.com/spreadsheets/d/<ESTE_ID>/edit`) y pégalo en `.env` como `GOOGLE_SPREADSHEET_ID`.

Referencia oficial: [Google Sheets API Python Quickstart](https://developers.google.com/sheets/api/quickstart/python)

### 6. Levantar los servicios

```bash
docker compose up -d --build
```

## Variables de entorno principales

Todas están documentadas en `.env.example`.

| Variable | Descripción | Valor por defecto |
|---|---|---|
| `TIMEZONE` | Zona horaria operativa | `America/La_Paz` |
| `REMINDER_INTERVAL_MINUTES` | Cada cuántos minutos corre el ciclo de recordatorios (debe dividir 60) | `30` |
| `REMINDER_COOLDOWN_MINUTES` | Mínimo entre dos recordatorios al mismo supervisor (producción: `60`; `1` para pruebas) | `60` |
| `REMINDER_ACTIVITY_WINDOW_MINUTES` | No se envía recordatorio a quien escribió al bot en los últimos N minutos | `10` |
| `DUPLICATE_MESSAGE_WINDOW_SECONDS` | El mismo texto del mismo teléfono en menos de N segundos se ignora (doble envío) | `2` |
| `SHEETS_MAX_RETRIES` / `SHEETS_RETRY_BASE_DELAY` | Reintentos ante 429/5xx de Google Sheets y espera base en segundos (se duplica en cada intento) | `3` / `1` |
| `MONDAY_AM_WINDOW_START` / `MONDAY_AM_ESCALATION_TIME` | Lunes AM: recordatorios para HOY desde la primera hora; desde la segunda, escalamiento | `08:00` / `12:00` |
| `MONDAY_PM_WINDOW_START` / `MONDAY_PM_ESCALATION_TIME` | Lunes PM: recordatorios para MAÑANA; desde la segunda hora, escalamiento. La primera también es el corte lunes → martes de la fecha de trabajo | `15:00` / `18:00` |
| `WEEKDAY_PM_WINDOW_START` / `WEEKDAY_PM_ESCALATION_TIME` | Martes a viernes: recordatorios para el día siguiente; desde la segunda hora, escalamiento | `15:00` / `18:00` |
| `SATURDAY_AM_WINDOW_START` / `SATURDAY_AM_LAST_REMINDER` | Sábado: recordatorios para HOY entre ambas horas (el último ignora el cooldown). Sin escalamiento | `08:00` / `11:30` |
| `GOOGLE_CREDENTIALS_PATH` | Ruta al JSON de la cuenta de servicio | `credentials/credentials.json` |
| `GOOGLE_SPREADSHEET_ID` | ID del Google Sheet | — |
| `WAHA_BASE_URL` | URL de WAHA (en Docker Compose: `http://supervisor-waha:3000`) | `http://localhost:3000` |
| `WAHA_API_KEY` | API key de WAHA | — |
| `WAHA_SESSION` | Nombre de la sesión de WhatsApp | `default` |
| `ADMIN_PHONE` | Teléfono del administrador (8 dígitos locales, sin código de país) que recibe las alertas | — |

El Google Sheet debe contener las hojas de maestros de rutas por sede, `PLANIFICACION_DIARIA`, `SUPERVISORES` y `LOG_BOT` (esta última se crea sola si no existe). Sus nombres se configuran con las variables `GOOGLE_WORKSHEET_*` y `GOOGLE_OUTPUT_WORKSHEET`.

La hoja `SUPERVISORES` lleva en la fila 1, exactamente: `Nombre | Telefono | Sede | Zona | Activo | Ultimo_Recordatorio`. El bot solo escribe `Ultimo_Recordatorio`.

## Configuración de WAHA (paso a paso)

1. Genera una API key con PowerShell:
   ```powershell
   $b = New-Object byte[] 32
   [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
   ($b | ForEach-Object { $_.ToString("x2") }) -join ""
   ```
2. Guárdala en `WAHA_API_KEY` dentro de `.env`. `docker-compose.yml` ya la lee desde allí (`WAHA_API_KEY=${WAHA_API_KEY}`), así que no hace falta escribirla también en el YAML; evita dejarla fija en un archivo que se sube al repositorio.
3. Levanta los servicios:
   ```bash
   docker compose up -d
   ```
4. Abre el dashboard: <http://localhost:3000/dashboard>
5. Ve a **Workers → Connect**, pega la API key y pulsa **Connect**.
6. Ve a **Sessions → + Start New**, nombre `default`, motor **GOWS**, y pulsa **Create & Start**.
7. Escanea el código QR con el WhatsApp del número dedicado.
8. Configura el webhook de la sesión:
   - URL: `http://supervisor-planner-app:8000/webhook/waha`
   - Evento: `message.any`
9. Verifica la conectividad entre contenedores:
   ```bash
   docker exec supervisor-waha curl -s http://supervisor-planner-app:8000/health
   ```

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Estado de la aplicación y de la conexión con Google Sheets |
| `POST` | `/webhook/waha` | Receptor de eventos de WAHA |

## Pruebas

```bash
docker compose exec app pytest -v
```

Los tests usan una hoja de cálculo simulada en memoria y no envían mensajes a WAHA, por lo que no necesitan credenciales ni red. El schedule de recordatorios se fija dentro de los tests, así que no dependen de los valores de tu `.env`.

## Estructura del proyecto

```
.
├── app/
│   ├── main.py             # Entrypoint FastAPI y ciclo de vida
│   ├── config.py           # Configuración (pydantic-settings) y logging
│   ├── api/                # /health y /webhook/waha
│   ├── core/               # Singletons: un cliente de Sheets, cachés y un hilo dedicado para todo el I/O de Sheets
│   ├── whatsapp/           # Cliente WAHA, parser, plantillas, idempotencia, resolución de LID
│   ├── business/           # Reglas de negocio: fechas, validación, matching, estados
│   ├── sheets/             # Cliente de Google Sheets y repositorios
│   ├── services/           # Planificación, supervisores, conversación, recordatorios, auditoría, scheduler
│   └── utils/              # Normalización de teléfonos
├── docs/                   # Manual de uso (HTML, PDF y Markdown) para supervisores y analistas
├── tests/                  # Suite pytest
├── scripts/                # Utilidades de verificación manual
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example            # Plantilla de variables de entorno
├── REQUIREMENTS.md         # Requisitos originales
├── PROGRESS_LEGACY.md      # Bitácora inicial (obsoleta, solo referencia)
└── ARCHITECTURE_LEGACY.md  # Diseño inicial (obsoleto, solo referencia)
```

## Seguridad

Antes de pasar a producción:

- Verifica `DEBUG=false`.
- Configura `REMINDER_INTERVAL_MINUTES` y `REMINDER_COOLDOWN_MINUTES` (60) con el valor real (no el de pruebas).
- Revisa que las ventanas y horas de escalamiento por día (`MONDAY_*`, `WEEKDAY_*`, `SATURDAY_*`) sean las correctas.
- Usa un `ADMIN_PHONE` real.

**Nunca subas al repositorio** `.env`, `credentials/`, `waha_sessions/`, `logs/` ni `data/`.

## Licencia

Uso interno. Todos los derechos reservados.
