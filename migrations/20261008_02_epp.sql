CREATE TABLE IF NOT EXISTS epp_articulos (
 id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, nombre VARCHAR(120) NOT NULL,
 categoria VARCHAR(80) NOT NULL, descripcion VARCHAR(1000) NOT NULL, activo TINYINT NOT NULL DEFAULT 1,
 talles JSON NOT NULL, sectores JSON NOT NULL, puestos JSON NOT NULL, aviso_anual INT NOT NULL DEFAULT 0,
 imagen MEDIUMBLOB NULL, actualizado_at DATETIME NOT NULL,
 UNIQUE KEY uq_epp_nombre(empresa_id,nombre)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_talles (
 empresa_id INT NOT NULL, empleado_id INT NOT NULL, articulo_id INT NOT NULL,
 talle VARCHAR(80) NOT NULL, medidas VARCHAR(300) NOT NULL, actualizado_at DATETIME NOT NULL,
 PRIMARY KEY(empresa_id,empleado_id,articulo_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_pedidos (
 id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, empleado_id INT NOT NULL,
 sucursal_id INT NOT NULL, empleado_nombre VARCHAR(240) NOT NULL, legajo VARCHAR(80) NOT NULL,
 estado VARCHAR(30) NOT NULL, revision INT NOT NULL DEFAULT 1, motivo VARCHAR(1000) NOT NULL,
 envio_id VARCHAR(36) NOT NULL, envio_hash CHAR(64) NOT NULL, creado_at DATETIME NOT NULL,
 UNIQUE KEY uq_epp_envio(empresa_id,empleado_id,envio_id),
 KEY ix_epp_historial(empresa_id,empleado_id,creado_at), KEY ix_epp_sucursal(empresa_id,sucursal_id,estado)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_lineas (
 id INT AUTO_INCREMENT PRIMARY KEY, pedido_id INT NOT NULL, articulo_id INT NOT NULL,
 nombre VARCHAR(120) NOT NULL, categoria VARCHAR(80) NOT NULL, talle VARCHAR(80) NOT NULL,
 medidas VARCHAR(300) NOT NULL, cantidad INT NOT NULL, aprobada INT NULL,
 motivo VARCHAR(1000) NOT NULL DEFAULT '', KEY ix_epp_lineas(pedido_id),
 FOREIGN KEY(pedido_id) REFERENCES epp_pedidos(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_entregas (
 id INT AUTO_INCREMENT PRIMARY KEY, pedido_id INT NOT NULL, fecha DATE NOT NULL,
 responsable_id INT NOT NULL, observaciones VARCHAR(1000) NOT NULL,
 clave VARCHAR(36) NOT NULL, envio_hash CHAR(64) NOT NULL, anulada TINYINT NOT NULL DEFAULT 0,
 firma MEDIUMBLOB NULL, creado_at DATETIME NOT NULL,
 UNIQUE KEY uq_epp_entrega(pedido_id,clave), KEY ix_epp_fecha(fecha),
 FOREIGN KEY(pedido_id) REFERENCES epp_pedidos(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_entrega_lineas (
 entrega_id INT NOT NULL, linea_id INT NOT NULL, cantidad INT NOT NULL,
 PRIMARY KEY(entrega_id,linea_id), FOREIGN KEY(entrega_id) REFERENCES epp_entregas(id),
 FOREIGN KEY(linea_id) REFERENCES epp_lineas(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_auditoria (
 id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, pedido_id INT NULL,
 empleado_id INT NULL, usuario_id INT NULL, accion VARCHAR(50) NOT NULL,
 datos JSON NOT NULL, creado_at DATETIME NOT NULL, KEY ix_epp_audit(empresa_id,pedido_id,id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS epp_categorias (
 id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL, nombre VARCHAR(80) NOT NULL,
 activo TINYINT NOT NULL DEFAULT 1, UNIQUE KEY uq_epp_categoria(empresa_id,nombre)
) ENGINE=InnoDB;
INSERT IGNORE INTO epp_categorias(empresa_id,nombre) SELECT id,'EPP' FROM empresas;
INSERT IGNORE INTO epp_categorias(empresa_id,nombre) SELECT id,'Ropa' FROM empresas;
INSERT IGNORE INTO epp_categorias(empresa_id,nombre) SELECT id,'Calzado' FROM empresas;
