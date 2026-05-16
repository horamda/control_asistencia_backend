-- Migracion: puestos adicionales por empleado para organigrama
-- Fecha: 2026-05-16

CREATE TABLE IF NOT EXISTS empleado_puestos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT NOT NULL,
  empresa_id INT NOT NULL,
  sector_id INT NOT NULL,
  puesto_id INT NOT NULL,
  activo TINYINT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_empleado_puestos_unico (empleado_id, sector_id, puesto_id),
  KEY idx_empleado_puestos_empleado_activo (empleado_id, activo),
  KEY idx_empleado_puestos_sector_activo (sector_id, activo),
  KEY idx_empleado_puestos_puesto (puesto_id),
  CONSTRAINT fk_empleado_puestos_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id) ON DELETE CASCADE,
  CONSTRAINT fk_empleado_puestos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_empleado_puestos_sector FOREIGN KEY (sector_id) REFERENCES sectores (id),
  CONSTRAINT fk_empleado_puestos_puesto FOREIGN KEY (puesto_id) REFERENCES puestos (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
