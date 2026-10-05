"""Migración aditiva y repetible; no aprueba registros ni asigna permisos."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import init_orm
from extensions import get_db

DEFAULTS = {
    ('categoria','seguro'): ['Utilización de epp correctamente','Utiliza los 3 puntos de contacto',
        'Estaciona autolevador en zona indicada','Utiliza casco y cinturon de seguridad','Camina sobre senda peatonal','Otro'],
    ('categoria','inseguro'): ['Falta de epp','Fumar en lugares no permitidos','Exceso de velocidad',
        'Aceleracion brusca','Circulación peatonal Inapropiada','Manejo Inseguro de Autoelevador',
        'No uso de casco en moto','No cierra lonas','Uso del celular en lugares no permitidos',
        'Interaccion hombre maquina en zona no permitidas','Frenada brusca','No utiliza el cinturón de Seguridad','Otros'],
    ('lugar',''): ['En ruta de reparto','Dentro del distri','Camino al trabajo','Otro'],
    ('clasificacion',''): ['SIF','FAI','MTI','MDI','LTI'],
    ('atencion',''): ['Atención médica','No requirió atención'],
    ('lesion',''): ['Esguince','Otro'],
    ('parte_cuerpo',''): ['Rodilla','Tobillo','Cabeza','Otro'],
}


def migrate():
    init_orm()
    db = get_db()
    c = db.cursor()
    try:
        for sql in (ROOT / 'migrations/20261002_01_seguridad_higiene.sql').read_text(encoding='utf-8').split(';'):
            if sql.strip():
                c.execute(sql)
        c.execute("SHOW COLUMNS FROM sh_fotos LIKE 'activo'")
        if c.fetchone() is None:
            c.execute('ALTER TABLE sh_fotos ADD COLUMN activo TINYINT NOT NULL DEFAULT 1')
        c.execute('SELECT id FROM empresas')
        empresas=[r[0] for r in c.fetchall()]
        for empresa in empresas:
            for (clase,tipo),names in DEFAULTS.items():
                for nombre in names:
                    c.execute('''INSERT INTO sh_catalogos(empresa_id,clase,tipo,nombre)
                        SELECT %s,%s,%s,%s WHERE NOT EXISTS(
                            SELECT 1 FROM sh_catalogos WHERE empresa_id=%s AND clase=%s AND tipo=%s AND nombre=%s)''',
                        (empresa,clase,tipo,nombre,empresa,clase,tipo,nombre))
        db.commit()
    finally:
        c.close()
        db.close()
    print('Seguridad e Higiene: tablas creadas. Configure catálogos y permisos en el panel.')


if __name__ == '__main__':
    migrate()
