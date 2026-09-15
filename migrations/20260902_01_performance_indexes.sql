-- Indices de performance para navegacion del panel, planilla diaria y mobile.
-- Compatible con MySQL sin CREATE INDEX IF NOT EXISTS.

SET @schema_name = DATABASE();

-- asistencias: listados por fecha, empleado+fecha y planilla diaria.
SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'asistencias'
    AND INDEX_NAME = 'idx_asistencias_fecha_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_asistencias_fecha_id ON asistencias (fecha, id)',
  'SELECT ''skip idx_asistencias_fecha_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'asistencias'
    AND INDEX_NAME = 'idx_asistencias_empresa_fecha_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_asistencias_empresa_fecha_id ON asistencias (empresa_id, fecha, id)',
  'SELECT ''skip idx_asistencias_empresa_fecha_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'asistencias'
    AND INDEX_NAME = 'idx_asistencias_empleado_fecha_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_asistencias_empleado_fecha_id ON asistencias (empleado_id, fecha, id)',
  'SELECT ''skip idx_asistencias_empleado_fecha_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- asistencia_marcas: export/historial admin y ultima marca del empleado.
SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'asistencia_marcas'
    AND INDEX_NAME = 'idx_am_empresa_fecha_hora_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_am_empresa_fecha_hora_id ON asistencia_marcas (empresa_id, fecha, hora, id)',
  'SELECT ''skip idx_am_empresa_fecha_hora_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'asistencia_marcas'
    AND INDEX_NAME = 'idx_am_fecha_hora_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_am_fecha_hora_id ON asistencia_marcas (fecha, hora, id)',
  'SELECT ''skip idx_am_fecha_hora_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'asistencia_marcas'
    AND INDEX_NAME = 'idx_am_asistencia_accion'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_am_asistencia_accion ON asistencia_marcas (asistencia_id, accion)',
  'SELECT ''skip idx_am_asistencia_accion'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- empleados: filtros del panel por empresa/sucursal/sector/jefe y control de asistencia.
SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'empleados'
    AND INDEX_NAME = 'idx_empleados_empresa_sucursal_sector'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_empleados_empresa_sucursal_sector ON empleados (empresa_id, sucursal_id, sector_id, activo)',
  'SELECT ''skip idx_empleados_empresa_sucursal_sector'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'empleados'
    AND INDEX_NAME = 'idx_empleados_reporta_empresa'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_empleados_reporta_empresa ON empleados (reporta_a_empleado_id, empresa_id, activo)',
  'SELECT ''skip idx_empleados_reporta_empresa'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Notificaciones globales del panel: COUNT(*) pendientes.
SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'justificaciones'
    AND INDEX_NAME = 'idx_justificaciones_estado'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_justificaciones_estado ON justificaciones (estado)',
  'SELECT ''skip idx_justificaciones_estado'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND INDEX_NAME = 'idx_vac_mov_estado_pendientes'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_vac_mov_estado_pendientes ON vacaciones_movimientos (estado, revertido_por_movimiento_id, origen_movimiento_id)',
  'SELECT ''skip idx_vac_mov_estado_pendientes'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'adelantos'
    AND INDEX_NAME = 'idx_adelantos_estado_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_adelantos_estado_id ON adelantos (estado, id)',
  'SELECT ''skip idx_adelantos_estado_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'pedidos_mercaderia'
    AND INDEX_NAME = 'idx_pedidos_mercaderia_estado_id'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_pedidos_mercaderia_estado_id ON pedidos_mercaderia (estado, id)',
  'SELECT ''skip idx_pedidos_mercaderia_estado_id'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- feedback: listados, dashboard y filtros frecuentes.
SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_empresa_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_empresa_created ON feedbacks (empresa_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_empresa_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_estado_fecha_limite'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_estado_fecha_limite ON feedbacks (estado, fecha_limite, fecha_vencimiento)',
  'SELECT ''skip idx_feedbacks_estado_fecha_limite'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_empleado_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_empleado_created ON feedbacks (empleado_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_empleado_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_jefe_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_jefe_created ON feedbacks (jefe_directo_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_jefe_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_responsable_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_responsable_created ON feedbacks (responsable_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_responsable_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_sector_origen_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_sector_origen_created ON feedbacks (sector_origen_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_sector_origen_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_sector_responsable_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_sector_responsable_created ON feedbacks (sector_responsable_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_sector_responsable_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND INDEX_NAME = 'idx_feedbacks_sucursal_created'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_feedbacks_sucursal_created ON feedbacks (sucursal_id, created_at, id)',
  'SELECT ''skip idx_feedbacks_sucursal_created'' AS info'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
