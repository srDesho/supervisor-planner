# INSTRUCCIÓN PRINCIPAL

Actúa como un equipo senior compuesto por:

- Arquitecto de software.
- Backend Python senior.
- Ingeniero de automatización de WhatsApp.
- Ingeniero de integración con Google Sheets.
- Ingeniero de APIs.
- Ingeniero de bases de datos.
- Ingeniero DevOps/Docker.
- QA senior.
- Especialista en sistemas robustos de procesamiento de mensajes.

Necesito que desarrolles COMPLETAMENTE un proyecto funcional para Company.

NO quiero únicamente una explicación, pseudocódigo, fragmentos ni una arquitectura conceptual.

Quiero que GENERES EL PROYECTO COMPLETO, con todos los archivos necesarios para poder copiarlo a una carpeta, configurar `.env`, levantar Docker y ejecutarlo.

Antes de generar código, analiza cuidadosamente todos los requisitos.

Si alguna API externa cambió, verifica la documentación oficial y actualizada correspondiente, especialmente WAHA, Google Sheets y Gemini. NO INVENTES endpoints, nombres de eventos, parámetros ni métodos de autenticación.

---

# 1. OBJETIVO DEL SISTEMA

Desarrollar un bot de WhatsApp para automatizar la recepción, interpretación, validación y consolidación de la planificación diaria de 5 supervisores comerciales de Company.

Company tiene:

- 2 supervisores en Santa Cruz.
- 2 supervisores en La Paz / El Alto.
- 1 supervisor en Cochabamba.

Total: 5 supervisores.

La aplicación funcionará inicialmente de manera local y posteriormente debe poder desplegarse en un servidor/VPS mediante Docker.

Tecnologías principales:

- WAHA para WhatsApp.
- Python.
- FastAPI.
- Google Sheets.
- Gemini API.
- SQLite para persistencia interna del MVP.
- Scheduler para recordatorios.

---

# 2. PRINCIPIO ARQUITECTÓNICO CRÍTICO

Gemini NO es la autoridad final de validación.

Gemini solamente puede ayudar a:

- interpretar mensajes;
- detectar intención;
- normalizar nombres;
- corregir errores de escritura;
- proponer coincidencias;
- interpretar lenguaje natural;
- detectar modalidad;
- detectar ambigüedad.

Python debe ser quien realmente decida:

- fecha de trabajo;
- día de trabajo;
- vendedor válido;
- ruta válida;
- códigos oficiales;
- correspondencia ruta/día;
- modalidad válida;
- INSERT;
- UPDATE;
- CANCELACIÓN;
- estados;
- recordatorios;
- escalamiento.

Nunca permitas que Gemini invente información oficial.

Los siguientes valores SIEMPRE deben salir del maestro:

- nombre oficial del vendedor;
- código ERP;
- ruta oficial;
- zona;
- código de ruta;
- día de ruta.

---

# 3. SEDES

Implementar exactamente:

SCZ

LPZ-EA

CBBA

La identidad de sede del supervisor debe obtenerse automáticamente mediante su número de WhatsApp.

El supervisor NO debe escribir su propio nombre.

Debe existir una configuración similar a:

SUPERVISORES

telefono_whatsapp

supervisor

sede

activo

No hardcodear los números directamente dentro de la lógica de negocio.

Utilizar configuración externa.

---

# 4. GOOGLE SHEETS

Existen tres maestros independientes:

PLANIFICACION_SCZ_RENOM

PLANIFICACION_LPZ

VENDEDORES_CBBA

Cada uno contiene:

RUTA
ZONA
DIA
VENDEDOR
CODIGO ERP
CODIGO RUTA

Debe implementarse una capa de acceso a Google Sheets separada de la lógica de negocio.

No colocar código de Google Sheets dentro de `main.py`.

Debe existir un repositorio/servicio dedicado.

Los maestros deben:

1. descargarse;
2. validarse;
3. normalizarse;
4. quedar disponibles en memoria/caché;
5. refrescarse periódicamente.

