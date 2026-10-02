"""No habilita personas automáticamente ni modifica movimientos históricos."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from extensions import get_db
from db import init_orm


def migrate():
    init_orm()
    db = get_db()
    c = db.cursor()
    try:
        for kind, column, flag in (
            ('empleados', 'empleado_id', 'habilitado'),
            ('puestos', 'puesto_id', 'bloqueado'),
        ):
            c.execute(f'''CREATE TABLE IF NOT EXISTS vacaciones_compensatorios_{kind} (
                {column} INT NOT NULL PRIMARY KEY,
                empresa_id INT NOT NULL,
                {flag} TINYINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY ({column}) REFERENCES {kind}(id),
                FOREIGN KEY (empresa_id) REFERENCES empresas(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        db.commit()
        print('[done] compensatorios_habilitacion')
    finally:
        c.close()
        db.close()


if __name__ == '__main__':
    migrate()
