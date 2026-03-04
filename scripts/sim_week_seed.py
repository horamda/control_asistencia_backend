import argparse
import datetime as dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module
from extensions import get_db
from repositories.asistencia_marca_repository import create as create_asistencia_marca
from repositories.asistencia_repository import (
    create_ausente,
    upsert_resumen_desde_marca,
)
from repositories.empleado_horario_repository import create_asignacion
from repositories.empleado_repository import create as create_empleado
from repositories.horario_dia_bloque_repository import create as create_horario_dia_bloque
from repositories.horario_dia_repository import create as create_horario_dia
from repositories.horario_repository import create as create_horario
from repositories.justificacion_repository import create as create_justificacion
from repositories.vacacion_repository import create as create_vacacion
from utils.asistencia import validar_asistencia


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Seed semanal reproducible para pruebas de asistencias"
    )
    parser.add_argument("--tag", default="SIMW260302", help="Prefijo del dataset simulado")
    parser.add_argument(
        "--start-date",
        default="2026-02-23",
        help="Fecha de inicio ISO (debe ser lunes para este escenario)",
    )
    return parser.parse_args()


def _qmarks(size: int):
    return ",".join(["%s"] * size)


def _fetch_ids(cursor, sql: str, params=()):
    cursor.execute(sql, params)
    return [int(row["id"]) for row in cursor.fetchall()]


def _delete_where_in(cursor, table: str, column: str, ids: list[int]):
    if not ids:
        return 0
    cursor.execute(
        f"DELETE FROM {table} WHERE {column} IN ({_qmarks(len(ids))})",
        tuple(ids),
    )
    return int(cursor.rowcount)


def _get_base_context():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM empresas ORDER BY id LIMIT 1")
        empresa = cursor.fetchone()
        if not empresa:
            raise RuntimeError("No hay empresas para generar la simulacion.")
        empresa_id = int(empresa["id"])

        cursor.execute(
            "SELECT id FROM sucursales WHERE empresa_id = %s ORDER BY id LIMIT 1",
            (empresa_id,),
        )
        suc = cursor.fetchone()
        if not suc:
            raise RuntimeError("No hay sucursales para la empresa base.")
        sucursal_id = int(suc["id"])

        cursor.execute(
            "SELECT id FROM sectores WHERE empresa_id = %s ORDER BY id LIMIT 1",
            (empresa_id,),
        )
        sec = cursor.fetchone()
        if not sec:
            raise RuntimeError("No hay sectores para la empresa base.")
        sector_id = int(sec["id"])

        cursor.execute(
            "SELECT id FROM puestos WHERE empresa_id = %s ORDER BY id LIMIT 1",
            (empresa_id,),
        )
        pue = cursor.fetchone()
        if not pue:
            raise RuntimeError("No hay puestos para la empresa base.")
        puesto_id = int(pue["id"])

        return {
            "empresa_id": empresa_id,
            "sucursal_id": sucursal_id,
            "sector_id": sector_id,
            "puesto_id": puesto_id,
        }
    finally:
        cursor.close()
        db.close()