El sistema debe funcionar incluso evitando consultar Google Sheets por cada mensaje.

Crear configuración para indicar el intervalo de actualización.

---

# 5. AUTENTICACIÓN GOOGLE

Usar una integración segura y documentada.

No colocar secretos en Git.

Crear:

`.env.example`

con placeholders.

Por ejemplo:

GOOGLE_CREDENTIALS_PATH=
GOOGLE_SPREADSHEET_ID=
GOOGLE_WORKSHEET_SCZ=
GOOGLE_WORKSHEET_LPZ=
GOOGLE_WORKSHEET_CBBA=
GOOGLE_OUTPUT_WORKSHEET=
GOOGLE_LOG_WORKSHEET=

La implementación debe documentarse claramente.

---

# 6. ZONA HORARIA

Usar obligatoriamente:

America/La_Paz

No utilizar la zona horaria del servidor sin conversión.

Toda fecha/hora operacional debe calcularse en America/La_Paz.

---

# 7. CÁLCULO DE FECHA DE TRABAJO

Implementar exactamente estas reglas:

Lunes 00:00 a 08:30:
→ mismo lunes.

Lunes después de 08:30:
→ martes.

Martes:
→ miércoles.

Miércoles:
→ jueves.

Jueves:
→ viernes.

Viernes:
→ próximo lunes.

Sábado:
→ próximo lunes.

Domingo:
→ próximo lunes.

La hora de corte debe ser configurable:

MONDAY_CUTOFF_TIME=08:30

Crear función unitaria independiente:

calculate_work_date(now)

Debe tener tests para todas las combinaciones.

---

# 8. DIA DEL MAESTRO

Los valores pueden ser:

1-LU
2-MA
3-MI
4-JU
5-VI
6-SA

Implementar función:

get_weekday_code(date)

Debe devolver exactamente esos valores.

No incluir domingo como día de ruta.

---

# 9. VALIDACIÓN DE RUTA Y DÍA

Esta es una regla crítica.

Ejemplo:

Fecha trabajo:

18/09/2026

Día:

Viernes

Código:

5-VI

Ruta:

ROUTE-001

Si el maestro indica:

DIA = 5-VI

es válida.

Si indica:

DIA = 2-MA

la planificación es inválida.

En ese caso:

- no escribir Google Sheets;
- no modificar la planificación anterior;
- devolver rechazo;
- registrar auditoría.

Python debe ser responsable de esta validación.

Gemini no puede cambiar esta decisión.

---

# 10. FORMATO DEL MENSAJE

El formato recomendado es:

PLANIFICACION

MODALIDAD: ACOMPAÑAMIENTO
VENDEDOR: SELLER_ALPHA
RUTA: ROUTE-001
OBSERVACION: Revisar clientes de baja venta

Pero el sistema también debe tolerar lenguaje natural.

Ejemplos:

"Mañana voy con SELLER_ALPHA a la ruta 77."

"Mañana acompaño a SELLER_ALPHA en DTS 77."

"Mañana hago venta directa en la ruta 81."

"Mañana estaré en oficina."

No obligar al usuario a usar un lenguaje robótico cuando el sistema pueda entenderlo.

---

# 11. MODALIDADES

Implementar:

ACOMPAÑAMIENTO

VENTA DIRECTA

OFICINA

ACOMPAÑAMIENTO:

requiere vendedor + ruta.

VENTA DIRECTA:

requiere ruta.

Vendedor = VENTA DIRECTA

Código ERP = N/A

OFICINA:

ruta = OFICINA

vendedor = N/A

código ERP = N/A

código ruta = N/A

No validar día del maestro para OFICINA.

---

# 12. MATCHING

Implementar primero matching determinístico.

Orden:

1. exacto;
2. lower/upper normalization;
3. quitar tildes;
4. normalizar espacios;
5. normalizar guiones;
6. equivalencia de caracteres;
7. fuzzy matching;
8. Gemini solo si realmente aporta valor.

Gemini NO debe recibir capacidad para inventar resultados.

Si hay coincidencia única y clara:

