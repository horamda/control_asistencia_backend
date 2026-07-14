-- Permite solicitar unidades sueltas adicionales a los bultos completos.
ALTER TABLE pedidos_mercaderia_items
  ADD COLUMN IF NOT EXISTS cantidad_unidades INT UNSIGNED NOT NULL DEFAULT 0
  AFTER cantidad_bultos;
