CREATE TABLE IF NOT EXISTS sh_personas_externas (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 empresa_id INT NOT NULL,
 nombre VARCHAR(180) NOT NULL,
 empresa VARCHAR(180) NOT NULL DEFAULT '',
 activo TINYINT NOT NULL DEFAULT 1,
 creado_at DATETIME NOT NULL,
 INDEX ix_sh_externos_empresa (empresa_id,activo,nombre),
 FOREIGN KEY (empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sh_evento_externos (
 evento_id BIGINT NOT NULL,
 externo_id BIGINT NOT NULL,
 nombre VARCHAR(180) NOT NULL,
 empresa VARCHAR(180) NOT NULL DEFAULT '',
 PRIMARY KEY (evento_id,externo_id),
 FOREIGN KEY (evento_id) REFERENCES sh_eventos(id),
 FOREIGN KEY (externo_id) REFERENCES sh_personas_externas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
