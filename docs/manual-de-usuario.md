# Supervisor Planner — Manual de uso

Sistema de registro de la planificación diaria de supervisores comerciales por WhatsApp.

> Versión 1.0 · Octubre 2026. Existen también una versión en HTML ([manual-de-usuario.html](manual-de-usuario.html)) y un PDF generado a partir de ella ([manual-de-usuario.pdf](manual-de-usuario.pdf)). **Las tres deben mantenerse iguales**; el PDF se regenera abriendo el HTML y usando *Imprimir → Guardar como PDF* (sin encabezados ni pies de página).

| | |
|---|---|
| **Parte 1** | Supervisores: cómo registrar, consultar y cambiar tu planificación |
| **Parte 2** | Analistas: cómo administrar los datos, entender los reportes y resolver problemas |

---

# Parte 1 — Guía del supervisor

## 1. Qué hace el sistema

Cada día laboral debes avisar **cómo vas a trabajar el siguiente día**: acompañando a un vendedor, cubriendo una ruta tú solo, en venta directa o en oficina. Lo haces conversando por WhatsApp con el bot. El bot valida tu elección, te muestra un resumen, **te pide confirmación** y recién entonces la guarda.

- No hay que instalar nada: es una conversación normal de WhatsApp con el número del bot.
- El bot te atiende **a cualquier hora y cualquier día**.
- Si tu número no está habilitado, el bot **no responde** (ver sección 9).

## 2. Cómo responder: palabras o números

Puedes usar **palabras** (`oficina`, `confirmar`) o **números** cuando el bot te muestra un menú numerado. Ambas formas hacen lo mismo; usa la que prefieras.

Reglas de los números:

- Solo valen **mientras el menú esté en pantalla**, es decir, si es lo último que te escribió el bot.
- Solo cuenta **un dígito exacto**: `1`, `2`, `3` o `4` (también `1.` o `1)`). Un código como `10` o `4287` nunca se toma como opción de menú.
- Si respondes algo que el bot no entiende, **te repite el menú**.

## 3. ¿Para qué día estás planificando?

El bot calcula la fecha automáticamente y **siempre la escribe en el menú y en el resumen**. Revísala antes de confirmar.

| Cuando escribes | Planificas para |
|---|---|
| Lunes antes de las 15:00 | **Hoy** (lunes) |
| Lunes desde las 15:00 | Martes |
| Martes, miércoles o jueves | El día siguiente |
| Viernes | Sábado |
| Sábado antes de las 12:00 | **Hoy** (sábado) |
| Sábado desde las 12:00, o domingo | Lunes |

## 4. Registrar tu planificación

Escribe **AYUDA** (o cualquier mensaje) para ver el menú principal:

```
📋 ¿Qué quieres registrar para el martes 15/09?

1️⃣ Acompañar a un vendedor
2️⃣ Cubrir una ruta tú solo
3️⃣ Venta directa
4️⃣ Oficina

Responde con el número.
```

### 4.1 Acompañar a un vendedor

Vas en la ruta **con** un vendedor.

- **Con palabras:** escribe directamente el **código ERP del vendedor** (3 a 6 dígitos), por ejemplo `4287`.
- **Con menú:** `1` y luego el código.

Si el vendedor tiene **más de una ruta ese día**, el bot te las lista y debes responder con el **número** de la ruta que acompañarás.

### 4.2 Cubrir una ruta tú solo

Tú haces la ruta, sin acompañar a un vendedor. Escribe **`RUTA`** (o `2` en el menú principal). El bot pregunta cómo quieres elegirla:

```
🚗 ¿Cómo quieres elegir la ruta?

1️⃣ Por código de vendedor
2️⃣ Por código de ruta
3️⃣ Ver las rutas de todos los vendedores de ese día

Responde con el número.
O CANCELAR para salir.
```

| Opción | Qué haces | Ejemplo |
|---|---|---|
| `1` Por código de vendedor | Envías el código del vendedor; el bot toma su ruta del día | `4287` |
| `2` Por código de ruta | Envías el código de la ruta | `105` |
| `3` Ver las rutas | El bot lista todas las rutas de **tu zona** para ese día; respondes con el **número de la lista** | `3` |

Atajos: después de `RUTA` puedes enviar directamente un código (el bot prueba primero como vendedor y luego como ruta) o escribir `LISTA`. Si hay muchas rutas, la lista tiene páginas: `LISTA 2`, `LISTA 3`.

