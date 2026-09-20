"""Add correction metadata and the unified read-only reporting view."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from db import init_orm
from extensions import get_db

def migrate():
    init_orm();db=get_db();c=db.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='asistencia_marcas' AND COLUMN_NAME='corregida_manualmente'")
        if not c.fetchone()[0]:
            c.execute('ALTER TABLE asistencia_marcas ADD COLUMN corregida_manualmente TINYINT(1) NOT NULL DEFAULT 0')
        c.execute('''CREATE TABLE IF NOT EXISTS asistencia_correcciones (
            id BIGINT AUTO_INCREMENT PRIMARY KEY, asistencia_id INT NOT NULL,
            usuario_id INT NULL, accion VARCHAR(30) NOT NULL,
            antes LONGTEXT NULL, despues LONGTEXT NULL,
            creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ac_asistencia (asistencia_id,creado_en)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        c.execute((ROOT/'migrations/20260920_03_asistencia_reportes.sql').read_text(encoding='utf-8').strip().rstrip(';'))
        db.commit()
        print('Metadatos de correccion y vista de reportes disponibles. No se modificaron horarios historicos.')
    finally:
        c.close();db.close()

if __name__=='__main__': migrate()
