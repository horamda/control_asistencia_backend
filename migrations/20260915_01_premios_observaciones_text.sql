-- Aplicar antes de desplegar el formulario que admite 5000 caracteres.
-- TEXT conserva las observaciones existentes y admite caracteres utf8mb4.
ALTER TABLE premios_resultados MODIFY COLUMN observaciones TEXT NULL;
