-- Migración: nuevos campos en tabla empleados
-- Fecha: 2026-04-15

ALTER TABLE empleados
    ADD COLUMN cuil             VARCHAR(15)                                        NULL AFTER dni,
    ADD COLUMN tipo_contrato    ENUM('efectivo','temporal','pasantia','otro')       NULL AFTER fecha_ingreso,
    ADD COLUMN modalidad        ENUM('presencial','remoto','hibrido')               NULL DEFAULT 'presencial' AFTER tipo_contrato,
    ADD COLUMN fecha_baja       DATE                                                NULL AFTER modalidad,
    ADD COLUMN categoria        VARCHAR(100)                                        NULL AFTER fecha_baja,
    ADD COLUMN obra_social      VARCHAR(100)                                        NULL AFTER categoria,
    ADD COLUMN cod_chess_erp    INT                                                 NULL AFTER obra_social,
    ADD COLUMN banco            VARCHAR(100)                                        NULL AFTER cod_chess_erp,
    ADD COLUMN cbu              VARCHAR(22)                                         NULL AFTER banco,
    ADD COLUMN numero_emergencia VARCHAR(50)                                        NULL AFTER cbu;