Ejemplo de lista:

```
📋 RUTAS DISPONIBLES — JUEVES 17/09/2026

1. SC-DTS-RUTA-126 · JEANNINE ARIANA CASTEDO VON BOECK · 105
2. SC-DTS-RUTA-24 · DANVER DANIEL RAMIREZ RODRIGUEZ · 175
3. SC-DTS-RUTA-75 · VENDEDOR 10 · 226

Envía el NÚMERO de la ruta que vas a cubrir (ej. 3).
O envía CANCELAR para salir.
```

Cada línea es `número · ruta · vendedor · código de ruta`. Con la lista en pantalla, **un número corto es la posición en la lista**.

### 4.3 Venta directa

Vendes sin vendedor ni ruta asignada. Escribe `venta directa` (o `3` en el menú principal).

### 4.4 Oficina

Trabajas desde la oficina. Escribe `oficina` (o `4` en el menú principal).

## 5. Confirmar, corregir o cancelar

Antes de guardar, el bot muestra un resumen y **no registra nada hasta que lo confirmes**:

```
📋 CONFIRMA TU PLANIFICACIÓN

🏢 Modalidad: OFICINA
📆 Fecha: 15/09/2026 (Martes - 2-MA)
🏢 Sede: SCZ
👤 Supervisor: Carlos Mendoza

1️⃣ Confirmar
2️⃣ Corregir
3️⃣ Cancelar

Responde con el número.
```

| Quieres | Número | Palabras que también valen |
|---|---|---|
| **Confirmar** (guardar) | `1` | `confirmar`, `confirma`, `confirmo`, `ok`, `okey`, `dale`, `listo`, `si` / `sí` |
| **Corregir** (cambiar) | `2` | `corregir`, `corrige`, `corrijo`, `cambiar`, `cambia`, `editar`, `edito` |
| **Cancelar** (descartar) | `3` | `cancelar`, `cancela`, `cancelo`, `descartar`, `no`, `nop`, `salir`, `salgo` |

> **Importante:** las palabras cortas (`ok`, `dale`, `listo`, `si`, `no`, `nop`, `salir`, `salgo`) solo cuentan cuando son **todo el mensaje**. "No tengo ruta para hoy" **no** cancela tu planificación, y "ok gracias" **no** la confirma. Las palabras largas (`confirmar`, `cancelar`, `corregir`…) sí se reconocen dentro de una frase.

Si en lugar de responder envías **otro comando** (otro código, `oficina`, `ruta`…), el bot reemplaza el borrador por tu nueva elección.

## 6. Ver o cambiar una planificación ya guardada

- **Ver lo guardado:** escribe `corregir`. El bot muestra tu planificación actual y, debajo, el menú principal con una opción extra: **`5` Dejar mi planificación como está**. Si cambias de idea, responde `5` (o `cancelar`) y no se modifica nada.
- **Cambiarla:** envía simplemente la nueva elección (por ejemplo `oficina`). El bot avisará *"⚠️ Vas a reemplazar tu planificación anterior."* y mostrará el resumen nuevo para confirmar.
- **Si eliges lo mismo que ya está guardado**, el bot responde *"✅ Esa planificación ya está activa. No hay cambios."* y no modifica nada.
- Cuando ya tienes una planificación guardada, el bot **no contesta mensajes que no entiende** ni te repite el menú (para no molestarte). Escribe `AYUDA` o `corregir` para volver a ver opciones. Si escribes `cancelar` (o `no`, `salir`) sin tener nada pendiente, te responde que tu planificación sigue activa.

Ejemplo: ver lo guardado.

```
Tú:  corregir
Bot: 📋 Tu planificación actual es:

     🏢 Modalidad: OFICINA
     📆 Fecha: 15/09/2026 (Martes - 2-MA)
     🏢 Sede: SCZ
     👤 Supervisor: Carlos Mendoza

     📋 ¿Qué quieres registrar para el martes 15/09?
     1️⃣ Acompañar a un vendedor … 4️⃣ Oficina
     5️⃣ Dejar mi planificación como está
```

## 7. Recordatorios automáticos

Si todavía no registraste tu planificación, el bot te escribe y deja abierto el menú; puedes responder con `1` a `4`, incluso horas después.

