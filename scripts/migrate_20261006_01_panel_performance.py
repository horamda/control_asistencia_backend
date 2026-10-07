"""Audit and benchmark by default; --apply creates missing indexes online only."""
import argparse
import json
import statistics
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mysql.connector
from db import _load_db_settings

INDEXES = (
    ('sh_eventos', 'ix_sh_estado_fecha', ('empresa_id', 'estado', 'fecha_evento', 'id', 'tipo')),
    ('sh_fotos', 'ix_sh_fotos_activas', ('evento_id', 'activo')),
    ('sh_import_filas', 'ix_sh_import_pendientes', ('importacion_id', 'evento_id')),
)
QUERIES = {
    'roundtrip': ('SELECT 1', ()),
    'asistencias_mes': ("SELECT COUNT(*),COUNT(CASE WHEN estado='tarde' THEN 1 END) FROM asistencias WHERE fecha>=%s AND fecha<%s", ('2026-09-01','2026-10-01')),
    'justificaciones_mes': ('SELECT COUNT(*),estado FROM justificaciones WHERE created_at>=%s AND created_at<%s GROUP BY estado', ('2026-09-01','2026-10-01')),
    'seguridad_historial': ("SELECT id,tipo,fecha_evento FROM sh_eventos WHERE empresa_id=%s AND estado='aprobado' ORDER BY fecha_evento DESC,id DESC LIMIT 30", (1,)),
    'seguridad_anual': ("SELECT tipo,YEAR(fecha_evento),MONTH(fecha_evento),COUNT(*) FROM sh_eventos WHERE empresa_id=%s AND estado='aprobado' AND fecha_evento<=%s GROUP BY tipo,YEAR(fecha_evento),MONTH(fecha_evento)", (1,'2026-10-06')),
    'importacion_pendientes': ('SELECT COUNT(*) FROM sh_import_filas f JOIN sh_importaciones i ON i.id=f.importacion_id WHERE i.empresa_id=%s AND f.evento_id IS NULL', (1,)),
}

def covering_index(rows, columns):
    indexes = {}
    for row in sorted(rows, key=lambda r:(r['Key_name'],r['Seq_in_index'])):
        if row.get('Visible','YES') == 'NO' or row.get('Ignored','NO') == 'YES':
            continue
        indexes.setdefault(row['Key_name'],[]).append(row['Column_name'] if row.get('Sub_part') is None else None)
    return next((name for name,parts in indexes.items() if tuple(parts[:len(columns)])==columns),None)

def measure(cursor):
    report = {}
    for label,(sql,args) in QUERIES.items():
        cursor.execute('EXPLAIN FORMAT=TRADITIONAL '+sql,args)
        plans=[{k:r.get(k) for k in ('table','type','key','rows','Extra')} for r in cursor.fetchall()]
        samples=[]
        for _ in range(5):
            start=perf_counter();cursor.execute(sql,args);cursor.fetchall()
            samples.append(round((perf_counter()-start)*1000,2))
        report[label]=dict(median_ms=statistics.median(samples),samples_ms=samples,explain=plans)
    return report

def run(apply, output):
    output=Path(output)
    # Exclusive report directory: never overwrite evidence of an earlier DDL run.
    output.mkdir(parents=True,exist_ok=False)
    settings=_load_db_settings()
    start=perf_counter()
    conn=mysql.connector.connect(host=settings['host'],port=int(settings['port']),user=settings['user'],
        password=settings['password'],database=settings['db'],connection_timeout=10)
    report=dict(connection_ms=round((perf_counter()-start)*1000,2),operations=[])
    cursor=conn.cursor(dictionary=True)
    try:
        cursor.execute('SET SESSION lock_wait_timeout=5')
        report['before']=measure(cursor)
        # End read transaction before online DDL. No business writes are made.
        conn.rollback()
        definitions=[]
        for table,name,columns in INDEXES:
            cursor.execute(f'SHOW CREATE TABLE `{table}`')
            definitions.append(cursor.fetchone()['Create Table']+';')
        (output/'schema_before.sql').write_text('\n\n'.join(definitions),encoding='utf-8')
        for table,name,columns in INDEXES:
            cursor.execute(f'SHOW INDEX FROM `{table}`');rows=cursor.fetchall()
            existing=covering_index(rows,columns)
            operation=dict(table=table,index=name,covering=existing,status='covered' if existing else 'proposed')
            report['operations'].append(operation)
            if existing: continue
            if any(r['Key_name']==name for r in rows): raise RuntimeError('Index name collision')
            ddl=f"ALTER TABLE `{table}` ADD INDEX `{name}` ({','.join('`'+c+'`' for c in columns)}), ALGORITHM=INPLACE, LOCK=NONE"
            operation['ddl']=ddl
            if apply:
                cursor.execute(ddl)
                operation['status']='created'
                with (output/'rollback.sql').open('a',encoding='utf-8') as rollback:
                    rollback.write(f'ALTER TABLE `{table}` DROP INDEX `{name}`, ALGORITHM=INPLACE, LOCK=NONE;\n')
        report['after']=measure(cursor)
    finally:
        (output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        cursor.close();conn.close()
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try: run(args.apply,args.output)
    except Exception as exc:
        print(f'FAILED: {type(exc).__name__}, errno={getattr(exc,"errno",None)}',file=sys.stderr)
        sys.exit(1)
