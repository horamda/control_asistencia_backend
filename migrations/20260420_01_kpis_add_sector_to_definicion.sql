-- Migracion: agrega sector_id a kpis_definicion
-- Los KPIs pasan a pertenecer a un sector especifico en lugar de a la empresa entera.
-- Fecha: 2026-04-20

ALTER TABLE kpis_definicion
  ADD COLUMN sector_id INT NOT NULL AFTER empresa_id,
  DROP INDEX uk_kpis_definicion_empresa_codigo,
  ADD UNIQUE KEY uk_kpis_definicion_sector_codigo (sector_id, codigo),
  ADD KEY idx_kpis_definicion_sector (sector_id),
  ADD CONSTRAINT fk_kpis_definicion_sector FOREIGN KEY (sector_id) REFERENCES sectores (id);
