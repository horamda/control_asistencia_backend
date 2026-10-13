"""Aggregate follow-up checks; no changes to remote data or schema."""
import datetime as dt
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import _load_db_settings
import mysql.connector


def main():
    s = _load_db_settings()
    conn = mysql.connector.connect(host=s['host'], port=int(s['port']), user=s['user'], password=s['password'], database=s['db'], connection_timeout=15, read_timeout=20, collation='utf8mb4_general_ci')
    cur = conn.cursor(dictionary=True)
    cur.execute('SET SESSION MAX_EXECUTION_TIME=5000')
    result = {'started_utc': str(dt.datetime.now(dt.timezone.utc)), 'queries': {}}
    checks = {
        'nonworking_scope': "SELECT COUNT(*) total,SUM(empresa_id=0 AND sucursal_id=0 AND sector_id=0) global_scope,SUM(d.empresa_id<>0 AND NOT EXISTS(SELECT 1 FROM empresas e WHERE e.id=d.empresa_id)) invalid_company,SUM(d.sucursal_id<>0 AND NOT EXISTS(SELECT 1 FROM sucursales s WHERE s.id=d.sucursal_id)) invalid_branch,SUM(d.sector_id<>0 AND NOT EXISTS(SELECT 1 FROM sectores s WHERE s.id=d.sector_id)) invalid_sector FROM asistencia_dias_no_laborables d",
        'incomplete_by_month': "SELECT DATE_FORMAT(fecha,'%Y-%m') month,COUNT(*) total,SUM(hora_entrada IS NOT NULL AND hora_salida IS NULL) missing_exit,SUM(hora_entrada IS NULL AND hora_salida IS NOT NULL) missing_entry FROM asistencias WHERE fecha<DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR) GROUP BY month ORDER BY month",
        'incomplete_with_marks': "SELECT COUNT(*) missing_exit,SUM(EXISTS(SELECT 1 FROM asistencia_marcas m WHERE m.empleado_id=a.empleado_id AND m.fecha=a.fecha AND m.accion='egreso')) days_with_exit_mark FROM asistencias a WHERE a.fecha<DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR) AND a.hora_entrada IS NOT NULL AND a.hora_salida IS NULL",
        'safety_future': "SELECT COUNT(*) future_rows FROM sh_eventos WHERE fecha_evento>DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR)",
    }
    try:
        for name, sql in checks.items():
            conn.start_transaction(readonly=True)
            cur.execute(sql)
            result['queries'][name] = {'sql': sql, 'rows': cur.fetchall()}
            conn.rollback()
        conn.start_transaction(readonly=True)
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            cur.execute('SELECT 1 AS ok')
            assert cur.fetchall() == [{'ok': 1}]
            samples.append(round((time.perf_counter() - start) * 1000, 2))
        conn.rollback()
        result['select1_client_ms'] = {'samples': samples, 'median': statistics.median(samples), 'scope': 'execute + fetch only, local PC to configured Railway proxy; not application-server latency'}
        result['finished_utc'] = str(dt.datetime.now(dt.timezone.utc))
        (ROOT / 'output/db_audit_followup_20261013.json').write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
        print(json.dumps(result, default=str))
    finally:
        conn.rollback()
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
