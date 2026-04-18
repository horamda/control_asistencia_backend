-- Migracion: tabla adelantos
-- Fecha: 2026-04-17

CREATE TABLE IF NOT EXISTS adelantos (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  periodo_year SMALLINT NOT NULL,
  periodo_month TINYINT UNSIGNED NOT NULL,
  fecha_solicitud DATE NOT NULL,
  estado ENUM('pendiente', 'aprobado', 'rechazado', 'cancelado') NOT NULL DEFAULT 'pendiente',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_adelantos_empleado_periodo (empleado_id, periodo_year, periodo_month),
  KEY idx_adelantos_empresa_periodo (empresa_id, periodo_year, periodo_month),
  KEY idx_adelantos_estado (estado),
  CONSTRAINT fk_adelantos_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_adelantos_empleado_empresa FOREIGN KEY (empleado_id, empresa_id)
    REFERENCES empleados (id, empresa_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
