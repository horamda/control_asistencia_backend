-- Migracion: vacaciones_movimientos como fuente principal de vacaciones
-- Fecha: 2026-05-19

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND COLUMN_NAME = 'motivo_resolucion'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE vacaciones_movimientos ADD COLUMN motivo_resolucion VARCHAR(255) NULL AFTER estado',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND COLUMN_NAME = 'resuelto_by'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE vacaciones_movimientos ADD COLUMN resuelto_by INT NULL AFTER motivo_resolucion',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND COLUMN_NAME = 'resuelto_at'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE vacaciones_movimientos ADD COLUMN resuelto_at DATETIME NULL AFTER resuelto_by',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND COLUMN_NAME = 'origen_movimiento_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE vacaciones_movimientos ADD COLUMN origen_movimiento_id BIGINT UNSIGNED NULL AFTER resuelto_at',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND COLUMN_NAME = 'revertido_por_movimiento_id'
);
SET @sql := IF(
  @col_exists = 0,
  'ALTER TABLE vacaciones_movimientos ADD COLUMN revertido_por_movimiento_id BIGINT UNSIGNED NULL AFTER origen_movimiento_id',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND INDEX_NAME = 'idx_vac_mov_periodos_aprobados'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_vac_mov_periodos_aprobados ON vacaciones_movimientos (tipo, estado, fecha_desde, fecha_hasta)',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND INDEX_NAME = 'idx_vac_mov_origen'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_vac_mov_origen ON vacaciones_movimientos (origen_movimiento_id)',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'vacaciones_movimientos'
    AND INDEX_NAME = 'idx_vac_mov_revertido'
);
SET @sql := IF(
  @idx_exists = 0,
  'CREATE INDEX idx_vac_mov_revertido ON vacaciones_movimientos (revertido_por_movimiento_id)',
  'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

INSERT INTO vacaciones_movimientos
(
  empleado_id,
  empresa_id,
  anio,
  tipo,
  dias,
  observacion,
  fecha_desde,
  fecha_hasta,
  estado,
  origen_movimiento_id,
  revertido_por_movimiento_id
)
SELECT
  v.empleado_id,
  COALESCE(v.empresa_id, e.empresa_id) AS empresa_id,
  YEAR(v.fecha_desde) AS anio,
  'tomado' AS tipo,
  DATEDIFF(v.fecha_hasta, v.fecha_desde) + 1 AS dias,
  NULLIF(v.observaciones, '') AS observacion,
  v.fecha_desde,
  v.fecha_hasta,
  'aprobado' AS estado,
  NULL AS origen_movimiento_id,
  NULL AS revertido_por_movimiento_id
FROM vacaciones v
JOIN empleados e ON e.id = v.empleado_id
WHERE v.fecha_desde IS NOT NULL
  AND v.fecha_hasta IS NOT NULL
  AND v.fecha_desde <= v.fecha_hasta
  AND COALESCE(v.empresa_id, e.empresa_id) IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM vacaciones_movimientos vm
    WHERE vm.empleado_id = v.empleado_id
      AND vm.tipo = 'tomado'
      AND vm.fecha_desde = v.fecha_desde
      AND vm.fecha_hasta = v.fecha_hasta
      AND vm.estado IN ('pendiente', 'aprobado')
    LIMIT 1
  );