aceptar/proponer.

Si hay múltiples posibilidades:

AMBIGUO.

Si no existe:

NO_ENCONTRADO.

---

# 13. GEMINI

Crear un cliente independiente:

ai/gemini_client.py

No colocar llamadas directamente en los handlers.

La IA debe devolver JSON estructurado.

Ejemplo conceptual:

{
  "intent": "NEW_PLANNING",
  "modalidad": "ACOMPANAMIENTO",
  "vendedor_texto": "SELLER_ALPHA",
  "ruta_texto": "ruta 77",
  "observacion": ""
}

Nunca permitir que Gemini devuelva como verdad:

codigo_erp

codigo_ruta

dia

Estos valores deben resolverse mediante el maestro.

Además:

- usar temperatura baja;
- validar JSON;
- aplicar timeout;
- implementar manejo de errores;
- tener fallback;
- no depender de Gemini para operaciones simples.

Si Gemini no está disponible, el sistema debe poder manejar entradas simples por matching determinístico.

---

# 14. ESTADOS DEL SISTEMA

Implementar:

PENDIENTE_ENVIO
PENDIENTE_REVISION
PENDIENTE_CONFIRMACION
RECHAZADO
PENDIENTE_CORRECCION
REGISTRADO
MODIFICADO
CANCELADO
EXENTO
PENDIENTE_ESCALADO

Crear máquina de estados o lógica explícita que impida transiciones inválidas.

---

# 15. CONFIRMACIÓN

IMPORTANTE:

La confirmación la realiza EL SUPERVISOR.

No el administrador.

Flujo:

1. recibe mensaje;
2. interpreta;
3. normaliza;
4. valida;
5. genera resumen;
6. envía al supervisor;
7. supervisor confirma;
8. Python registra.

Ejemplo:

📋 PLANIFICACIÓN DETECTADA

📅 Fecha de trabajo: 18/09/2026

🏢 Sede: SCZ

👤 Supervisor: Carlos Mendoza

🚗 Modalidad: Acompañamiento

🛒 Vendedor: SELLER_ALPHA
ERP: 1691

🗺️ Ruta: ROUTE-001
Código: 1100

✅ Día de ruta: 5-VI
✅ Día de trabajo: 5-VI

¿Registrar?

✅ CONFIRMAR
❌ CORREGIR

No escribir a Google Sheets antes de la confirmación.

---

# 16. IDENTIFICACIÓN DEL SUPERVISOR

Obtener el teléfono del evento de WAHA.

Buscarlo en la configuración.

Si no está registrado:

NO procesar la planificación.

Responder algo apropiado y registrar el intento en log.

No permitir que alguien simplemente escriba "soy Carlos" para hacerse pasar por otro supervisor.

---

# 17. IDEMPOTENCIA DE MENSAJES

Guardar el ID del mensaje de WhatsApp.

Si llega dos veces el mismo evento:

procesarlo una sola vez.

Esto es obligatorio para evitar registros duplicados.

---

# 18. PLANIFICACIÓN ACTIVA

La planificación activa se identifica lógicamente por:

Fecha_Trabajo + Sede + Supervisor

Debe existir máximo una planificación activa para esa combinación.

Primer registro:

INSERT.

Corrección posterior:

UPDATE.

No crear una fila adicional como nueva planificación activa.

---

# 19. MODIFICACIONES

El supervisor puede decir:

CAMBIAR

CORREGIR

MODIFICAR

ACTUALIZAR

REEMPLAZAR

o usar lenguaje natural:

"Me equivoqué de vendedor."

"Cambia la ruta."

"Corrijo la planificación."

"La anterior estaba mal."

Gemini puede identificar la intención.

Python ejecutará la modificación.

---

# 20. MODIFICACIÓN PARCIAL

Debe soportar:

CAMBIAR VENDEDOR

SELLER_GAMMA

CAMBIAR RUTA

ROUTE-002

También permitir:

"cambia el vendedor por SELLER_GAMMA"

"cambia la ruta por la 81"

