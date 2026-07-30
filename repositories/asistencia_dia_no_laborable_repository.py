from __future__ import annotations

import datetime as dt

from extensions import get_db


def _scope_id(value: int | None) -> int:
    return int(value or 0)


def get_dates(
    *,
    year: int,
    month: int,
    empresa_id: int | None = None,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
) -> set[str]:
    first = dt.date(int(year), int(month), 1)
    if month == 12:
        last = dt.date(int(year) + 1, 1, 1) - dt.timedelta(days=1)
    else:
        last = dt.date(int(year), int(month) + 1, 1) - dt.timedelta(days=1)

    scopes: list[tuple[int, int, int]] = [(0, 0, 0)]
    emp = _scope_id(empresa_id)
    suc = _scope_id(sucursal_id)
    sec = _scope_id(sector_id)
    if emp:
        scopes.append((emp, 0, 0))
    if emp and suc:
        scopes.append((emp, suc, 0))
    if emp and sec:
        scopes.append((emp, 0, sec))
    if emp and suc and sec:
        scopes.append((emp, suc, sec))

    where_scopes = " OR ".join(["(empresa_id = %s AND sucursal_id = %s AND sector_id = %s)" for _ in scopes])
    params: list[object] = [first.isoformat(), last.isoformat()]
    for scope in scopes:
        params.extend(scope)

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            f"""
            SELECT fecha
            FROM asistencia_dias_no_laborables
            WHERE fecha BETWEEN %s AND %s
              AND ({where_scopes})
            ORDER BY fecha
            """,
            params,
        )
        return {row["fecha"].isoformat() if hasattr(row["fecha"], "isoformat") else str(row["fecha"]) for row in cursor.fetchall()}
    finally:
        cursor.close()
        db.close()


def replace_month_dates(
    *,
    year: int,
    month: int,
    dates: set[str],
    empresa_id: int | None = None,
    sucursal_id: int | None = None,
    sector_id: int | None = None,
    actor_id: int | None = None,
) -> int:
    first = dt.date(int(year), int(month), 1)
    if month == 12:
        last = dt.date(int(year) + 1, 1, 1) - dt.timedelta(days=1)
    else:
        last = dt.date(int(year), int(month) + 1, 1) - dt.timedelta(days=1)

    normalized = []
    for value in dates or set():
        try:
            parsed = dt.date.fromisoformat(str(value))
        except ValueError:
            continue
        if first <= parsed <= last:
            normalized.append(parsed.isoformat())
    normalized = sorted(set(normalized))

    emp = _scope_id(empresa_id)
    suc = _scope_id(sucursal_id)
    sec = _scope_id(sector_id)
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM asistencia_dias_no_laborables
            WHERE empresa_id = %s
              AND sucursal_id = %s
              AND sector_id = %s
              AND fecha BETWEEN %s AND %s
            """,
            (emp, suc, sec, first.isoformat(), last.isoformat()),
        )
        if normalized:
            cursor.executemany(
                """
                INSERT INTO asistencia_dias_no_laborables (
                    empresa_id,
                    sucursal_id,
                    sector_id,
                    fecha,
                    created_by_usuario_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                [(emp, suc, sec, fecha, actor_id) for fecha in normalized],
            )
        db.commit()
        return len(normalized)
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()