```
⏰ Aún no hemos recibido tu planificación para el 15/09/2026 (2-MA).

📋 ¿Qué quieres registrar?

1️⃣ Acompañar a un vendedor
2️⃣ Cubrir una ruta tú solo
3️⃣ Venta directa
4️⃣ Oficina

Responde con el número.
```

| Día | Horario de recordatorios | Para qué día |
|---|---|---|
| Lunes | 08:00 – 12:00 | Hoy |
| Lunes | 15:00 – 18:00 | Martes |
| Martes a viernes | 15:00 – 18:00 | Día siguiente |
| Sábado | 08:00 – 11:30 | Hoy |

- Recibes **como máximo un recordatorio por hora**.
- **No** se te recuerda si escribiste al bot en los últimos 10 minutos.
- Si al cierre (12:00 / 18:00) no planificaste, el sistema **avisa al administrador**. El sábado no hay aviso al administrador.

## 8. Resumen de comandos

| Comando | Qué hace |
|---|---|
| `AYUDA` | Abre el menú principal. Dentro de un flujo, repite el paso en que estás |
| `<código>` (3 a 6 dígitos) | Acompañar a ese vendedor |
| `RUTA` | Cubrir una ruta tú solo (menú de 3 opciones) |
| `LISTA` / `LISTA 2` | Lista de rutas del día (dentro del flujo RUTA) |
| `VENTA DIRECTA` | Registrar venta directa |
| `OFICINA` | Registrar oficina |
| `CONFIRMAR`, `CORREGIR`, `CANCELAR` | Responder al resumen (o `1`, `2`, `3`) |

Las mayúsculas y las tildes no importan: `Sí`, `si` y `SI` son lo mismo.

## 9. Mensajes del bot y qué hacer

| El bot dice | Qué significa | Qué hacer |
|---|---|---|
| *No encontré ningún vendedor con ese código…* | El código no existe en tu sede | Revisa el código y vuelve a enviarlo |
| *El código X pertenece a … Esa zona no está a tu cargo* | El vendedor es de otra zona | Elige un vendedor de tu zona |
| *Ese vendedor no tiene una ruta asignada…* | No tiene ruta en la fecha planificada | Elige otro vendedor o usa `RUTA` → `LISTA` |
| *El vendedor … ya fue registrado … por …* | Otro supervisor ya lo registró ese día | Elige otro vendedor |
| *No encontré ninguna ruta con ese código…* | El código de ruta no existe en tu zona ese día | Revisa el código o usa `LISTA` |
| *Número inválido, la lista tiene N rutas* | Elegiste un número fuera de la lista | Responde con un número de 1 a N |
| *Tu registro está incompleto…* | Tu usuario no tiene zona asignada | Avisa al analista (ver Parte 2) |
| *Demasiados intentos inválidos* | Te equivocaste 3 veces eligiendo ruta | Empieza de nuevo con el código |
| *Tuve un problema procesando tu mensaje* | Falla temporal del sistema | Espera unos segundos y reenvía |
| *(sin respuesta)* | Tu número no está habilitado, o ya tienes planificación y el mensaje no se entendió | Escribe `AYUDA`; si sigue igual, contacta al analista |

## 10. Consejos

- **Un mensaje a la vez.** Si envías el mismo texto dos veces en menos de 2 segundos, el bot ignora el repetido.
- **La conversación vence a los 30 minutos sin actividad** (2 horas si respondes un recordatorio). Si vence, simplemente empieza de nuevo.
- **Revisa la fecha** del resumen antes de confirmar, sobre todo los lunes y sábados.
- **Cancelar siempre es seguro:** `cancelar` descarta lo pendiente y nunca borra una planificación ya guardada.

---

# Parte 2 — Guía del analista

## 1. Visión general

```
Supervisor ⇄ WhatsApp ⇄ WAHA (puente WhatsApp) ⇄ Aplicación (bot) ⇄ Google Sheets
```

- **Todo se guarda en un Google Sheet.** No hay base de datos adicional.
- El **Sheet es la fuente de verdad** de supervisores, rutas y planificaciones. El analista administra el sistema editando el Sheet; no hay panel aparte.
- La aplicación corre en Docker en un equipo local (ver sección 5).

## 2. Hojas del Google Sheet

> **Importante:** no renombres hojas ni columnas, no cambies su orden y no agregues columnas intermedias: el sistema las busca por nombre y posición.

### 2.1 `SUPERVISORES` — quién puede usar el bot