El sistema debe volver a validar todo antes del UPDATE.

---

# 21. CAMBIO INVÁLIDO

Si una modificación no pasa validación:

NO modificar la planificación existente.

Responder:

❌ CAMBIO RECHAZADO

La nueva ruta no corresponde al día de trabajo.

Tu planificación anterior se mantiene sin cambios.

Esto es obligatorio.

---

# 22. CANCELACIÓN

Implementar:

CANCELAR

CANCELAR PLANIFICACION

El sistema debe pedir confirmación antes de cancelar.

No cancelar simplemente por una frase ambigua.

---

# 23. MENSAJES INCOMPLETOS

Si falta información:

pedir únicamente lo necesario.

Ejemplo:

"No pude identificar la ruta."

o:

"Me falta el vendedor para ACOMPAÑAMIENTO."

No reiniciar toda la conversación innecesariamente.

---

# 24. CONTEXTO CONVERSACIONAL

Debe existir un mecanismo para recordar un estado temporal por supervisor.

Ejemplo:

Supervisor:

"Voy con SELLER_ALPHA en la 77."

Bot:

"Encontré estas dos rutas..."

Supervisor:

"1"

El sistema debe saber qué pregunta estaba pendiente.

Este contexto debe persistir mediante SQLite o mecanismo equivalente.

Debe existir expiración para estados conversacionales antiguos.

---

# 25. RECORDATORIOS

Implementar un scheduler.

Frecuencia:

cada 15 minutos.

Configurable:

REMINDER_INTERVAL_MINUTES=15

Debe revisar individualmente a los 5 supervisores.

Mientras no estén registrados:

enviar recordatorio.

No enviar recordatorio una vez:

`REGISTRADO`

También detener recordatorios si:

`CANCELADO`

`EXENTO`

o el periodo de recordatorios terminó.

---

# 26. RECORDATORIO SEGÚN ESTADO

Si:

PENDIENTE_ENVIO

usar:

"⏰ Aún no hemos recibido tu planificación..."

Si:

PENDIENTE_CORRECCION

usar:

"⚠️ Tu planificación está pendiente de corrección..."

Si:

PENDIENTE_CONFIRMACION

usar:

"📋 Tu planificación está pendiente de confirmación..."

No confundir estados.

---

# 27. CADA 15 MINUTOS

Ejemplo:

17:00
17:15
17:30
17:45
18:00
18:15

El scheduler no debe enviar dos recordatorios dentro del mismo intervalo.

Guardar:

last_reminder_at

y revisar antes de enviar.

---

# 28. HORA FINAL

Crear:

REMINDER_END_TIME=20:00

Al superar la hora:

- detener recordatorios normales;
- cambiar a PENDIENTE_ESCALADO;
- notificar al administrador.

El administrador debe configurarse por número WhatsApp.

---

# 29. GRUPO

No utilizar el grupo como canal principal de captura.

Usar conversaciones privadas.

Opcionalmente implementar grupo de monitoreo.

Crear función:

send_daily_status_summary()

Ejemplo:

📊 ESTADO DE PLANIFICACIONES

SCZ
✅ Supervisor 1
⏳ Supervisor 2

LPZ-EA
✅ Supervisor 1
✅ Supervisor 2

CBBA
❌ Supervisor 1

4/5 registradas.

El ID del grupo debe estar en `.env`.

---

# 30. GOOGLE SHEETS OUTPUT

Hoja:

Planificacion_Diaria

Columnas:

ID_Registro
Fecha_Registro
Hora_Registro
Fecha_Trabajo
Sede
Supervisor
Modalidad
Vendedor_Apoyo
Codigo_ERP_Vendedor
Ruta_Oficial
Zona
Codigo_Ruta
DIA
Estado
Observaciones
Es_Cambio
ID_Mensaje_WA

Crear servicio:

sheets/planning_repository.py

Debe implementar como mínimo:

find_active_planning()

insert_planning()

update_planning()

cancel_planning()

---

# 31. LOG

Crear:

LOG_BOT

Registrar como mínimo:

