"""Read-only live audit. Aggregate evidence only; no application initialization."""
import datetime as dt
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import _load_db_settings
import mysql.connector

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/db_audit_20261013.json'


def main():
    settings = _load_db_settings()
    conn = mysql.connector.connect(host=settings['host'], port=int(settings['port']), user=settings['user'], password=settings['password'], database=settings['db'], connection_timeout=15, read_timeout=20, collation='utf8mb4_general_ci')
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SET SESSION MAX_EXECUTION_TIME=5000')
    result = {'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'database': settings['db'], 'mode': 'READ ONLY; SELECT timeout 5 seconds', 'queries': {}}
    def query(name, sql, args=()):
        began = time.perf_counter()
        try:
            conn.start_transaction(readonly=True)
            cursor.execute(sql, args)
            rows = cursor.fetchall()
            result['queries'][name] = {'sql': sql, 'params': args, 'rows': rows, 'elapsed_ms': round((time.perf_counter()-began)*1000, 2)}
            return rows
        except mysql.connector.Error as exc:
            result['queries'][name] = {'sql': sql, 'error_code': exc.errno, 'error': str(exc), 'elapsed_ms': round((time.perf_counter()-began)*1000, 2)}
            return []
        finally:
            conn.rollback()
            OUTPUT.parent.mkdir(exist_ok=True)
            OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    try:
        query('server', 'SELECT VERSION() version, DATABASE() db, UTC_TIMESTAMP() utc_now, @@session.time_zone session_timezone, @@global.time_zone global_timezone, @@read_only server_readonly')
        tables = query('tables', 'SELECT TABLE_NAME,ENGINE,TABLE_ROWS,DATA_LENGTH,INDEX_LENGTH,DATA_FREE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE=\'BASE TABLE\' ORDER BY DATA_LENGTH DESC')
        columns = query('columns', 'SELECT TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,ORDINAL_POSITION')
        indexes = query('indexes', 'SELECT TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART,INDEX_TYPE,IS_VISIBLE FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME,INDEX_NAME,SEQ_IN_INDEX')
        fks = query('foreign_keys', 'SELECT TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME,ORDINAL_POSITION FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION')
        query('variables', "SHOW GLOBAL VARIABLES WHERE Variable_name IN ('max_connections','innodb_buffer_pool_size','slow_query_log','long_query_time','performance_schema','log_bin','binlog_expire_logs_seconds','innodb_flush_log_at_trx_commit','sync_binlog','require_secure_transport','wait_timeout')")
        query('status', "SHOW GLOBAL STATUS WHERE Variable_name IN ('Uptime','Threads_connected','Threads_running','Max_used_connections','Slow_queries','Connections','Aborted_connects','Innodb_buffer_pool_reads','Innodb_buffer_pool_read_requests','Created_tmp_disk_tables','Created_tmp_tables','Innodb_row_lock_waits','Innodb_row_lock_time','Questions')")
        query('connections', "SELECT COMMAND,STATE,COUNT(*) connections,MAX(TIME) max_seconds FROM information_schema.PROCESSLIST WHERE DB=DATABASE() GROUP BY COMMAND,STATE")
        query('lock_waits', 'SELECT COUNT(*) waiting_locks FROM performance_schema.data_lock_waits')
        query('transactions', 'SELECT COUNT(*) active_transactions,MAX(TIMESTAMPDIFF(SECOND,trx_started,NOW())) oldest_seconds,SUM(trx_rows_locked) rows_locked FROM information_schema.INNODB_TRX')
        query('statement_digest', "SELECT DIGEST_TEXT,COUNT_STAR,ROUND(SUM_TIMER_WAIT/1000000000000,3) total_seconds,ROUND(AVG_TIMER_WAIT/1000000000,3) avg_ms,MAX_TIMER_WAIT/1000000000 max_ms,SUM_ROWS_EXAMINED,SUM_ROWS_SENT,SUM_NO_INDEX_USED,SUM_CREATED_TMP_DISK_TABLES,FIRST_SEEN,LAST_SEEN FROM performance_schema.events_statements_summary_by_digest WHERE SCHEMA_NAME=DATABASE() AND DIGEST_TEXT IS NOT NULL ORDER BY SUM_TIMER_WAIT DESC LIMIT 20")
        query('statement_errors', "SELECT DIGEST_TEXT,COUNT_STAR,SUM_ERRORS,SUM_WARNINGS,FIRST_SEEN,LAST_SEEN FROM performance_schema.events_statements_summary_by_digest WHERE SCHEMA_NAME=DATABASE() AND SUM_ERRORS>0 ORDER BY SUM_ERRORS DESC LIMIT 12")
        names = {t['TABLE_NAME'] for t in tables}
        cols = {}
        for row in columns: cols.setdefault(row['TABLE_NAME'], set()).add(row['COLUMN_NAME'])
        for table in tables:
            name = table['TABLE_NAME']
            query('count:'+name, f'SELECT COUNT(*) total FROM `{name}`')
        print(f'Metadata and counts: {len(tables)} tables', flush=True)
        for fk in fks:
            if fk['ORDINAL_POSITION'] != 1 or sum(r['CONSTRAINT_NAME']==fk['CONSTRAINT_NAME'] and r['TABLE_NAME']==fk['TABLE_NAME'] for r in fks) > 1:
                continue
            t, col, parent, pk = (fk[k] for k in ('TABLE_NAME','COLUMN_NAME','REFERENCED_TABLE_NAME','REFERENCED_COLUMN_NAME'))
            query('fk:'+t+':'+col, f'SELECT COUNT(*) orphan_rows FROM `{t}` c LEFT JOIN `{parent}` p ON p.`{pk}`=c.`{col}` WHERE c.`{col}` IS NOT NULL AND p.`{pk}` IS NULL')
        for name, available in cols.items():
            if name not in names: continue
            for col, parent in [('empresa_id','empresas'), ('empleado_id','empleados'), ('sucursal_id','sucursales'), ('sector_id','sectores'), ('puesto_id','puestos')]:
                if col in available and parent in names and not any(f['TABLE_NAME']==name and f['COLUMN_NAME']==col for f in fks):
                    query('inferred_fk:'+name+':'+col, f'SELECT COUNT(*) orphan_rows FROM `{name}` c LEFT JOIN `{parent}` p ON p.id=c.`{col}` WHERE c.`{col}` IS NOT NULL AND p.id IS NULL')
            if {'empleado_id','empresa_id'} <= available:
                query('company:'+name, f'SELECT COUNT(*) mismatched_rows FROM `{name}` c JOIN empleados e ON e.id=c.empleado_id WHERE c.empresa_id<>e.empresa_id')
            if {'fecha_desde','fecha_hasta'} <= available:
                query('date_range:'+name, f'SELECT COUNT(*) reversed_ranges FROM `{name}` WHERE fecha_hasta<fecha_desde')
        for table, keys in [('empleados',['empresa_id','dni']),('empleados',['empresa_id','legajo']),('asistencias',['empleado_id','fecha']),('asistencia_marcas',['empleado_id','fecha','hora','accion']),('usuarios',['usuario'])]:
            if set(keys) <= cols.get(table,set()):
                group = ','.join('`'+k+'`' for k in keys)
                nonempty = ' AND '.join(f"`{k}` IS NOT NULL AND CAST(`{k}` AS CHAR)<>''" for k in keys)
                query('duplicates:'+table+':'+','.join(keys), f'SELECT COUNT(*) duplicated_groups,COALESCE(SUM(n-1),0) excess_rows FROM (SELECT COUNT(*) n FROM `{table}` WHERE {nonempty} GROUP BY {group} HAVING COUNT(*)>1) d')
        for table, column in [('asistencias','fecha'),('asistencia_marcas','fecha'),('sh_eventos','fecha_evento'),('mobile_sesiones','created_at')]:
            if column in cols.get(table,set()):
                query('freshness:'+table, f'SELECT MIN(`{column}`) first_date,MAX(`{column}`) last_date,SUM(`{column}`>DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR)+INTERVAL 1 DAY) future_rows FROM `{table}`')
        if {'fecha_ingreso','fecha_baja','activo'} <= cols.get('empleados',set()):
            query('employee_dates', 'SELECT COUNT(*) total,SUM(activo=1) active,SUM(fecha_ingreso IS NULL) missing_start,SUM(activo=0 AND fecha_baja IS NULL) inactive_without_end,SUM(fecha_baja<fecha_ingreso) reversed_dates,SUM(activo=1 AND fecha_baja<DATE(UTC_TIMESTAMP()-INTERVAL 3 HOUR)) active_past_end FROM empleados')
        if 'app_schema_versions' in names: query('bootstrap_versions', 'SELECT version,applied_at FROM app_schema_versions')
        result['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
        OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(json.dumps({'tables':len(tables),'queries':len(result['queries']),'errors':[(k,v.get('error_code')) for k,v in result['queries'].items() if 'error' in v],'output':str(OUTPUT)},ensure_ascii=True),flush=True)
    finally:
        conn.rollback()
        cursor.close()
        conn.close()


if __name__ == '__main__': main()