Fila 1, exactamente: `Nombre | Telefono | Sede | Zona | Activo | Ultimo_Recordatorio`

| Columna | Qué poner |
|---|---|
| `Nombre` | Nombre del supervisor, **tal como saldrá en los reportes** |
| `Telefono` | Su número de WhatsApp (8 dígitos locales; también acepta con 591) |
| `Sede` | `SCZ`, `CBBA` o `LPZ` |
| `Zona` | Exactamente igual a la columna `ZONA` de los maestros (ej. `N`) |
| `Activo` | `TRUE` para habilitar. Cualquier otro valor lo deja **sin acceso** |
| `Ultimo_Recordatorio` | **No editar.** Lo escribe el bot |

- **Alta:** agrega la fila completa con `Activo=TRUE`. No existe comando de auto-registro.
- **Baja temporal o definitiva:** cambia `Activo` a `FALSE`.
- Los cambios se aplican en **hasta 5 minutos** (caché de supervisores).
- Un supervisor sin `Zona` no puede usar `RUTA` ni acompañar vendedores (verá "Tu registro está incompleto").
- Se asume un supervisor por zona y por sede.

### 2.2 Maestros de rutas por sede

Una hoja por sede (nombres configurados en el sistema, p. ej. `PLANIFICACION_SCZ_RENOM`). Columnas que usa el bot: `RUTA`, `ZONA`, `DIA`, `VENDEDOR`, `CODIGO ERP`, `CODIGO RUTA`.

- `DIA` usa los códigos `1-LU`, `2-MA`, `3-MI`, `4-JU`, `5-VI`, `6-SA`.
- `LISTA` muestra solo filas de **la zona del supervisor** y del día planificado, **sin** rutas cuyo nombre contenga `MERC`, ordenadas por `CODIGO RUTA` (numéricamente).
- Si la celda `VENDEDOR` está vacía, la lista muestra "(sin vendedor)".
- Los cambios en los maestros se reflejan en **hasta 30 minutos** (o al reiniciar la aplicación).

### 2.3 `PLANIFICACION_DIARIA` — el resultado

Una fila por supervisor, sede y fecha de trabajo.

| Columna | Contenido |
|---|---|
| `ID_Registro` | Identificador único |
| `Fecha_Registro`, `Hora_Registro` | Cuándo se registró (o se registró por primera vez tras un escalamiento) |
| `Fecha_Trabajo` | Día planificado, formato `AAAA-MM-DD` |
| `Sede`, `Supervisor` | Quién planificó |
| `Modalidad` | `ACOMPAÑAMIENTO`, `RUTA`, `VENTA DIRECTA` u `OFICINA` |
| `Vendedor_Apoyo`, `Codigo_ERP_Vendedor` | Ver tabla siguiente |
| `Ruta_Oficial`, `Zona`, `Codigo_Ruta`, `DIA` | Datos de la ruta (`N/A` si no aplica) |
| `Estado` | Ver abajo |
| `Es_Cambio` | `TRUE` si reemplazó una planificación anterior del mismo día |
| `Observaciones` | Libre, para uso del analista |
| `ID_Mensaje_WA` | Mensaje de WhatsApp que originó el registro |

**Qué se guarda según la modalidad**

| Modalidad | `Vendedor_Apoyo` | `Codigo_ERP_Vendedor` | Datos de ruta |
|---|---|---|---|
| ACOMPAÑAMIENTO | Nombre del vendedor | Código del vendedor | Ruta del vendedor ese día |
| RUTA (por código de vendedor) | *(vacío)* | Código del vendedor | Ruta del vendedor ese día |
| RUTA (por código de ruta o lista) | *(vacío)* | `N/A` | Ruta elegida |
| VENTA DIRECTA | `VENTA DIRECTA` | `N/A` | `N/A` |
| OFICINA | `N/A` | `N/A` | `N/A` |

**Estados**

| Estado | Significado |
|---|---|
| `REGISTRADO` | Primera planificación confirmada del día |
| `MODIFICADO` | El supervisor la reemplazó (`Es_Cambio = TRUE`) |
| `PENDIENTE_ESCALADO` | **No planificó a tiempo.** Es una marca, no una planificación (`Modalidad = N/A`). Si el supervisor planifica después, esa misma fila pasa a `REGISTRADO` |
| `CANCELADO` | Fila anulada manualmente: el bot la ignora y el supervisor puede volver a planificar ese día |