id
timestamp
phone
supervisor
sede
whatsapp_message_id
original_message
intent
state_before
state_after
action
result
error
details

Guardar tanto éxito como errores.

---

# 32. SQLITE

Usar SQLite en el MVP.

Crear tablas apropiadas.

Como mínimo:

supervisors
conversation_states
planning_states
processed_messages
reminders
audit_logs

No guardar secretos de API dentro de SQLite.

---

# 33. TRANSACCIONALIDAD

Un registro solo debe pasar a REGISTRADO después de:

1. validación exitosa;
2. confirmación del supervisor;
3. escritura exitosa en Google Sheets.

Si Google Sheets falla:

NO marcar como registrado.

Guardar error.

Permitir reintento.

---

# 34. RETRY

Implementar reintentos para:

- Google Sheets;
- Gemini;
- WAHA cuando corresponda.

Usar backoff razonable.

No duplicar mensajes ni registros.

---

# 35. MODO DESARROLLO

Crear:

`.env.example`

README.md

docker-compose.yml

Dockerfile

requirements.txt o pyproject.toml

scripts/

tests/

Crear endpoint:

GET /health

Debe responder algo como:

{
  "status": "ok"
}

---

# 36. DOCKER

Preparar contenedores para el proyecto.

Considerar:

- aplicación FastAPI;
- base de datos cuando sea necesario;
- WAHA según arquitectura elegida.

Utilizar variables de entorno.

No poner secretos en Dockerfile.

Crear volúmenes persistentes para datos.

---

# 37. WAHA

Implementar integración utilizando la versión/API actual y documentada de WAHA.

No inventar endpoints.

Implementar:

- recepción de webhook;
- identificación del chat;
- identificación del remitente;
- envío de mensajes;
- manejo de errores;
- validación del evento;
- idempotencia.

El webhook debe ser:

POST /webhook/waha

o el endpoint técnicamente correcto según la implementación actual de WAHA.

Documentar cómo configurar la URL webhook.

---

# 38. SESIÓN DE WHATSAPP

Documentar exactamente:

- cómo levantar WAHA;
- cómo crear/iniciar sesión;
- cómo autenticar el número;
- cómo configurar webhook;
- cómo comprobar que está conectado.

Debe ser entendible para una persona no experta.

---

# 39. GEMINI

Crear cliente desacoplado.

Variable:

GEMINI_API_KEY=

Seleccionar el modelo mediante:

GEMINI_MODEL=

No asumir un nombre de modelo sin comprobar la documentación actual.

Implementar fallback y mensajes claros si la API no está disponible.

---

# 40. SEGURIDAD

Nunca:

- subir `.env`;
- subir credenciales Google;
- subir API keys;
- hardcodear números sensibles;
- imprimir secretos en logs.

Agregar `.gitignore`.

---

# 41. CONFIGURACIÓN

Todo lo variable debe estar en `.env`.

Ejemplos:

APP_ENV=
APP_PORT=
TIMEZONE=
MONDAY_CUTOFF_TIME=
REMINDER_INTERVAL_MINUTES=
REMINDER_END_TIME=
GOOGLE_CREDENTIALS_PATH=
GOOGLE_SPREADSHEET_ID=
GOOGLE_WORKSHEET_SCZ=
GOOGLE_WORKSHEET_LPZ=
GOOGLE_WORKSHEET_CBBA=
GOOGLE_OUTPUT_WORKSHEET=
GOOGLE_LOG_WORKSHEET=
GEMINI_API_KEY=
GEMINI_MODEL=
WAHA_BASE_URL=
WAHA_API_KEY=
WAHA_SESSION=
ADMIN_PHONE=
STATUS_GROUP_ID=

No asumir que todos los valores estarán disponibles.

---

# 42. PRUEBAS

Crear tests reales.

Como mínimo:

### Fecha

- lunes antes de 08:30;
- lunes después de 08:30;
- martes;
- miércoles;
- jueves;
- viernes;
- sábado;
- domingo.

### Validación

