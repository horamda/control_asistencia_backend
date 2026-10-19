# Gestión de jornada laboral — etapa A (reglas, convenios y condiciones laborales)

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

## Pendiente (etapas siguientes)

| Etapa | Contenido |
|---|---|
| B | Motor de cálculo desde los fichajes (solo lectura): horas programadas, trabajadas, ordinarias, excedentes, nocturnas, faltantes; resumen de horas, indicadores y reporte. Resultados guardados con la versión de regla usada. |
| C | Horas extras al 50 % y al 100 % (franjas y feriados), autorización, estados (pendiente, aprobada, rechazada, liquidada, compensada), cierre de período mensual y exportación para liquidación. |
| D | Banco de horas: acuerdos, libro de movimientos inmutable con reversiones, compensatorios y cierre. |

**Decisión pendiente antes de la etapa B:** los turnos que cruzan la medianoche. Hoy el egreso automático cierra las
jornadas abiertas a las 23:59 y las marcas se guardan por fecha. Si hay personal nocturno, habrá que excluirlo del
egreso automático para que el motor empareje el ingreso de un día con el egreso del siguiente.
