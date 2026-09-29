-- Validacion de carga: snapshots historicos, fotos privadas y catalogos.
CREATE TABLE IF NOT EXISTS carga_camiones (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 sucursal_id INT NOT NULL,
 numero VARCHAR(40) NOT NULL,
 patente VARCHAR(20) NOT NULL,
 descripcion VARCHAR(200) NOT NULL DEFAULT '',
 activo TINYINT NOT NULL DEFAULT 1,
 UNIQUE KEY uq_carga_camion_numero (empresa_id, numero),
 UNIQUE KEY uq_carga_camion_patente (empresa_id, patente)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS carga_horarios (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 sucursal_id INT NULL,
 nombre VARCHAR(100) NOT NULL,
 tipo ENUM('inicial','recarga') NOT NULL,
 desde_minuto SMALLINT UNSIGNED NOT NULL,
 hasta_minuto SMALLINT UNSIGNED NOT NULL,
 vigente_desde DATE NOT NULL,
 vigente_hasta DATE NULL,
 activo TINYINT NOT NULL DEFAULT 1,
 KEY idx_carga_horario_scope (empresa_id, sucursal_id, tipo, activo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS carga_puestos (
 empresa_id INT NOT NULL,
 puesto_id INT NOT NULL,
 PRIMARY KEY (empresa_id, puesto_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS carga_validaciones (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 empleado_id INT NOT NULL,
 legajo VARCHAR(100) NOT NULL,
 empleado_nombre VARCHAR(255) NOT NULL,
 sucursal_empleado_id INT NOT NULL,
 sucursal_empleado_nombre VARCHAR(200) NOT NULL,
 puesto_nombre VARCHAR(255) NOT NULL,
 camion_id BIGINT UNSIGNED NOT NULL,
 camion_numero VARCHAR(40) NOT NULL,
 camion_patente VARCHAR(20) NOT NULL,
 sucursal_camion_id INT NOT NULL,
 sucursal_camion_nombre VARCHAR(200) NOT NULL,
 fecha DATE NOT NULL,
 registrado_at DATETIME(6) NOT NULL,
 tipo ENUM('inicial','recarga') NOT NULL,
 consolidado VARCHAR(64) NOT NULL,
 valida TINYINT NOT NULL,
 observaciones TEXT NOT NULL,
 en_horario TINYINT NOT NULL,
 horario_id BIGINT UNSIGNED NOT NULL,
 horario_nombre VARCHAR(100) NOT NULL,
 desde_minuto SMALLINT UNSIGNED NOT NULL,
 hasta_minuto SMALLINT UNSIGNED NOT NULL,
 origen ENUM('web','app') NOT NULL,
 envio_id VARCHAR(36) NOT NULL,
 envio_hash CHAR(64) NOT NULL,
 inicial_fecha DATE GENERATED ALWAYS AS (CASE WHEN tipo = 'inicial' THEN fecha ELSE NULL END) STORED,
 UNIQUE KEY uq_carga_inicial (camion_id, inicial_fecha),
 UNIQUE KEY uq_carga_consolidado (camion_id, fecha, consolidado),
 UNIQUE KEY uq_carga_envio (empresa_id, empleado_id, envio_id),
 KEY idx_carga_empresa_fecha (empresa_id, fecha, id),
 KEY idx_carga_empleado_fecha (empleado_id, fecha),
 KEY idx_carga_sucursal_fecha (sucursal_empleado_id, fecha),
 CONSTRAINT fk_carga_camion FOREIGN KEY (camion_id) REFERENCES carga_camiones(id),
 CONSTRAINT fk_carga_horario FOREIGN KEY (horario_id) REFERENCES carga_horarios(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS carga_fotos (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 validacion_id BIGINT UNSIGNED NOT NULL,
 contenido MEDIUMBLOB NOT NULL,
 sha256 CHAR(64) NOT NULL,
 CONSTRAINT fk_carga_foto FOREIGN KEY (validacion_id) REFERENCES carga_validaciones(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS carga_auditoria (
 id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 usuario_id INT NOT NULL,
 entidad VARCHAR(30) NOT NULL,
 registro_id BIGINT UNSIGNED NULL,
 detalle TEXT NOT NULL,
 creado_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO carga_horarios (empresa_id, nombre, tipo, desde_minuto, hasta_minuto, vigente_desde)
 SELECT e.id, 'Carga inicial', 'inicial', 0, 485, '1970-01-01' FROM empresas e
 WHERE NOT EXISTS (SELECT 1 FROM carga_horarios h WHERE h.empresa_id=e.id AND h.tipo='inicial' AND h.sucursal_id IS NULL);
INSERT INTO carga_horarios (empresa_id, nombre, tipo, desde_minuto, hasta_minuto, vigente_desde)
 SELECT e.id, 'Recarga', 'recarga', 660, 1440, '1970-01-01' FROM empresas e
 WHERE NOT EXISTS (SELECT 1 FROM carga_horarios h WHERE h.empresa_id=e.id AND h.tipo='recarga' AND h.sucursal_id IS NULL);