- ruta correcta/día correcto;
- ruta correcta/día incorrecto;
- vendedor válido;
- vendedor inexistente;
- ruta inexistente;
- ruta ambigua;
- vendedor ambiguo;
- oficina;
- venta directa.

### UPSERT

- primer registro;
- modificación;
- segunda modificación;
- cancelación.

### Recordatorios

- no registrado;
- registrado;
- pendiente de corrección;
- pendiente de confirmación;
- escalado;
- intervalo de 15 minutos.

### Idempotencia

- mismo mensaje recibido dos veces.

### Seguridad

- número no registrado.

---

# 43. ESTRUCTURA DEL PROYECTO

Propón y genera una estructura similar a:

supervisor_planner/

├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   │
│   ├── api/
│   │   ├── webhook.py
│   │   └── health.py
│   │
│   ├── whatsapp/
│   │   ├── client.py
│   │   ├── parser.py
│   │   ├── handlers.py
│   │   └── messages.py
│   │
│   ├── ai/
│   │   ├── gemini_client.py
│   │   ├── prompts.py
│   │   └── schemas.py
│   │
│   ├── business/
│   │   ├── dates.py
│   │   ├── validation.py
│   │   ├── matching.py
│   │   ├── planning.py
│   │   ├── states.py
│   │   └── reminders.py
│   │
│   ├── sheets/
│   │   ├── client.py
│   │   ├── masters.py
│   │   └── planning_repository.py
│   │
│   ├── database/
│   │   ├── models.py
│   │   ├── database.py
│   │   └── repositories.py
│   │
│   └── services/
│       ├── supervisor_service.py
│       ├── planning_service.py
│       └── audit_service.py
│
├── tests/
│
├── scripts/
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md

Puedes modificar esta estructura si tienes una razón técnica mejor, pero debes mantener una separación limpia entre:

API
WhatsApp
IA
reglas de negocio
Google Sheets
base de datos
scheduler.

---

# 44. README

El README debe explicar paso a paso:

1. requisitos;
2. instalación;
3. creación del entorno;
4. creación del `.env`;
5. configuración de Google Sheets;
6. creación de credenciales;
7. configuración de Gemini;
8. instalación de WAHA;
9. conexión de WhatsApp;
10. configuración del webhook;
11. ejecución;
12. pruebas;
13. solución de errores comunes;
14. migración a VPS;
15. backups;
16. actualización.

Quiero instrucciones realmente ejecutables.

---

# 45. ARCHIVOS COMPLETOS

IMPORTANTE:

NO entregues pseudocódigo.

NO pongas:

"# aquí iría..."

NO pongas funciones incompletas.

NO pongas:

"implementar después".

Genera el contenido completo de cada archivo necesario.

Si un archivo es largo, entrégalo completo.

---

# 46. ORDEN DE RESPUESTA

Tu respuesta debe venir en este orden:

1. Resumen de arquitectura.
2. Decisiones técnicas.
3. Árbol final del proyecto.
4. Todos los archivos completos.
5. Instrucciones de configuración.
6. Instrucciones de ejecución.
7. Pruebas.
8. Ejemplos de conversaciones reales.
9. Lista de variables `.env`.
10. Checklist de despliegue.
11. Limitaciones conocidas.
12. Mejoras futuras.

---

# 47. CONVERSACIONES QUE DEBES SOPORTAR

Caso 1:

Supervisor:

PLANIFICACION

MODALIDAD: ACOMPAÑAMIENTO
VENDEDOR: SELLER_ALPHA
RUTA: DTS 77

Bot:

Detecta coincidencia y muestra resumen.

Supervisor:

CONFIRMAR

Bot:

✅ PLANIFICACIÓN REGISTRADA

---

Caso 2:

Supervisor:

"Mañana voy con SELLER_ALPHA a la ruta 77"

Bot:

interpreta.

---

Caso 3:

Supervisor:

"Me equivoqué de vendedor."

Bot:

busca planificación y pregunta qué desea modificar.

---

Caso 4:

Supervisor:

"cambia el vendedor por SELLER_GAMMA"

