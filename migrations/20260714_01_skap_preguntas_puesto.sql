-- SKAP: preguntas especificas por puesto (ademas de por sector)
-- Fecha: 2026-07-14
-- puesto_id NULL = pregunta general del sector (aplica a todos los puestos del sector)
-- puesto_id fijado = pregunta especifica de ese puesto dentro del sector

ALTER TABLE skap_preguntas
    ADD COLUMN puesto_id INT NULL AFTER sector_id,
    ADD INDEX idx_skap_preguntas_puesto (puesto_id),
    ADD INDEX idx_skap_preguntas_sector_puesto_activo (sector_id, puesto_id, activo),
    ADD CONSTRAINT fk_skap_preguntas_puesto
        FOREIGN KEY (puesto_id) REFERENCES puestos(id) ON DELETE CASCADE;

ALTER TABLE skap_preguntas
    DROP INDEX uq_skap_preguntas_sector_categoria_desc,
    ADD UNIQUE KEY uq_skap_preguntas_sector_puesto_categoria_desc (sector_id, puesto_id, categoria, descripcion);
