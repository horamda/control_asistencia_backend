-- Migracion: KPIs sectoriales con objetivos anuales y resultados por empleado
-- Fecha: 2026-04-19

CREATE TABLE IF NOT EXISTS kpis_definicion (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  codigo VARCHAR(64) NOT NULL,
  nombre VARCHAR(120) NOT NULL,
  descripcion VARCHAR(255) NULL,
  unidad VARCHAR(60) NOT NULL,
  tipo_acumulacion ENUM('suma', 'promedio', 'ultimo') NOT NULL DEFAULT 'suma',
  mayor_es_mejor TINYINT(1) NOT NULL DEFAULT 1,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_kpis_definicion_empresa_codigo (empresa_id, codigo),
  KEY idx_kpis_definicion_empresa_activo (empresa_id, activo),
  CONSTRAINT fk_kpis_definicion_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS kpis_sector_objetivo (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  sector_id INT NOT NULL,
  kpi_id INT UNSIGNED NOT NULL,
  anio SMALLINT NOT NULL,
  objetivo_valor DECIMAL(14,4) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_kpis_sector_objetivo (sector_id, kpi_id, anio),
  KEY idx_kpis_sector_objetivo_empresa_anio (empresa_id, anio),
  KEY idx_kpis_sector_objetivo_kpi (kpi_id),
  CONSTRAINT fk_kpis_sector_obj_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_kpis_sector_obj_sector FOREIGN KEY (sector_id) REFERENCES sectores (id),
  CONSTRAINT fk_kpis_sector_obj_kpi FOREIGN KEY (kpi_id) REFERENCES kpis_definicion (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS kpis_empleado_resultado (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  empresa_id INT NOT NULL,
  empleado_id INT NOT NULL,
  kpi_id INT UNSIGNED NOT NULL,
  fecha DATE NOT NULL,
  valor DECIMAL(14,4) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_kpis_empleado_resultado (empleado_id, kpi_id, fecha),
  KEY idx_kpis_empleado_resultado_empresa_fecha (empresa_id, fecha),
  KEY idx_kpis_empleado_resultado_kpi_fecha (kpi_id, fecha),
  CONSTRAINT fk_kpis_emp_res_empresa FOREIGN KEY (empresa_id) REFERENCES empresas (id),
  CONSTRAINT fk_kpis_emp_res_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id),
  CONSTRAINT fk_kpis_emp_res_kpi FOREIGN KEY (kpi_id) REFERENCES kpis_definicion (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
