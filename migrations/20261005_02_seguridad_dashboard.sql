CREATE TABLE IF NOT EXISTS sh_dashboard_config (
 empresa_id INT NOT NULL PRIMARY KEY,
 inicio DATE NOT NULL,
 FOREIGN KEY (empresa_id) REFERENCES empresas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
