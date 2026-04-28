-- Migracion: agrega condicion al objetivo sectorial de KPI
-- La condicion (gte/lte/eq) se define por objetivo, no se deriva del KPI.
-- Fecha: 2026-04-20

ALTER TABLE kpis_sector_objetivo
  ADD COLUMN condicion ENUM('gte', 'lte', 'eq') NOT NULL DEFAULT 'gte' AFTER objetivo_valor;
