CREATE TABLE IF NOT EXISTS epp_conceptos_reposicion (
 id INT AUTO_INCREMENT PRIMARY KEY, empresa_id INT NOT NULL,
 nombre VARCHAR(120) NOT NULL, activo TINYINT NOT NULL DEFAULT 1,
 UNIQUE KEY uq_epp_concepto(empresa_id,nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
