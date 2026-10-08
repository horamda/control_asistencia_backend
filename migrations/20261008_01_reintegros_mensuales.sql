CREATE TABLE IF NOT EXISTS reintegro_config (
 empresa_id INT PRIMARY KEY, revision INT NOT NULL DEFAULT 0,
 FOREIGN KEY (empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_sectores (
 empresa_id INT NOT NULL, sector_id INT NOT NULL,
 PRIMARY KEY(empresa_id,sector_id), FOREIGN KEY(empresa_id) REFERENCES empresas(id),
 FOREIGN KEY(sector_id) REFERENCES sectores(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_odometros (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, solicitud_id BIGINT NOT NULL,
 revision_carga INT NOT NULL, activo TINYINT NOT NULL DEFAULT 1,
 contenido MEDIUMBLOB NOT NULL, sha256 CHAR(64) NOT NULL,
 KEY ix_reintegro_odometro(solicitud_id,activo),
 FOREIGN KEY(solicitud_id) REFERENCES reintegro_solicitudes(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_recordatorios (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, empleado_id INT NOT NULL,
 periodo DATE NOT NULL, mensaje VARCHAR(500) NOT NULL, creado_at DATETIME NOT NULL, leido_at DATETIME NULL,
 UNIQUE KEY uq_reintegro_recordatorio(empresa_id,empleado_id,periodo),
 KEY ix_reintegro_recordatorio_personal(empleado_id,leido_at),
 FOREIGN KEY(empleado_id) REFERENCES empleados(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