Bot:

propone nuevo vendedor oficial.

---

Caso 5:

Supervisor:

"cambia la ruta por la 81"

Bot:

revalida día.

---

Caso 6:

Ruta pertenece a viernes pero fecha es martes.

Bot:

rechaza.

---

Caso 7:

Supervisor:

"Mañana hago venta directa en ruta 82"

Bot:

Vendedor = VENTA DIRECTA.

---

Caso 8:

Supervisor:

"Mañana estaré en oficina."

Bot:

OFICINA.

---

Caso 9:

Supervisor:

"voy a ruta 7"

y existen tres coincidencias.

Bot:

pide selección.

---

Caso 10:

Supervisor no manda planificación.

Scheduler:

cada 15 minutos.

---

# 48. ADMINISTRADOR

El sistema debe contemplar un número administrador configurable.

El administrador podrá recibir alertas de:

- supervisor desconocido;
- error crítico;
- Google Sheets caído;
- WAHA caído;
- Gemini caído;
- planificación no registrada al alcanzar hora límite;
- problemas de sincronización del maestro.

No es necesario crear un panel web completo para el MVP, pero la arquitectura debe permitir agregarlo posteriormente.

---

# 49. MANEJO DE ERROR DE GEMINI

Si Gemini falla:

- no romper el backend;
- usar matching determinístico cuando sea posible;
- si no puede interpretarse con seguridad, pedir al supervisor que utilice el formato estructurado;
- nunca inventar datos.

---

# 50. MANEJO DE ERROR DE GOOGLE SHEETS

Si Google Sheets está temporalmente caído:

- NO marcar como registrado;
- guardar estado pendiente;
- registrar error;
- reintentar;
- avisar al administrador si supera determinado número de intentos.

Nunca afirmar al supervisor:

"Planificación registrada"

si la escritura realmente no fue confirmada.

---

# 51. MANEJO DE ERROR DE WAHA

Registrar el error.

No perder el evento.

Utilizar logs.

Mantener idempotencia.

---

# 52. CALIDAD DEL CÓDIGO

Quiero:

- Python moderno;
- type hints;
- Pydantic;
- manejo estructurado de excepciones;
- logging;
- funciones pequeñas;
- separación por responsabilidades;
- nombres claros;
- configuración centralizada;
- tests;
- documentación.

Evita sobreingeniería innecesaria.

El código debe ser fácil de entender y mantener por una persona que está aprendiendo backend/automatización pero tiene conocimientos de Python y BI.

---

# 53. FUTURO VPS

El proyecto debe diseñarse de modo que migrarlo de:

Windows + Docker local

a:

Linux VPS + Docker

requiera como máximo:

- mover archivos;
- configurar `.env`;
- montar persistencia;
- configurar dominio/HTTPS si fuera necesario;
- actualizar webhook.

No meter rutas absolutas de Windows en la lógica.

---

# 54. REQUISITO FINAL

Quiero que el resultado sea un MVP REALMENTE EJECUTABLE.

No quiero que simplemente me enseñes cómo hacerlo.

Quiero que GENERES EL PROYECTO.

Después de generar el código:

- revisa internamente la consistencia entre archivos;
- comprueba imports;
- comprueba nombres de variables;
- comprueba endpoints;
- comprueba modelos;
- comprueba estados;
- comprueba flujo de INSERT/UPDATE;
- comprueba que los recordatorios utilizan 15 minutos;
- comprueba que el día de ruta se valida con Python;
- comprueba que el supervisor confirma;
- comprueba que una modificación inválida no destruye la planificación anterior;
- comprueba idempotencia;
- comprueba que Google Sheets no se actualiza antes de la confirmación;
- comprueba que el sistema puede correr sin Gemini cuando una coincidencia determinística es suficiente.

Si detectas una decisión técnicamente mejor que alguna parte de esta especificación, puedes modificarla, pero debes explicar claramente qué cambiaste y por qué.

No elimines ningún requisito funcional importante sin explicarlo.

Entrega el proyecto completo.