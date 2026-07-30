CREATE TABLE IF NOT EXISTS asistencia_dias_no_laborables (
    id INT AUTO_INCREMENT PRIMARY KEY,
    empresa_id INT NOT NULL DEFAULT 0,
    sucursal_id INT NOT NULL DEFAULT 0,
    sector_id INT NOT NULL DEFAULT 0,
    fecha DATE NOT NULL,
    motivo VARCHAR(255) NULL,
    created_by_usuario_id INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_asistencia_no_laborable_scope_fecha (empresa_id, sucursal_id, sector_id, fecha),
    KEY idx_asistencia_no_laborable_fecha (fecha),
    KEY idx_asistencia_no_laborable_scope (empresa_id, sucursal_id, sector_id)
);
