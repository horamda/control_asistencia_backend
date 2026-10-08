CREATE TABLE IF NOT EXISTS reintegro_categorias (
 id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, nombre VARCHAR(120) NOT NULL, activo TINYINT NOT NULL DEFAULT 1,
 UNIQUE KEY uq_reintegro_categoria(empresa_id,nombre), FOREIGN KEY(empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_solicitudes (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, empleado_id INT NOT NULL,
 sucursal_id INT NULL, jefe_id INT NULL, envio_id CHAR(36) NOT NULL, contenido_hash CHAR(64) NOT NULL,
 estado VARCHAR(20) NOT NULL, revision INT NOT NULL DEFAULT 1, moneda CHAR(3) NOT NULL DEFAULT 'ARS',
 total_solicitado DECIMAL(14,2) NOT NULL, total_aprobado DECIMAL(14,2) NOT NULL DEFAULT 0,
 observaciones TEXT NULL, motivo TEXT NULL, creado_at DATETIME NOT NULL, actualizado_at DATETIME NOT NULL,
 revisor_id INT NULL, revisado_at DATETIME NULL, pagado_por INT NULL, pagado_at DATETIME NULL,
 fecha_pago DATE NULL, referencia_pago VARCHAR(180) NULL,
 UNIQUE KEY uq_reintegro_envio(empresa_id,empleado_id,envio_id),
 KEY ix_reintegro_bandeja(empresa_id,estado,creado_at,id), KEY ix_reintegro_personal(empleado_id,creado_at,id),
 KEY ix_reintegro_empresa_fecha(empresa_id,creado_at,id),
 FOREIGN KEY(empresa_id) REFERENCES empresas(id), FOREIGN KEY(empleado_id) REFERENCES empleados(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_gastos (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, solicitud_id BIGINT NOT NULL, revision_carga INT NOT NULL,
 fecha DATE NOT NULL, concepto VARCHAR(500) NOT NULL, categoria_id INT NULL, categoria_nombre VARCHAR(120) NULL,
 importe DECIMAL(14,2) NOT NULL, decision VARCHAR(20) NOT NULL DEFAULT 'pendiente', motivo VARCHAR(1000) NULL,
 activo TINYINT NOT NULL DEFAULT 1, KEY ix_reintegro_gastos(solicitud_id,activo),
 FOREIGN KEY(solicitud_id) REFERENCES reintegro_solicitudes(id), FOREIGN KEY(categoria_id) REFERENCES reintegro_categorias(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_fotos (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, gasto_id BIGINT NOT NULL, contenido MEDIUMBLOB NOT NULL,
 sha256 CHAR(64) NOT NULL, FOREIGN KEY(gasto_id) REFERENCES reintegro_gastos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reintegro_auditoria (
 id BIGINT AUTO_INCREMENT PRIMARY KEY, solicitud_id BIGINT NULL, empresa_id INT NOT NULL,
 usuario_id INT NULL, empleado_id INT NULL, accion VARCHAR(40) NOT NULL, datos JSON NOT NULL, creado_at DATETIME NOT NULL,
 KEY ix_reintegro_auditoria(solicitud_id,id), FOREIGN KEY(solicitud_id) REFERENCES reintegro_solicitudes(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
