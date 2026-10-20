# Contrato aditivo de preparación facial

Estado: código de preparación, activación bloqueada. No desplegado por esta tarea.

## GET /api/v1/mobile/me/config-asistencia

Autenticación y campos existentes sin cambios. Se añade `facial_policy`.
No es un permiso para fichar ni evidencia de identidad.

```json
{
  "schema_version": 1,
  "requested": {
    "mode": "disabled",
    "on_entry": true,
    "on_exit": true,
    "max_attempts": 3,
    "timeout_seconds": 30
  },
  "origins": {
    "mode": "default",
    "on_entry": "default",
    "on_exit": "default",
    "max_attempts": "default",
    "timeout_seconds": "default"
  },
  "revisions": {"company": 0, "branch": 0, "employee": 0},
  "effective_mode": "disabled",
  "capture_enabled": false,
  "activation_available": false,
  "activation_block_reason": "provider_and_authorization_not_validated",
  "configuration_status": "ok"
}
```

`requested` es un borrador resuelto. Modos: disabled/trial/required/risk.
Nunca usarlo para abrir cámara o bloquear asistencia. `origins` indica
default/company/branch/employee por campo. Las revisiones son contadores
administrativos, no tokens de autorización ni pruebas biométricas.

Ante borradores inválidos o relación empresa/sucursal inconsistente se
devuelven schema_version, effective_mode, capture_enabled,
activation_available, activation_block_reason y configuration_status=invalid,
sin exponer borradores de otra empresa.

Sin migración el resultado es disabled con defaults. La lectura de la
configuración actual no depende de que existan las columnas faciales.
Los errores generales de base de datos no se convierten en verificación exitosa.

## Edición administrativa

Se usan los POST existentes de editar empresa/sucursal/empleado, con CSRF
y action=save_facial_draft. Campos:

- facial_revision: revisión esperada; conflicto requiere recargar.
- facial_mode: disabled/trial/required/risk; inherit elimina la excepción.
- facial_on_entry y facial_on_exit: true/false/inherit.
- facial_max_attempts: entero 1–5, vacío hereda.
- facial_timeout_seconds: entero 10–120, vacío hereda.

Campos ausentes conservan el borrador anterior. Esto permite que formularios
anteriores guarden el modo sin borrar otros parámetros. Estos límites son
valores de preparación, no resultados de una evaluación biométrica.

Administrador activo de la empresa o administrador global. RRHH no obtiene
permiso facial por poder editar el legajo. La actualización y el evento de
auditoría se guardan juntos. No se cambian datos generales del registro.

## Compatibilidad Flutter

AttendanceConfig agrega el campo opcional con default seguro. El cache
existente preserva modo, origen de modo, parámetros y revisiones.
La ausencia del objeto es compatible con backends antiguos.

Esta versión no soporta captura. Una activación recibida se marca unsupported
localmente. Antes de activar cualquier política real se necesita implementar
el flujo, validar versiones mínimas y exigir autorización en todas las rutas
servidor. Un bloqueo local no impide evasión mediante clientes modificados.

## Migraciones y recuperación

Preparadas, no ejecutadas:

1. 20261020_01_facial_company_draft.sql
2. 20261020_02_facial_scope_drafts.sql

Aplicar primero en una base de pruebas con backup y comparar columnas.
MySQL DDL puede confirmar cada ALTER por separado; ante interrupción,
inspeccionar y aplicar sólo lo faltante. No se conectaron a bootstrap.

La recuperación operativa consiste en revertir las secciones y la proyección
de configuración, manteniendo columnas y auditoría. Los clientes anteriores
ignoran el JSON adicional. No borrar fichadas ni columnas para desactivar.
