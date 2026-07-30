-- Migracion: Feedback por sector responsable.
-- Compatible con MySQL sin ADD COLUMN IF NOT EXISTS.
-- Puede ejecutarse completa aunque algunas columnas, indices o constraints ya existan.
-- Funciona con SQL_SAFE_UPDATES activo.

SET @schema_name := DATABASE();

-- feedback_motivos: plazo y requisitos de carga.
SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedback_motivos ADD COLUMN tiempo_resolucion_valor INT NOT NULL DEFAULT 1 AFTER sla_dias',
    'SELECT ''skip feedback_motivos.tiempo_resolucion_valor'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedback_motivos'
    AND COLUMN_NAME = 'tiempo_resolucion_valor'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedback_motivos ADD COLUMN tiempo_resolucion_unidad VARCHAR(10) NOT NULL DEFAULT ''DIAS'' AFTER tiempo_resolucion_valor',
    'SELECT ''skip feedback_motivos.tiempo_resolucion_unidad'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedback_motivos'
    AND COLUMN_NAME = 'tiempo_resolucion_unidad'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedback_motivos ADD COLUMN requiere_foto TINYINT(1) NOT NULL DEFAULT 0 AFTER tiempo_resolucion_unidad',
    'SELECT ''skip feedback_motivos.requiere_foto'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedback_motivos'
    AND COLUMN_NAME = 'requiere_foto'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedback_motivos ADD COLUMN requiere_observacion TINYINT(1) NOT NULL DEFAULT 1 AFTER requiere_foto',
    'SELECT ''skip feedback_motivos.requiere_observacion'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedback_motivos'
    AND COLUMN_NAME = 'requiere_observacion'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedback_motivos ADD INDEX idx_feedback_motivos_tiempo (tiempo_resolucion_unidad, tiempo_resolucion_valor)',
    'SELECT ''skip idx_feedback_motivos_tiempo'' AS info'
  )
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedback_motivos'
    AND INDEX_NAME = 'idx_feedback_motivos_tiempo'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE feedback_motivos
SET tiempo_resolucion_valor = COALESCE(NULLIF(sla_dias, 0), 1),
    tiempo_resolucion_unidad = 'DIAS'
WHERE id >= 0
  AND (tiempo_resolucion_valor IS NULL OR tiempo_resolucion_valor <= 0);

-- feedbacks: snapshots de sector/responsable y fecha limite con hora.
SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedbacks ADD COLUMN numero VARCHAR(30) NULL AFTER id',
    'SELECT ''skip feedbacks.numero'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND COLUMN_NAME = 'numero'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedbacks ADD COLUMN sector_origen_id INT NULL AFTER empleado_id',
    'SELECT ''skip feedbacks.sector_origen_id'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND COLUMN_NAME = 'sector_origen_id'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedbacks ADD COLUMN sucursal_id INT NULL AFTER sector_origen_id',
    'SELECT ''skip feedbacks.sucursal_id'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND COLUMN_NAME = 'sucursal_id'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedbacks ADD COLUMN sector_responsable_id INT NULL AFTER motivo_id',
    'SELECT ''skip feedbacks.sector_responsable_id'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND COLUMN_NAME = 'sector_responsable_id'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedbacks ADD COLUMN responsable_id INT NULL AFTER sector_responsable_id',
    'SELECT ''skip feedbacks.responsable_id'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND COLUMN_NAME = 'responsable_id'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(
    COUNT(*) = 0,
    'ALTER TABLE feedbacks ADD COLUMN fecha_limite DATETIME NULL AFTER fecha_vencimiento',
    'SELECT ''skip feedbacks.fecha_limite'' AS info'
  )
  FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = @schema_name
    AND TABLE_NAME = 'feedbacks'
    AND COLUMN_NAME = 'fecha_limite'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD INDEX idx_feedbacks_numero (numero)', 'SELECT ''skip idx_feedbacks_numero'' AS info')
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND INDEX_NAME = 'idx_feedbacks_numero'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD INDEX idx_feedbacks_sector_origen (sector_origen_id)', 'SELECT ''skip idx_feedbacks_sector_origen'' AS info')
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND INDEX_NAME = 'idx_feedbacks_sector_origen'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD INDEX idx_feedbacks_sucursal_scope (sucursal_id)', 'SELECT ''skip idx_feedbacks_sucursal_scope'' AS info')
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND INDEX_NAME = 'idx_feedbacks_sucursal_scope'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD INDEX idx_feedbacks_sector_responsable (sector_responsable_id)', 'SELECT ''skip idx_feedbacks_sector_responsable'' AS info')
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND INDEX_NAME = 'idx_feedbacks_sector_responsable'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD INDEX idx_feedbacks_responsable (responsable_id)', 'SELECT ''skip idx_feedbacks_responsable'' AS info')
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND INDEX_NAME = 'idx_feedbacks_responsable'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD INDEX idx_feedbacks_fecha_limite (fecha_limite)', 'SELECT ''skip idx_feedbacks_fecha_limite'' AS info')
  FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND INDEX_NAME = 'idx_feedbacks_fecha_limite'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD CONSTRAINT fk_feedbacks_sector_origen FOREIGN KEY (sector_origen_id) REFERENCES sectores(id) ON DELETE SET NULL', 'SELECT ''skip fk_feedbacks_sector_origen'' AS info')
  FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND CONSTRAINT_NAME = 'fk_feedbacks_sector_origen'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD CONSTRAINT fk_feedbacks_sucursal_scope FOREIGN KEY (sucursal_id) REFERENCES sucursales(id) ON DELETE SET NULL', 'SELECT ''skip fk_feedbacks_sucursal_scope'' AS info')
  FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND CONSTRAINT_NAME = 'fk_feedbacks_sucursal_scope'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD CONSTRAINT fk_feedbacks_sector_responsable FOREIGN KEY (sector_responsable_id) REFERENCES sectores(id) ON DELETE SET NULL', 'SELECT ''skip fk_feedbacks_sector_responsable'' AS info')
  FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND CONSTRAINT_NAME = 'fk_feedbacks_sector_responsable'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (
  SELECT IF(COUNT(*) = 0, 'ALTER TABLE feedbacks ADD CONSTRAINT fk_feedbacks_responsable FOREIGN KEY (responsable_id) REFERENCES empleados(id) ON DELETE SET NULL', 'SELECT ''skip fk_feedbacks_responsable'' AS info')
  FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = @schema_name AND TABLE_NAME = 'feedbacks' AND CONSTRAINT_NAME = 'fk_feedbacks_responsable'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE feedbacks f
JOIN empleados e ON e.id = f.empleado_id
JOIN feedback_motivos m ON m.id = f.motivo_id
SET f.sector_origen_id = COALESCE(f.sector_origen_id, e.sector_id),
    f.sucursal_id = COALESCE(f.sucursal_id, e.sucursal_id),
    f.sector_responsable_id = COALESCE(f.sector_responsable_id, m.sector_id),
    f.responsable_id = COALESCE(f.responsable_id, f.jefe_directo_id),
    f.fecha_limite = COALESCE(f.fecha_limite, TIMESTAMP(f.fecha_vencimiento, '23:59:59')),
    f.numero = COALESCE(f.numero, CONCAT('FB-', LPAD(f.id, 8, '0')))
WHERE f.id >= 0;

UPDATE feedbacks
SET estado = 'pendiente'
WHERE id >= 0
  AND estado IN ('en_proceso', 'vencido');
