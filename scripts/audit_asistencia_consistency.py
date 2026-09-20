"""Read-only consistency audit; outputs counts without employee identifiers."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from db import init_orm
from extensions import get_db


def audit():
    init_orm();db=get_db();c=db.cursor(dictionary=True)
    try:
        c.execute('''SELECT COUNT(*) AS resumenes,
          COALESCE(SUM((a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL) AND NOT EXISTS
            (SELECT 1 FROM asistencia_marcas m WHERE m.empleado_id=a.empleado_id AND m.fecha=a.fecha)),0) AS resumenes_historicos_sin_marcas,
          COALESCE(SUM(a.estado='ausente' AND (a.hora_entrada IS NOT NULL OR a.hora_salida IS NOT NULL)),0) AS ausentes_con_horario
          FROM asistencias a''')
        result=c.fetchone()
        c.execute('''SELECT COUNT(*) AS resumenes_con_marcas_discrepantes FROM asistencias a
          JOIN (SELECT asistencia_id, MIN(CASE WHEN accion='ingreso' THEN hora END) AS entrada,
            MAX(CASE WHEN accion='egreso' THEN hora END) AS salida FROM asistencia_marcas
            WHERE asistencia_id IS NOT NULL GROUP BY asistencia_id) m ON m.asistencia_id=a.id
          WHERE NOT (a.hora_entrada <=> m.entrada) OR NOT (a.hora_salida <=> m.salida)''')
        result.update(c.fetchone())
        c.execute('''SELECT COUNT(*) AS marcas_sin_resumen FROM asistencia_marcas m LEFT JOIN asistencias a ON a.id=m.asistencia_id
          WHERE a.id IS NULL''');result.update(c.fetchone())
        c.execute('''SELECT COUNT(*) AS marcas_con_identidad_o_fecha_distinta FROM asistencia_marcas m JOIN asistencias a ON a.id=m.asistencia_id
          WHERE m.empleado_id<>a.empleado_id OR m.empresa_id<>a.empresa_id OR m.fecha<>a.fecha''');result.update(c.fetchone())
        return {k:int(v or 0) for k,v in result.items()}
    finally:
        c.close();db.close()

if __name__=='__main__':
    print(json.dumps(audit(),ensure_ascii=False,indent=2))