Para **anular una planificación** escribe `CANCELADO` en `Estado`. No borres ni insertes filas a mano.

### 2.4 `LOG_BOT` — auditoría

Una fila por evento de supervisores autorizados (a los números desconocidos nunca se les registra nada). Columnas: `timestamp`, `telefono_resuelto`, `whatsapp_id`, `nombre`, `sede`, `wa_msg_id`, `mensaje_original`, `intencion`, `estado_antes`, `estado_despues`, `accion`, `resultado`, `error`, `detalles`.

| `accion` | `resultado` | Qué indica |
|---|---|---|
| `CONFIRM_PLANNING` | `SUCCESS` | Planificación registrada o actualizada |
| `CONFIRM_PLANNING` | `NO_CHANGES` | Confirmó algo idéntico a lo guardado; no se escribió nada |
| `REJECTED_WRONG_ZONE` | `REJECTED` | Intentó un vendedor de otra zona |
| `REJECTED_DUPLICATE_SELLER` | `REJECTED` | Vendedor ya tomado por otro supervisor ese día |
| `REJECTED_NO_ZONE` | `REJECTED` | Supervisor sin zona asignada |
| `IGNORED_ALREADY_REGISTERED` | `IGNORED` | Mensaje no entendido de alguien que ya planificó |

## 3. Reglas de negocio que aplica el bot

1. **Zona:** un supervisor solo puede elegir vendedores y rutas de su zona.
2. **Día:** el vendedor debe tener ruta en el día de trabajo. Si tiene varias, el supervisor elige una.
3. **Duplicados:** un mismo vendedor no puede ser registrado por dos supervisores el mismo día en la misma sede (al elegir por código de vendedor). Al elegir una ruta directamente (por código o lista) no se aplica, porque cada zona tiene un solo supervisor.
4. **Una planificación activa por supervisor y fecha:** una nueva la reemplaza (queda `MODIFICADO`); si es idéntica, no se escribe nada.

## 4. Calendario operativo

El equipo que ejecuta el bot se enciende el **lunes entre 08:00 y 08:30** y se apaga el **sábado a las 12:00**. Al arrancar, el sistema ejecuta un ciclo de recordatorios inmediato para recuperar lo que se perdió mientras estaba apagado.

| Día | Recordatorios | Cierre y escalamiento |
|---|---|---|
| Lunes AM | 08:00 – 12:00, para **hoy** | 12:00: marca `PENDIENTE_ESCALADO` y avisa al administrador |
| Lunes PM | 15:00 – 18:00, para **martes** | 18:00: ídem |
| Martes a viernes | 15:00 – 18:00, para el día siguiente | 18:00: ídem |
| Sábado | 08:00 – 11:30, para **hoy** | **Sin escalamiento** (el equipo se apaga a las 12:00) |
| Domingo | — | — |

- El ciclo corre cada 30 minutos en punto; cada supervisor recibe **como máximo 1 recordatorio por hora** y ninguno si escribió hace menos de 10 minutos. El último del sábado (11:30) ignora el límite horario.
- El escalamiento ocurre **una sola vez por supervisor y día**. El administrador recibe un WhatsApp como este:

```
⚠️ PLANIFICACIÓN PENDIENTE

• Carlos Mendoza (SCZ)
• Maria Suarez (CBBA)

Fecha de trabajo: 15/09/2026
```

- Quien figure como `PENDIENTE_ESCALADO` **sigue recibiendo recordatorios** (cuando corresponda) y puede planificar con normalidad.

## 5. Operación diaria

**Rutina sugerida**

1. Lunes ~08:00: encender el equipo y verificar que Docker y WAHA estén arriba.
2. Comprobar `http://localhost:8000/health` (debe responder `status: ok` y `sheets: connected`).
3. Durante la ventana de la tarde, revisar `PLANIFICACION_DIARIA` filtrando por la `Fecha_Trabajo` del día siguiente.
4. Atender los avisos de *PLANIFICACIÓN PENDIENTE* contactando al supervisor.
5. Sábado antes de las 12:00: verificar que no queden pendientes críticos.

**Comandos útiles** (desde la carpeta del proyecto)

| Acción | Comando |
|---|---|
| Ver estado de los servicios | `docker compose ps` |
| Ver el log en vivo | `docker compose logs -f app` |
| Reiniciar la aplicación | `docker compose restart app` |
| Levantar todo | `docker compose up -d` |

