CREATE TABLE IF NOT EXISTS sh_catalogos (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL,
 clase VARCHAR(30) NOT NULL, tipo VARCHAR(20) NOT NULL DEFAULT '', nombre VARCHAR(180) NOT NULL,
 activo TINYINT NOT NULL DEFAULT 1,
 UNIQUE KEY uq_sh_catalogo (empresa_id,clase,tipo,nombre),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_eventos (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL,
 reportante_id INT NULL, usuario_id INT NULL, tipo VARCHAR(20) NOT NULL,
 fecha_evento DATE NOT NULL, hora_evento VARCHAR(5) NULL,
 descripcion TEXT NOT NULL, categoria_id BIGINT NULL, categoria_nombre VARCHAR(180) NOT NULL DEFAULT '',
 detalles LONGTEXT NOT NULL, estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
 motivo TEXT NULL, revision INT NOT NULL DEFAULT 1,
 envio_id VARCHAR(80) NOT NULL, contenido_hash CHAR(64) NOT NULL,
 origen VARCHAR(20) NOT NULL, creado_at DATETIME NOT NULL,
 revisado_at DATETIME NULL, revisor_id INT NULL,
 UNIQUE KEY uq_sh_envio (empresa_id,envio_id), KEY ix_sh_historial (empresa_id,fecha_evento,estado,tipo),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id), FOREIGN KEY (reportante_id) REFERENCES empleados(id),
 FOREIGN KEY (categoria_id) REFERENCES sh_catalogos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_involucrados (
 evento_id BIGINT NOT NULL, empleado_id INT NOT NULL,
 nombre VARCHAR(240) NOT NULL, legajo VARCHAR(80) NOT NULL,
 sucursal_id INT NULL, sucursal_nombre VARCHAR(180) NULL,
 sector_id INT NULL, sector_nombre VARCHAR(180) NULL,
 puesto_id INT NULL, puesto_nombre VARCHAR(180) NULL,
 PRIMARY KEY (evento_id,empleado_id), KEY ix_sh_persona (empleado_id,evento_id),
 FOREIGN KEY (evento_id) REFERENCES sh_eventos(id), FOREIGN KEY (empleado_id) REFERENCES empleados(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_fotos (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, evento_id BIGINT NOT NULL,
 contenido MEDIUMBLOB NOT NULL, activo TINYINT NOT NULL DEFAULT 1, FOREIGN KEY (evento_id) REFERENCES sh_eventos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_auditoria (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, evento_id BIGINT NULL,
 usuario_id INT NULL, accion VARCHAR(50) NOT NULL, datos LONGTEXT NOT NULL, creado_at DATETIME NOT NULL,
 KEY ix_sh_audit (empresa_id,evento_id), FOREIGN KEY (evento_id) REFERENCES sh_eventos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_acciones (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, evento_id BIGINT NOT NULL,
 descripcion TEXT NOT NULL, responsable_id INT NOT NULL, vencimiento DATE NOT NULL,
 estado VARCHAR(20) NOT NULL DEFAULT 'pendiente', evidencia TEXT NULL,
 FOREIGN KEY (evento_id) REFERENCES sh_eventos(id), FOREIGN KEY (responsable_id) REFERENCES empleados(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_importaciones (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, usuario_id INT NOT NULL,
 nombre VARCHAR(255) NOT NULL, archivo LONGBLOB NOT NULL, sha256 CHAR(64) NOT NULL,
 creado_at DATETIME NOT NULL, UNIQUE KEY uq_sh_archivo (empresa_id,sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_import_filas (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, importacion_id BIGINT NOT NULL,
 hoja VARCHAR(180) NOT NULL, fila INT NOT NULL, original LONGTEXT NOT NULL,
 propuesta LONGTEXT NOT NULL, errores TEXT NOT NULL, evento_id BIGINT NULL,
 UNIQUE KEY uq_sh_fila (importacion_id,hoja,fila),
 FOREIGN KEY (importacion_id) REFERENCES sh_importaciones(id), FOREIGN KEY (evento_id) REFERENCES sh_eventos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
