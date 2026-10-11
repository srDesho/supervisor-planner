# Supervisor Planner

Bot de WhatsApp para automatizar la recepción, validación, confirmación y consolidación de la planificación diaria de supervisores comerciales. El supervisor escribe por WhatsApp el código de un vendedor (o `oficina` / `venta directa`); el bot valida las reglas de negocio, pide confirmación y registra el resultado en Google Sheets.

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
| `MONDAY_CUTOFF_TIME` | Hora de corte del lunes para calcular la fecha de trabajo (reservada: hoy el código usa `08:30` fijo) | `08:30` |
| `PLANNING_WINDOW_START` / `PLANNING_WINDOW_END` | Ventana (lunes a viernes) en la que el bot acepta planificaciones nuevas y envía recordatorios | `15:00` / `18:00` |
| `REMINDER_INTERVAL_MINUTES` | Cada cuántos minutos corre el ciclo de recordatorios | `30` |
| `REMINDER_ESCALATION_TIME` | Hora a la que se escala al administrador a quienes no han planificado | `18:00` |
| `SATURDAY_NOTICE_TIME` | Hora del aviso único de los sábados | `11:45` |
| `GOOGLE_CREDENTIALS_PATH` | Ruta al JSON de la cuenta de servicio | `credentials/credentials.json` |
| `GOOGLE_SPREADSHEET_ID` | ID del Google Sheet | — |
| `WAHA_BASE_URL` | URL de WAHA (en Docker Compose: `http://supervisor-waha:3000`) | `http://localhost:3000` |
| `WAHA_API_KEY` | API key de WAHA | — |
| `WAHA_SESSION` | Nombre de la sesión de WhatsApp | `default` |
| `ADMIN_PHONE` | Teléfono del administrador (8 dígitos locales, sin código de país) que recibe las alertas | — |

El Google Sheet debe contener las hojas de maestros de rutas por sede, `PLANIFICACION_DIARIA`, `SUPERVISORES` y `LOG_BOT` (esta última se crea sola si no existe). Sus nombres se configuran con las variables `GOOGLE_WORKSHEET_*` y `GOOGLE_OUTPUT_WORKSHEET`.

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

Los tests usan una hoja de cálculo simulada en memoria, por lo que no necesitan credenciales ni red. La configuración se lee del `.env`: si cambiaste la ventana de planificación, el intervalo de recordatorios o la hora de escalamiento para pruebas manuales, algunos tests de recordatorios y escalamiento pueden fallar. Ejecútalos con los valores por defecto de `.env.example`.

## Estructura del proyecto

```
.
├── app/
│   ├── main.py             # Entrypoint FastAPI y ciclo de vida
│   ├── config.py           # Configuración (pydantic-settings) y logging
│   ├── api/                # /health y /webhook/waha
│   ├── whatsapp/           # Cliente WAHA, parser, plantillas, idempotencia, resolución de LID
│   ├── business/           # Reglas de negocio: fechas, validación, matching, estados
│   ├── sheets/             # Cliente de Google Sheets y repositorios
│   ├── services/           # Planificación, supervisores, conversación, recordatorios, auditoría, scheduler
│   └── utils/              # Normalización de teléfonos y registro de intentos no autorizados
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
- Configura `REMINDER_INTERVAL_MINUTES` con el valor real (no el de pruebas).
- Revisa que la ventana horaria (`PLANNING_WINDOW_START` / `PLANNING_WINDOW_END`) y `REMINDER_ESCALATION_TIME` sean los correctos.
- Usa un `ADMIN_PHONE` real.

**Nunca subas al repositorio** `.env`, `credentials/`, `waha_sessions/`, `logs/` ni `data/`.

## Licencia

Uso interno. Todos los derechos reservados.
