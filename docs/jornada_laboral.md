# Gestión de jornada laboral — etapas A (reglas y convenios) y B (cálculo de horas)

Módulo del **panel web**. No modifica la API mobile, la app Flutter, ni ninguna tabla o fichaje existente. Todo se
escribe por rutas del panel (sesión, CSRF y permiso `jornada_laboral`), nunca desde el navegador a la base.

## Qué incluye la etapa A

| Pantalla | Ruta | Para qué |
|---|---|---|
| Reglas generales | `/jornada-laboral/reglas` | Regla de la empresa y de cada sucursal, con versiones |
| Convenios y acuerdos | `/jornada-laboral/convenios` | Alta, datos y regla (topes) de cada convenio |
| Asignar convenio | `/jornada-laboral/asignaciones` | Asignación masiva por filtros (sucursal, sector, puesto, convenio) |
| Condiciones laborales | `/jornada-laboral/empleado/{id}` | Jornada efectiva con el origen de cada valor, horario, convenio, condición individual e historial |
| Historial | `/jornada-laboral/historial` | Todas las versiones de reglas y asignaciones |

- **Menú:** Configuración → Jornada laboral.
- **Ficha del empleado** (Empleados → editar): resumen de condiciones laborales con enlace a la vista completa.
- **Horarios y feriados:** se enlazan, no se duplican.
  - Horarios y turnos son los de Horarios (plantillas, asignaciones y excepciones).
  - Los feriados son los del calendario de días no laborables (Asistencia → Reporte mensual).

## Modelo

- **Niveles**, del más general al más específico: **empresa → sucursal → convenio → empleado**. Para cada campo vale el
  nivel más específico **vigente en la fecha**; un campo vacío hereda del nivel superior.
- **Topes:** la regla del convenio del empleado (o la de *Fuera de convenio (LCT)* si no tiene convenio) fija los topes
  obligatorios: horas semanales, diarias, nocturnas y topes de horas extras por mes y por año. Una condición individual
  no puede superarlos: el sistema lo rechaza al guardar ("solo puede ser más favorable").
- **Versiones:** reglas y asignaciones nunca se editan. Una versión nueva cierra la anterior el día previo
  (`vigente_hasta`) y la referencia (`reemplaza_id`). No se puede cargar una versión que empiece antes que la vigente:
  el pasado no se reescribe.
- **Horario y descansos:** salen del horario asignado. Los descansos no computables son los huecos entre bloques, y el
  computable es un campo de la regla.
- **Tolerancias:** solo clasifican llegadas y salidas; **nunca cambian los minutos trabajados** (regla para la etapa B).

### Campos de una regla

| Campo | Es tope del convenio |
|---|---|
| Horas semanales y diarias pactadas | Sí |
| Días laborales (1 = lunes … 7 = domingo) | — |
| Régimen de distribución (diaria fija, semanal, promedio en un ciclo) | — |
| Descanso computable (min por jornada) | — |
| Tolerancias de ingreso y salida (min) | — |
| Jornada nocturna desde/hasta y horas nocturnas diarias | Horas nocturnas: sí |
| Trabaja en feriados | — |
| Tope de horas extras por mes y por año | Sí |
| Banco de horas habilitado (bandera; el libro de movimientos es la etapa D) | — |
| Observaciones | — |

### Carga inicial (cada empresa)

| Convenio | Valores |
|---|---|
| Fuera de convenio (LCT) | 48 h semanales, 8 diarias (Ley 11.544), nocturna de 21 a 6 con 7 h, 30 h extras por mes y 200 por año (Decreto 484/2000). **Valores de referencia: verificarlos con el asesor laboral.** |
| Camioneros (CCT 40/89) | Sin valores: completar según el convenio vigente. |
| SUTIAGA | Sin valores: completar según el convenio vigente. |

Hasta que se cargue la regla de un convenio, sus empleados no tienen topes de convenio.

**Nivel "Ley":** un campo que no define ningún nivel (empleado, convenio, sucursal ni empresa) toma el valor de la
regla de *Fuera de convenio (LCT)*. Por ejemplo, la franja nocturna de 21 a 6 aplica a todos si nadie la cambia. La
pantalla de condiciones muestra ese origen como "Ley".

## Tablas nuevas

| Tabla | Contenido |
|---|---|
| `jl_convenios` | Convenios y acuerdos de cada empresa (código, nombre, tipo, activo). |
| `jl_reglas` | Reglas por nivel (`alcance` = empresa, sucursal, convenio o empleado) con vigencia, valores, motivo, usuario y versión anterior. |
| `jl_asignaciones` | Convenio de cada empleado con vigencia, motivo, usuario y versión anterior. |

- **Migración:** `scripts/migrate_20261019_01_jornada_laboral.py`, versión `20261019_jornada_laboral` del bootstrap.
- **Qué hace:** solo crea tablas e inserta la carga inicial. Es idempotente.

**Reversión:**
1. Quitar el código.
2. `DROP TABLE jl_asignaciones, jl_reglas, jl_convenios;`
3. `DELETE FROM app_schema_versions WHERE version='20261019_jornada_laboral';`

Ningún dato existente depende de estas tablas.

## Permisos

Módulo `jornada_laboral` (Usuarios del panel → permisos), por defecto para admin y RR. HH.:

