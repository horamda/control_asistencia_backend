-- Migration: GPS fields for attendance scan validation
-- Date: 2026-02-16
-- Target: table asistencias

ALTER TABLE asistencias
  ADD COLUMN IF NOT EXISTS gps_ok_entrada TINYINT(1) NULL AFTER lon_entrada,
  ADD COLUMN IF NOT EXISTS gps_distancia_entrada_m DECIMAL(10,2) NULL AFTER gps_ok_entrada,
  ADD COLUMN IF NOT EXISTS gps_tolerancia_entrada_m DECIMAL(10,2) NULL AFTER gps_distancia_entrada_m,
  ADD COLUMN IF NOT EXISTS gps_ref_lat_entrada DECIMAL(10,7) NULL AFTER gps_tolerancia_entrada_m,
  ADD COLUMN IF NOT EXISTS gps_ref_lon_entrada DECIMAL(10,7) NULL AFTER gps_ref_lat_entrada,
  ADD COLUMN IF NOT EXISTS gps_ok_salida TINYINT(1) NULL AFTER lon_salida,
  ADD COLUMN IF NOT EXISTS gps_distancia_salida_m DECIMAL(10,2) NULL AFTER gps_ok_salida,
  ADD COLUMN IF NOT EXISTS gps_tolerancia_salida_m DECIMAL(10,2) NULL AFTER gps_distancia_salida_m,
  ADD COLUMN IF NOT EXISTS gps_ref_lat_salida DECIMAL(10,7) NULL AFTER gps_tolerancia_salida_m,
  ADD COLUMN IF NOT EXISTS gps_ref_lon_salida DECIMAL(10,7) NULL AFTER gps_ref_lat_salida;
