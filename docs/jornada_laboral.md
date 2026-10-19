# Gestión de jornada laboral — etapas A (reglas), B (cálculo de horas) y C (horas extras y cierre)

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
| Recargo de horas extras en días hábiles y en descanso/feriados (%), y hora del sábado desde la que corre el de descanso | — |
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

## Etapa C — horas extras y cierre del mes (Asistencia → Horas extras)

| Pantalla | Ruta | Para qué |
|---|---|---|
| Bandeja | `/horas-extras/?mes=AAAA-MM` | Días con excedente: "Para decidir", todas, aprobadas, rechazadas, liquidadas; acción en lote |
| Día | `/horas-extras/dia/{empleado}/{fecha}` | Fichadas, propuesta, acumulado contra topes, decisión e historial |
| Cierre del mes | `/horas-extras/cierre?mes=AAAA-MM` | Lo que falta para cerrar, cerrar, reabrir y exportar la liquidación |

**El excedente nunca se vuelve hora extra solo.**
1. **Propuesta:** el sistema propone el reparto (LCT art. 201).
   - Se toman como extra los últimos minutos trabajados del día.
   - Cada tramo se clasifica según el momento en que ocurrió:
     - recargo de descanso: domingos, feriados y sábado desde la hora de la regla;
     - recargo hábil: el resto.
   - Valores de la LCT: 50 %, 100 % y sábado desde las 13. Cada convenio los puede cambiar en su regla.
2. **Visto bueno del jefe:** un usuario del panel vinculado a un empleado da el visto bueno o rechaza los días de su cadena de reportes. Es la misma cadena que en Vacaciones: si no tiene jefe y tiene reportes, ve a toda la empresa. Nunca decide sobre sus propias horas.
3. **Decisión de RR. HH.** (rol admin o rrhh): aprueba (puede ser menos de lo propuesto) o rechaza. Puede decidir sin visto bueno del jefe, y queda registrado.

| Estado | Significado |
|---|---|
| Pendiente del jefe | Sin decisión (no hay fila: sale en vivo del cálculo) |
| Con visto bueno del jefe / Rechazada por el jefe | Espera la decisión de RR. HH. |
| Aprobada / Rechazada | Decidido por RR. HH. |
| Liquidada | Aprobada y con el mes cerrado |

- **Rechazar** pide motivo.
- **Topes:** si al aprobar se supera el tope mensual o anual de horas extras de la regla, hay que confirmar y escribir el motivo. Queda marcado como "supera tope". Al jefe solo se le avisa.
- **Fichajes corregidos:** si los fichajes cambian después de una decisión, el día lo avisa.
- **Trazabilidad:** cada paso queda en `jl_horas_extra_eventos`, que solo se inserta. Los recargos vigentes se guardan con la decisión.

### Cierre del mes

- **Para cerrar hace falta:**
  - que el mes haya terminado;
  - que no haya días con fichadas a revisar (se corrigen en Asistencia);
  - que no queden excedentes sin decisión de RR. HH.;
  - que ninguna aprobación supere lo que hoy marcan los fichajes.
- **Al cerrar:**
  - se registra el cálculo del mes (foto de la etapa B);
  - lo aprobado pasa a "liquidada";
  - el mes no admite cambios.
- **Reabrir:** pide motivo. Lo liquidado vuelve a "aprobada" y la reapertura queda registrada; la foto del cierre anterior se conserva.
- **Liquidación (Excel):** sale de la foto del cierre.
  - Hoja *Liquidación*, una fila por empleado: legajo, DNI, sucursal, horas extras hábiles y de descanso con su recargo, nocturnas, feriados trabajados, ausencias injustificadas, días de licencia y horas trabajadas.
  - Hoja *Horas extras por día*.

### Tablas y permisos de la etapa C

- **Migración:** `scripts/migrate_20261019_03_horas_extras.py`, versión `20261019_horas_extras`.
  - **Tablas:** crea `jl_horas_extra`, `jl_horas_extra_eventos` y `jl_periodos`.
  - **Columnas:** agrega tres a `jl_reglas`.
  - **Valores de la ley:** completa la regla de carga inicial de la LCT con 50 %, 100 % y sábado desde las 13.
  - **Reversión:** DROP de las tres tablas y de las tres columnas, y borrar la versión de `app_schema_versions`.
- **Permiso `horas_extras`** (por defecto admin y RR. HH.):

| Acción | Habilita |
|---|---|
| `ver` | Bandeja y días |
| `aprobar` | Jefe: visto bueno de su cadena. RR. HH.: decisión. |
| `editar` | RR. HH.: cerrar y reabrir el mes |
| `exportar` | RR. HH.: liquidación |

  Para que un jefe participe necesita un usuario del panel **vinculado a su empleado** con `ver` y `aprobar` en este módulo.

## Pendiente (etapas siguientes)

| Etapa | Contenido |
|---|---|
| D | Banco de horas: acuerdos, libro de movimientos inmutable con reversiones, compensatorios y cierre. |

**Decisión pendiente: turnos que cruzan la medianoche.**
- **El motor ya los empareja:** un ingreso a las 22:00 con egreso a las 06:00 del día siguiente cuenta 8 h para el
  día del ingreso.
- **El egreso automático no se cambió.** Corre a las 03:30 y cierra el turno nocturno todavía abierto, así que ese día
  queda "a revisar" y el egreso real queda sin pareja.
- **Si hay personal nocturno:** habrá que excluirlo del egreso automático, o que corra después del fin de su turno.