| Acción | Habilita |
|---|---|
| `ver` | Pantallas |
| `crear` | Convenios nuevos |
| `editar` | Reglas, datos de convenio y asignaciones |

Cada cambio queda en la auditoría.

## Etapa B — cálculo de horas (Asistencia → Horas trabajadas)

| Pantalla | Ruta | Para qué |
|---|---|---|
| Resumen | `/horas-jornada/?mes=AAAA-MM` | Indicadores y horas por empleado del mes, filtros por sucursal, sector y convenio |
| Detalle | `/horas-jornada/empleado/{id}?mes=AAAA-MM` | Día por día, subtotales semanales contra lo pactado y alertas |
| Registrar | `POST /horas-jornada/registrar` | Guarda una foto del cálculo del período |
| Exportar | `/horas-jornada/exportar?mes=…` | Excel con hojas *Resumen* y *Detalle diario* |

**Solo lectura sobre los fichajes.** El motor (`services/jornada_calculo_service.py`) lee `asistencia_marcas`,
horarios, excepciones, feriados, justificaciones aprobadas, vacaciones y francos, y nunca escribe en ellos.

### Cómo calcula (por empleado y día, en minutos)

| Concepto | Regla |
|---|---|
| Programadas | Bloques del horario asignado; las excepciones mandan (CAMBIO_HORARIO usa sus bloques; franco, vacaciones, feriado o licencia anulan). Sin horario: las horas diarias de su regla en sus días laborales. Feriado (si su regla no trabaja feriados), licencia o fuera de la relación laboral: 0. |
| Fichadas | Suma de pares ingreso → egreso. Un ingreso se empareja con el próximo egreso hasta **16 h** después, aunque sea al día siguiente, y el turno cuenta para el día del ingreso. |
| Trabajadas | Fichadas más el descanso computable de la regla (como máximo, lo que realmente descansó entre pares). |
| Excedente | Trabajadas − programadas. **No es hora extra**: no se clasifica ni se autoriza (etapa C). Un feriado o día no laborable trabajado es todo excedente. |
| Faltantes | Programadas − trabajadas en días laborables; en una ausencia, todo lo programado. |
| Ordinarias | Trabajadas − excedente. |
| Nocturnas | Minutos dentro de la franja nocturna de la regla. |

- **Las tolerancias no cambian minutos:** quien llega 5 min tarde con 10 de tolerancia tiene 5 min faltantes.
- **Por versión:** la regla se resuelve día por día. Si cambia la condición a mitad de mes, cada día usa la suya, y
  el registro guarda qué versiones (`jl_reglas.id`) usó cada día.
- **Altas y bajas:** entran los activos y los dados de baja dentro del período; los días fuera de la relación laboral
  no programan horas.

### Estados de un día

| Estado | Cuándo |
|---|---|
| Normal | Fichadas completas |
| A revisar | Fichada sin pareja, día cerrado por el **egreso automático**, o fichadas en un día de licencia o fuera de la relación laboral. Sin excedente ni faltante hasta que se corrija. |
| Ausente | Día programado sin fichadas ni licencia |
| Licencia o justificada | Justificación aprobada, vacaciones, franco o excepción que anula el horario |
| Día no laborable | Sin programación y sin fichadas |
| Día en curso o futuro | Hoy en adelante (no se decide todavía) |

**Alertas:**
- jornada de más de 12 h;
- más horas que las diarias pactadas;
- menos de 12 h de descanso entre jornadas (LCT, art. 197).

Los días a revisar no generan alertas de horas.

### Cálculo en vivo y cálculos registrados

- **En vivo:** las pantallas calculan en el momento.
- **Registrar:** guarda una foto (`jl_calculos` + `jl_resultados_dia`) con quién, cuándo, motivo, las versiones de
  regla y una **huella de las marcas** de cada día.
  - Registrar de nuevo crea otra foto; las anteriores se conservan.
  - El resumen avisa cuántos días tienen fichajes que cambiaron desde el último registro.

### Tablas y permisos de la etapa B

- **Migración:** `scripts/migrate_20261019_02_jornada_calculo.py`, versión `20261019_jornada_calculo`.
  - Solo crea `jl_calculos` y `jl_resultados_dia`.
  - Reversión: `DROP TABLE jl_resultados_dia, jl_calculos;` y borrar la versión de `app_schema_versions`.
- **Permiso `horas_jornada`** (por defecto admin y RR. HH.): `ver`, `editar` (registrar cálculo), `exportar` (Excel).

## Pendiente (etapas siguientes)

| Etapa | Contenido |
|---|---|
| C | Horas extras al 50 % y al 100 % (franjas y feriados), autorización, estados (pendiente, aprobada, rechazada, liquidada, compensada), cierre de período mensual y exportación para liquidación. |
| D | Banco de horas: acuerdos, libro de movimientos inmutable con reversiones, compensatorios y cierre. |

**Decisión pendiente: turnos que cruzan la medianoche.**
- **El motor ya los empareja:** un ingreso a las 22:00 con egreso a las 06:00 del día siguiente cuenta 8 h para el
  día del ingreso.
- **El egreso automático no se cambió.** Corre a las 03:30 y cierra el turno nocturno todavía abierto, así que ese día
  queda "a revisar" y el egreso real queda sin pareja.
- **Si hay personal nocturno:** habrá que excluirlo del egreso automático, o que corra después del fin de su turno.