- Si **WhatsApp se desconecta**, abre el panel de WAHA (`http://localhost:3000/dashboard`) y vuelve a escanear el QR con el teléfono del bot (pasos en el `README.md`).
- Reiniciar la aplicación **borra las conversaciones en curso**: los supervisores solo deben reenviar su último mensaje. Las planificaciones ya confirmadas no se pierden.

**Reglas de oro**

- Ejecutar **una sola instancia** del bot: dos a la vez duplican avisos y filas.
- Evitar ordenar, insertar o borrar filas de `PLANIFICACION_DIARIA` mientras los supervisores están registrando (usa **filtros o vistas de filtro**, no ordenamientos). Editar celdas está bien.
- Mantener el número de WhatsApp del bot dedicado a este sistema.

## 6. Parámetros ajustables

Se cambian en el archivo `.env` y requieren reiniciar la aplicación. Valores recomendados para producción:

| Variable | Valor | Para qué sirve |
|---|---|---|
| `REMINDER_INTERVAL_MINUTES` | `30` | Cada cuántos minutos corre el ciclo (debe dividir 60) |
| `REMINDER_COOLDOWN_MINUTES` | `60` | Mínimo entre recordatorios al mismo supervisor |
| `REMINDER_ACTIVITY_WINDOW_MINUTES` | `10` | No recordar a quien acaba de escribir |
| `MONDAY_AM_*`, `MONDAY_PM_*`, `WEEKDAY_PM_*`, `SATURDAY_AM_*` | ver `.env.example` | Horarios de recordatorio y escalamiento |
| `CONVERSATION_TTL_MINUTES` | `30` | Cuánto dura una conversación inactiva |
| `REMINDER_MENU_TTL_MINUTES` | `120` | Cuánto sigue abierto el menú de un recordatorio |
| `ADMIN_PHONE` | 8 dígitos | Quién recibe los avisos de escalamiento |

Para pruebas se puede bajar `REMINDER_COOLDOWN_MINUTES` a `1`; **no olvidar devolverlo a `60`**.

## 7. Solución de problemas

| Síntoma | Causa probable | Qué revisar o hacer |
|---|---|---|
| Un supervisor dice que el bot no le responde | Número no habilitado, `Activo` distinto de `TRUE`, o teléfono mal escrito | Revisar la fila en `SUPERVISORES` (esperar hasta 5 min tras editar) |
| "Tu registro está incompleto" | `Zona` vacía | Completar `Zona` |
| "No encontré ningún vendedor / ruta" para un código válido | El maestro cambió hace poco, o el vendedor no tiene ruta ese día | Esperar hasta 30 min o reiniciar la app; verificar `DIA` y `ZONA` en el maestro |
| La LISTA sale vacía | No hay filas de esa zona y día | Revisar `ZONA` y `DIA` del maestro |
| Un supervisor quedó "escalado" pero sí planificó | Planificó después del cierre | Normal: su fila pasa a `REGISTRADO` al confirmar |
| No llegan recordatorios | Fuera de horario, equipo apagado, WhatsApp desconectado, o el supervisor ya planificó o escribió hace poco | Revisar el calendario (sección 4) y `docker compose logs -f app` |
| No llegan los avisos al administrador | `ADMIN_PHONE` incorrecto o WhatsApp desconectado | Revisar `.env` y el panel de WAHA |
| En el log aparece `Retry 1/3 … after 429` | Google Sheets limitó temporalmente las consultas | Suele resolverse solo; si es frecuente, reducir la actividad manual sobre el Sheet |
| `health` muestra `sheets: disconnected` | Credenciales o ID del Sheet incorrectos, o sin permiso | Verificar que la cuenta de servicio sea **Editor** del Sheet |
| Aparece "Tuve un problema procesando tu mensaje" | Error puntual del sistema | Buscar `Failed message` en el log; el supervisor puede reintentar |

**Cómo leer el log:** cada mensaje deja `Processing message from <teléfono> id=…` y luego `Finished message … in N.Ns` o `Failed message … : <error>`. Los recordatorios dejan `Dispatched reminder to <nombre>`.

## 8. Contacto y alcance

Este manual describe el comportamiento vigente del sistema. Ante cualquier duda sobre datos o accesos, el analista de turno es el primer punto de contacto del supervisor; los cambios de configuración del servidor (`.env`, Docker, WhatsApp) los realiza únicamente el responsable técnico.
