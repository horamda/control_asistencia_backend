-- Migracion: hace objetivo_valor nullable para soportar condicion 'between'
-- En between el objetivo se define por valor_min/valor_max, no por objetivo_valor.
-- Fecha: 2026-04-20

ALTER TABLE kpis_sector_objetivo
  MODIFY COLUMN objetivo_valor DECIMAL(14,4) NULL DEFAULT NULL;
