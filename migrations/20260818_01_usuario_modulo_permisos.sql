-- Migracion: permisos granulares por modulo para usuarios del panel web.
-- Mantiene usuarios.rol como compatibilidad y perfil base.

CREATE TABLE IF NOT EXISTS usuario_modulo_permisos (
  id              INT NOT NULL AUTO_INCREMENT,
  usuario_id      INT NOT NULL,
  modulo          VARCHAR(80) NOT NULL,
  puede_ver       TINYINT(1) NOT NULL DEFAULT 0,
  puede_crear     TINYINT(1) NOT NULL DEFAULT 0,
  puede_editar    TINYINT(1) NOT NULL DEFAULT 0,
  puede_eliminar  TINYINT(1) NOT NULL DEFAULT 0,
  puede_aprobar   TINYINT(1) NOT NULL DEFAULT 0,
  puede_exportar  TINYINT(1) NOT NULL DEFAULT 0,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_usuario_modulo_permiso (usuario_id, modulo),
  KEY idx_usuario_modulo_permiso_modulo (modulo),
  CONSTRAINT fk_usuario_modulo_permisos_usuario
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
