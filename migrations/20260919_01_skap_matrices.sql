-- Modelo operativo 0-4 independiente del histórico SKAP 1-5.
CREATE TABLE IF NOT EXISTS skap_matriz_aliases (
 empresa_id INT NOT NULL,
 nombre_clave VARCHAR(255) NOT NULL,
 empleado_id INT NOT NULL,
 PRIMARY KEY (empresa_id,nombre_clave),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id),
 FOREIGN KEY (empleado_id) REFERENCES empleados(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS skap_matriz_importaciones (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 usuario_id INT NULL,
 archivo VARCHAR(255) NOT NULL,
 sha256 CHAR(64) NOT NULL,
 contenido LONGTEXT NOT NULL,
 estado VARCHAR(20) NOT NULL DEFAULT 'vista_previa',
 resultado LONGTEXT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 aplicado_at DATETIME NULL,
 revertido_at DATETIME NULL,
 INDEX idx_skap_import_empresa (empresa_id, estado),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id),
 FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS skap_matriz_evaluaciones (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 importacion_id BIGINT NOT NULL,
 empresa_id INT NOT NULL,
 empleado_id INT NOT NULL,
 sucursal_id INT NOT NULL,
 sector_id INT NULL,
 rol VARCHAR(120) NOT NULL,
 rol_clave VARCHAR(120) NOT NULL,
 anio INT NOT NULL,
 escala VARCHAR(30) NOT NULL DEFAULT 'operativa_0_4',
 fecha_evaluacion DATE NULL,
 evaluador_empleado_id INT NULL,
 nombre_original VARCHAR(255) NOT NULL,
 hoja VARCHAR(255) NOT NULL,
 contenido LONGTEXT NOT NULL,
 contenido_sha256 CHAR(64) NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_skap_matriz_ciclo (empresa_id, empleado_id, sucursal_id, rol_clave, anio),
 INDEX idx_skap_matriz_empleado (empleado_id, anio),
 FOREIGN KEY (importacion_id) REFERENCES skap_matriz_importaciones(id),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id),
 FOREIGN KEY (empleado_id) REFERENCES empleados(id),
 FOREIGN KEY (sucursal_id) REFERENCES sucursales(id),
 FOREIGN KEY (sector_id) REFERENCES sectores(id) ON DELETE SET NULL,
 FOREIGN KEY (evaluador_empleado_id) REFERENCES empleados(id) ON DELETE SET NULL,
 CHECK (anio BETWEEN 1900 AND 2100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS skap_matriz_acciones (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 evaluacion_id BIGINT NOT NULL,
 competencia TEXT NOT NULL,
 criticidad CHAR(1) NULL,
 accion TEXT NOT NULL,
 responsable_empleado_id INT NULL,
 fecha_inicio DATE NULL,
 fecha_fin DATE NULL,
 estado VARCHAR(20) NOT NULL DEFAULT 'propuesta',
 progreso INT NOT NULL DEFAULT 0,
 comentarios TEXT NULL,
 updated_at DATETIME NULL,
 FOREIGN KEY (evaluacion_id) REFERENCES skap_matriz_evaluaciones(id) ON DELETE CASCADE,
 FOREIGN KEY (responsable_empleado_id) REFERENCES empleados(id) ON DELETE SET NULL,
 CHECK (progreso BETWEEN 0 AND 100),
 CHECK (estado IN ('propuesta','pendiente','en_proceso','completado','cancelado')),
 CHECK (fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS skap_matriz_auditoria (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 usuario_id INT NULL,
 importacion_id BIGINT NOT NULL,
 evento VARCHAR(40) NOT NULL,
 detalle LONGTEXT NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (importacion_id) REFERENCES skap_matriz_importaciones(id),
 FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