def cleanup_tag(tag: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    stats: dict[str, int] = {}
    try:
        db.start_transaction()

        emp_ids = _fetch_ids(
            cursor,
            "SELECT id FROM empleados WHERE legajo LIKE %s",
            (f"{tag}-%",),
        )
        asis_ids = []
        if emp_ids:
            cursor.execute(
                f"SELECT id FROM asistencias WHERE empleado_id IN ({_qmarks(len(emp_ids))})",
                tuple(emp_ids),
            )
            asis_ids = [int(row["id"]) for row in cursor.fetchall()]

        if asis_ids:
            stats["justificaciones_por_asistencia"] = _delete_where_in(
                cursor, "justificaciones", "asistencia_id", asis_ids
            )
        else:
            stats["justificaciones_por_asistencia"] = 0

        if emp_ids:
            stats["justificaciones_por_empleado"] = _delete_where_in(
                cursor, "justificaciones", "empleado_id", emp_ids
            )
            stats["asistencia_marcas"] = _delete_where_in(
                cursor, "asistencia_marcas", "empleado_id", emp_ids
            )
            stats["asistencias"] = _delete_where_in(cursor, "asistencias", "empleado_id", emp_ids)
            stats["empleado_excepciones"] = _delete_where_in(
                cursor, "empleado_excepciones", "empleado_id", emp_ids
            )
            stats["empleado_roles"] = _delete_where_in(cursor, "empleado_roles", "empleado_id", emp_ids)
            stats["francos"] = _delete_where_in(cursor, "francos", "empleado_id", emp_ids)
            stats["empleado_horarios"] = _delete_where_in(
                cursor, "empleado_horarios", "empleado_id", emp_ids
            )
            stats["vacaciones"] = _delete_where_in(cursor, "vacaciones", "empleado_id", emp_ids)
            stats["empleados"] = _delete_where_in(cursor, "empleados", "id", emp_ids)
        else:
            stats.update(
                {
                    "justificaciones_por_empleado": 0,
                    "asistencia_marcas": 0,
                    "asistencias": 0,
                    "empleado_excepciones": 0,
                    "empleado_roles": 0,
                    "francos": 0,
                    "empleado_horarios": 0,
                    "vacaciones": 0,
                    "empleados": 0,
                }
            )

        horario_ids = _fetch_ids(
            cursor,
            "SELECT id FROM horarios WHERE nombre = %s",
            (f"{tag}-HORARIO",),
        )
        if horario_ids:
            stats["empleado_horarios_por_horario"] = _delete_where_in(
                cursor, "empleado_horarios", "horario_id", horario_ids
            )
            cursor.execute(
                f"SELECT id FROM horario_dias WHERE horario_id IN ({_qmarks(len(horario_ids))})",
                tuple(horario_ids),
            )
            dia_ids = [int(row["id"]) for row in cursor.fetchall()]
            if dia_ids:
                stats["horario_dia_bloques"] = _delete_where_in(
                    cursor, "horario_dia_bloques", "horario_dia_id", dia_ids
                )
            else:
                stats["horario_dia_bloques"] = 0

            cursor.execute("SHOW TABLES LIKE 'horario_bloques'")
            has_legacy_blocks = cursor.fetchone() is not None
            if has_legacy_blocks:
                stats["horario_bloques"] = _delete_where_in(
                    cursor, "horario_bloques", "horario_id", horario_ids
                )
            else:
                stats["horario_bloques"] = 0

            stats["horario_dias"] = _delete_where_in(cursor, "horario_dias", "horario_id", horario_ids)
            stats["horarios"] = _delete_where_in(cursor, "horarios", "id", horario_ids)
        else:
            stats.update(
                {
                    "empleado_horarios_por_horario": 0,
                    "horario_dia_bloques": 0,
                    "horario_bloques": 0,
                    "horario_dias": 0,
                    "horarios": 0,
                }
            )

        db.commit()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def _mk_date_range(start_date: dt.date, days: int):
    return [start_date + dt.timedelta(days=idx) for idx in range(days)]


def _create_shift_horario(tag: str, empresa_id: int):
    horario_id = create_horario(
        {
            "empresa_id": empresa_id,
            "nombre": f"{tag}-HORARIO",
            "tolerancia_min": 5,
            "descripcion": f"{tag} turno cortado L-V",
            "activo": 1,
        }
    )
    for iso_day in (1, 2, 3, 4, 5):
        dia_id = create_horario_dia({"horario_id": horario_id, "dia_semana": iso_day})
        create_horario_dia_bloque(
            {
                "empresa_id": empresa_id,
                "horario_dia_id": dia_id,
                "orden": 1,
                "hora_entrada": "08:00",
                "hora_salida": "12:00",
            }
        )
        create_horario_dia_bloque(
            {
                "empresa_id": empresa_id,
                "horario_dia_id": dia_id,
                "orden": 2,
                "hora_entrada": "13:00",
                "hora_salida": "17:00",
            }
        )
    return int(horario_id)


def _seed_empleados(tag: str, base_ctx: dict, fecha_desde: str, horario_id: int):
    roster = [
        ("001", "Ana", "Rios"),
        ("002", "Bruno", "Sosa"),
        ("003", "Carla", "Paz"),
        ("004", "Diego", "Luna"),
        ("005", "Elena", "Mora"),
        ("006", "Fabian", "Neri"),
        ("007", "Gina", "Vega"),
        ("008", "Hugo", "Rey"),
    ]
    empleados: dict[str, int] = {}
    for idx, (code, nombre, apellido) in enumerate(roster, start=1):
        legajo = f"{tag}-{code}"
        emp_id = create_empleado(
            {
                "empresa_id": base_ctx["empresa_id"],
                "sucursal_id": base_ctx["sucursal_id"],
                "legajo": legajo,
                "dni": str(99026000 + idx),
                "nombre": nombre,
                "apellido": apellido,
                "fecha_nacimiento": "1990-01-01",
                "sexo": "no_informa",
                "email": f"{legajo.lower()}@sim.local",
                "telefono": f"000-{idx:04d}",
                "direccion": "SIM DATASET",
                "fecha_ingreso": fecha_desde,
                "estado": "activo",
                "foto": None,
                "password_hash": None,
                "sector_id": base_ctx["sector_id"],
                "puesto_id": base_ctx["puesto_id"],
                "codigo_postal": None,
            }
        )
        create_asignacion(
            empleado_id=emp_id,
            horario_id=horario_id,
            fecha_desde=fecha_desde,
            fecha_hasta=None,
            empresa_id=base_ctx["empresa_id"],
        )
        empleados[code] = int(emp_id)
    return empleados


def _weekday_events(code: str, day_idx: int):
    # Base: two blocks by QR.
    base = [
        ("08:00", "ingreso", "qr", "bloque_1_in"),
        ("12:00", "egreso", "qr", "bloque_1_out"),
        ("13:00", "ingreso", "qr", "bloque_2_in"),
        ("17:00", "egreso", "qr", "bloque_2_out"),
    ]

    if code == "002" and day_idx in {1, 3}:
        base[0] = ("08:25", "ingreso", "qr", "llegada_tarde")

    if code == "003" and day_idx == 0:
        base = [
            ("08:00", "ingreso", "qr", "mix_qr_manual_in"),
            ("12:00", "egreso", "manual", "mix_qr_manual_out"),
            ("14:00", "ingreso", "qr", "reingreso_qr"),
            ("17:00", "egreso", "qr", "egreso_qr"),
        ]

    if code == "004" and day_idx == 2:
        return {"ausente": True, "events": []}

    if code == "005":
        if day_idx == 4:
            return {"ausente": True, "events": []}
        base[3] = ("16:20", "egreso", "qr", "salida_anticipada")

    if code == "006":
        base = [
            ("08:00", "ingreso", "manual", "manual_turno_corto_in"),
            ("12:00", "egreso", "manual", "manual_turno_corto_out"),
        ]

    if code == "007":
        if day_idx % 2 == 0:
            base = [
                ("08:00", "ingreso", "manual", "mix_a"),
                ("12:00", "egreso", "qr", "mix_b"),
                ("13:00", "ingreso", "qr", "mix_c"),
                ("17:00", "egreso", "manual", "mix_d"),
            ]
        else:
            base = [
                ("08:00", "ingreso", "qr", "mix_e"),
                ("12:00", "egreso", "manual", "mix_f"),
                ("13:00", "ingreso", "manual", "mix_g"),
                ("17:00", "egreso", "qr", "mix_h"),
            ]

    if code == "008" and day_idx == 3:
        base = [
            ("08:00", "ingreso", "qr", "jornada_in"),
            ("13:00", "egreso", "manual", "egreso_manual_retroactivo"),
            ("14:00", "ingreso", "qr", "nuevo_ingreso_qr"),
            ("17:00", "egreso", "qr", "egreso_final_qr"),
        ]

    return {"ausente": False, "events": base}


def _weekend_events(code: str, iso_day: int):
    # Explicit weekend behavior:
    # - Saturday (6): 003 and 006 work one short cycle.
    # - Sunday (7): 007 and 008 work one short cycle.
    if iso_day == 6:
        if code == "003":
            return [("09:00", "ingreso", "qr", "sabado_guardia_in"), ("13:00", "egreso", "qr", "sabado_guardia_out")]
        if code == "006":
            return [("10:00", "ingreso", "manual", "sabado_manual_in"), ("12:00", "egreso", "manual", "sabado_manual_out")]
        return []

    if iso_day == 7:
        if code == "007":
            return [("18:00", "ingreso", "qr", "domingo_extra_in"), ("22:00", "egreso", "manual", "domingo_extra_out")]
        if code == "008":
            return [("19:00", "ingreso", "manual", "domingo_mix_in"), ("21:00", "egreso", "qr", "domingo_mix_out")]
        return []

    return []


def _fichar_evento(
    *,
    tag: str,
    empresa_id: int,
    empleado_id: int,
    fecha: str,
    hora: str,
    accion: str,
    metodo: str,
    note: str,
    open_entries: dict[tuple[int, str], str],
):
    key = (empleado_id, fecha)
    if accion == "ingreso":
        _, estado_calc = validar_asistencia(empleado_id, fecha, hora, None)
        estado = estado_calc or "ok"
        hora_entrada_base = hora
    else:
        hora_entrada_base = open_entries.get(key)
        if not hora_entrada_base:
            raise RuntimeError(
                f"Secuencia invalida para empleado={empleado_id} fecha={fecha}: egreso sin ingreso abierto."
            )
        _, estado_calc = validar_asistencia(empleado_id, fecha, hora_entrada_base, hora)
        estado = estado_calc or "ok"

    observaciones = f"{tag} | {note}"

    asistencia_id = upsert_resumen_desde_marca(
        empleado_id=empleado_id,
        fecha=fecha,
        hora=hora,
        accion=accion,
        metodo=metodo,
        lat=None,
        lon=None,
        foto=None,
        estado=estado,
        observaciones=observaciones,
        gps_ok=None,
        gps_distancia_m=None,
        gps_tolerancia_m=None,
        gps_ref_lat=None,
        gps_ref_lon=None,
    )
    create_asistencia_marca(
        empresa_id=empresa_id,
        empleado_id=empleado_id,
        asistencia_id=asistencia_id,
        fecha=fecha,
        hora=hora,
        accion=accion,
        metodo=metodo,
        tipo_marca="jornada",
        lat=None,
        lon=None,
        foto=None,
        gps_ok=None,
        gps_distancia_m=None,
        gps_tolerancia_m=None,
        gps_ref_lat=None,
        gps_ref_lon=None,
        estado=estado,
        observaciones=observaciones,
    )

    if accion == "ingreso":
        open_entries[key] = hora
    else:
        open_entries.pop(key, None)

    return int(asistencia_id), estado


def seed_week(*, tag: str, start_date: dt.date):
    if start_date.isoweekday() != 1:
        raise ValueError(f"start-date={start_date.isoformat()} debe ser lunes.")

    base_ctx = _get_base_context()
    cleanup_stats = cleanup_tag(tag)

    horario_id = _create_shift_horario(tag, base_ctx["empresa_id"])
    empleados = _seed_empleados(tag, base_ctx, start_date.isoformat(), horario_id)

    open_entries: dict[tuple[int, str], str] = {}
    week_dates = _mk_date_range(start_date, 7)

    justif_refs: dict[str, int] = {}
    ausente_refs: dict[str, int] = {}

    for day_idx, day in enumerate(week_dates):
        fecha = day.isoformat()
        iso_day = day.isoweekday()
        for code, empleado_id in empleados.items():
            if iso_day <= 5:
                plan = _weekday_events(code, day_idx)
                if plan["ausente"]:
                    asistencia_id = create_ausente(
                        empleado_id,
                        fecha,
                        observaciones=f"{tag} | ausente programado",
                    )
                    ausente_refs[f"{code}-{fecha}"] = int(asistencia_id)
                    continue
                events = plan["events"]
            else:
                events = _weekend_events(code, iso_day)

            for hora, accion, metodo, note in events:
                asistencia_id, _ = _fichar_evento(
                    tag=tag,
                    empresa_id=base_ctx["empresa_id"],
                    empleado_id=empleado_id,
                    fecha=fecha,
                    hora=hora,
                    accion=accion,
                    metodo=metodo,
                    note=note,
                    open_entries=open_entries,
                )
                if code == "002" and day_idx == 1 and hora == "08:25" and accion == "ingreso":
                    justif_refs["tarde_002"] = asistencia_id
                if code == "008" and day_idx == 3 and hora == "13:00" and accion == "egreso":
                    justif_refs["manual_008"] = asistencia_id

    if open_entries:
        raise RuntimeError(f"Hay ingresos abiertos al finalizar la simulacion: {open_entries}")

    absent_004 = ausente_refs.get(f"004-{(start_date + dt.timedelta(days=2)).isoformat()}")
    if absent_004:
        create_justificacion(
            {
                "empleado_id": empleados["004"],
                "asistencia_id": absent_004,
                "motivo": f"{tag} ausencia justificada por certificado medico",
                "archivo": None,
                "estado": "pendiente",
            }
        )

    late_002 = justif_refs.get("tarde_002")
    if late_002:
        create_justificacion(
            {
                "empleado_id": empleados["002"],
                "asistencia_id": late_002,
                "motivo": f"{tag} llegada tarde justificada por corte de ruta",
                "archivo": None,
                "estado": "aprobada",
            }
        )

    manual_008 = justif_refs.get("manual_008")
    if manual_008:
        create_justificacion(
            {
                "empleado_id": empleados["008"],
                "asistencia_id": manual_008,
                "motivo": f"{tag} egreso manual por olvido de fichada",
                "archivo": None,
                "estado": "pendiente",
            }
        )

    create_vacacion(
        {
            "empleado_id": empleados["002"],
            "fecha_desde": "2026-03-12",
            "fecha_hasta": "2026-03-14",
            "observaciones": f"{tag} vacaciones proximas",
        }
    )
    create_vacacion(
        {
            "empleado_id": empleados["007"],
            "fecha_desde": "2026-03-02",
            "fecha_hasta": "2026-03-04",
            "observaciones": f"{tag} vacaciones en curso",
        }
    )

    return {
        "cleanup": cleanup_stats,
        "base_ctx": base_ctx,
        "horario_id": horario_id,
        "empleados": empleados,
        "start_date": start_date.isoformat(),
        "end_date": week_dates[-1].isoformat(),
    }


def _print_summary(tag: str, start_date: str, end_date: str):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, legajo FROM empleados WHERE legajo LIKE %s ORDER BY id",
            (f"{tag}-%",),
        )
        emps = cursor.fetchall()
        emp_ids = [int(e["id"]) for e in emps]
        print(f"tag={tag}")
        print(f"empleados={len(emps)}")
        print(f"rango={start_date}..{end_date}")

        if not emp_ids:
            return

        cursor.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM asistencias
            WHERE empleado_id IN ({_qmarks(len(emp_ids))})
              AND fecha BETWEEN %s AND %s
            """,
            (*emp_ids, start_date, end_date),
        )
        asistencias_total = int(cursor.fetchone()["c"])
        print(f"asistencias={asistencias_total}")

        cursor.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM asistencia_marcas
            WHERE empleado_id IN ({_qmarks(len(emp_ids))})
              AND fecha BETWEEN %s AND %s
            """,
            (*emp_ids, start_date, end_date),
        )
        marcas_total = int(cursor.fetchone()["c"])
        print(f"marcas={marcas_total}")

        cursor.execute(
            f"""
            SELECT estado, COUNT(*) AS c
            FROM asistencias
            WHERE empleado_id IN ({_qmarks(len(emp_ids))})
              AND fecha BETWEEN %s AND %s
            GROUP BY estado
            ORDER BY estado
            """,
            (*emp_ids, start_date, end_date),
        )
        print("estados:")
        for row in cursor.fetchall():
            print(f"  - {row['estado']}: {int(row['c'])}")

        cursor.execute(
            f"""
            SELECT fecha, COUNT(*) AS c
            FROM asistencias
            WHERE empleado_id IN ({_qmarks(len(emp_ids))})
              AND fecha BETWEEN %s AND %s
            GROUP BY fecha
            ORDER BY fecha
            """,
            (*emp_ids, start_date, end_date),
        )
        print("asistencias_por_fecha:")
        for row in cursor.fetchall():
            print(f"  - {row['fecha']}: {int(row['c'])}")

        cursor.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM justificaciones
            WHERE empleado_id IN ({_qmarks(len(emp_ids))})
            """,
            tuple(emp_ids),
        )
        print(f"justificaciones={int(cursor.fetchone()['c'])}")

        cursor.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM vacaciones
            WHERE empleado_id IN ({_qmarks(len(emp_ids))})
            """,
            tuple(emp_ids),
        )
        print(f"vacaciones={int(cursor.fetchone()['c'])}")

        cursor.execute(
            """
            SELECT COUNT(*) AS c
            FROM asistencia_marcas am
            JOIN empleados e ON e.id = am.empleado_id
            WHERE e.legajo = %s
              AND am.fecha = %s
              AND am.hora = %s
              AND am.accion = 'ingreso'
              AND am.metodo = 'qr'
            """,
            (f"{tag}-003", start_date, "08:00"),
        )
        seq_start = int(cursor.fetchone()["c"])
        print(f"check_seq_start_ingreso_qr={seq_start}")
    finally:
        cursor.close()
        db.close()


def main():
    args = _parse_args()
    start_date = dt.date.fromisoformat(args.start_date)

    app_module.create_app()
    result = seed_week(tag=args.tag, start_date=start_date)

    print("cleanup:")
    for key, value in sorted(result["cleanup"].items()):
        print(f"  - {key}: {value}")
    print(f"horario_id={result['horario_id']}")
    print(f"empresa_id={result['base_ctx']['empresa_id']}")
    _print_summary(args.tag, result["start_date"], result["end_date"])


if __name__ == "__main__":
    main()
