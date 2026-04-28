-- Migracion: agrega condicion 'between' y columnas de rango a kpis_sector_objetivo
-- Fecha: 2026-04-20

ALTER TABLE kpis_sector_objetivo
  MODIFY COLUMN condicion ENUM('gte', 'lte', 'eq', 'between') NOT NULL DEFAULT 'gte' AFTER objetivo_valor,
  ADD COLUMN valor_min DECIMAL(14,4) NULL AFTER condicion,
  ADD COLUMN valor_max DECIMAL(14,4) NULL AFTER valor_min;
