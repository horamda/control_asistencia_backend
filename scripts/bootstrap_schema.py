"""Run compatibility DDL once per schema version before starting web workers."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions import bootstrap_schema, get_db, init_db
from scripts.migrate_20261008_02_epp import migrate_cursor as migrate_epp
from scripts.migrate_20261013_01_epp_conceptos import migrate_cursor as migrate_epp_concepts
from scripts.migrate_20261015_01_request_metrics import migrate_cursor as migrate_request_metrics
from scripts.migrate_20261015_02_epp_habilitaciones import migrate_cursor as migrate_epp_rules
from scripts.migrate_20261015_03_egreso_automatico import migrate_cursor as migrate_auto_exit
from scripts.migrate_20261015_03_egreso_automatico import migrate_metodo_salida as migrate_auto_exit_method
from scripts.migrate_20261015_03_egreso_automatico import migrate_ejecuciones as migrate_auto_exit_runs
from scripts.migrate_20261016_01_reuniones import migrate_cursor as migrate_meetings


def main():
    init_db()
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT GET_LOCK(CONCAT(DATABASE(), ':bootstrap'), 120)")
        if cursor.fetchone()[0] != 1:
            raise RuntimeError('Another schema migration is still running.')
        cursor.execute("CREATE TABLE IF NOT EXISTS app_schema_versions (version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        version = '20261013_compatibility_bootstrap'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            bootstrap_schema()
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261014_epp_concepts'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_epp(cursor)
            migrate_epp_concepts(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261015_request_metrics'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_request_metrics(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261015_epp_habilitaciones'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_epp_rules(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261015_egreso_automatico'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_auto_exit(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_egreso_automatico_metodo'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_auto_exit_method(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_egreso_automatico_ejecuciones'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_auto_exit_runs(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_reuniones'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_meetings(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
    finally:
        cursor.execute("SELECT RELEASE_LOCK(CONCAT(DATABASE(), ':bootstrap'))")
        cursor.fetchone()
        cursor.close()
        db.close()


if __name__ == '__main__':
    main()
