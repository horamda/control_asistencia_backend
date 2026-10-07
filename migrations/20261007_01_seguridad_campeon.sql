CREATE TABLE IF NOT EXISTS sh_campeon_reglas (
 empresa_id INT NOT NULL PRIMARY KEY,
 reglas JSON NOT NULL,
 revision INT NOT NULL DEFAULT 1,
 actualizado_at DATETIME NOT NULL,
 FOREIGN KEY (empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_campeon_premios (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 anio INT NOT NULL,
 mes INT NOT NULL DEFAULT 0,
 agrupacion VARCHAR(20) NOT NULL,
 grupo VARCHAR(80) NOT NULL,
 resultado JSON NOT NULL,
 usuario_id INT NOT NULL,
 confirmado_at DATETIME NOT NULL,
 UNIQUE KEY uq_sh_campeon_periodo (empresa_id,anio,mes,agrupacion,grupo),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
