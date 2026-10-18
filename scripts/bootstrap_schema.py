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
from scripts.migrate_20261016_02_reuniones_sucursales import migrate_cursor as migrate_meeting_branches
from scripts.migrate_20261016_03_feriados import migrate_cursor as migrate_holidays
from scripts.migrate_20261016_03_feriados import migrate_unificar as migrate_holidays_calendar
from scripts.migrate_20261016_04_reuniones_reprogramar import migrate_cursor as migrate_meeting_reschedule
from scripts.migrate_20261016_05_push import migrate_cursor as migrate_push
from scripts.migrate_20261016_06_comunicados import migrate_cursor as migrate_announcements
from scripts.migrate_20261016_07_periodos_laborales import migrate_cursor as migrate_employment_periods
from scripts.migrate_20261016_08_comunicados_imagen import migrate_cursor as migrate_announcement_image
from scripts.migrate_20261016_09_push_envios_empresa import migrate_cursor as migrate_push_history_index
from scripts.migrate_20261016_10_comunicados_imagen_push import migrate_cursor as migrate_announcement_push_image
from scripts.migrate_20261016_11_push_acuses import migrate_cursor as migrate_push_receipts
from scripts.migrate_20261017_01_push_reglas import migrate_cursor as migrate_push_rules
from scripts.migrate_20261017_02_notificaciones import migrate_cursor as migrate_employee_notifications
from scripts.migrate_20261018_01_vacaciones_semanas import migrate_cursor as migrate_vacation_weeks


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
        version = '20261016_reuniones_sucursales'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_meeting_branches(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_feriados'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_holidays(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_feriados_calendario'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_holidays(cursor)
            migrate_holidays_calendar(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_reuniones_reprogramar'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_meeting_reschedule(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_push'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_push(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_comunicados'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_announcements(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_periodos_laborales'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_employment_periods(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_comunicados_imagen'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_announcement_image(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_push_envios_empresa'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_push_history_index(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_comunicados_imagen_push'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_announcement_push_image(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261016_push_acuses'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_push_receipts(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261017_push_reglas'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_push_rules(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261017_notificaciones'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_employee_notifications(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
        version = '20261018_vacaciones_semanas'
        cursor.execute('SELECT version FROM app_schema_versions WHERE version=%s', (version,))
        if not cursor.fetchone():
            cursor.execute('SET SESSION lock_wait_timeout=5')
            migrate_vacation_weeks(cursor)
            cursor.execute('INSERT INTO app_schema_versions(version) VALUES (%s)', (version,))
            db.commit()
    finally:
        cursor.execute("SELECT RELEASE_LOCK(CONCAT(DATABASE(), ':bootstrap'))")
        cursor.fetchone()
        cursor.close()
        db.close()


if __name__ == '__main__':
    main()
