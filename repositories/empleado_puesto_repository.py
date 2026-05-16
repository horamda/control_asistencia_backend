from extensions import get_db


def get_puestos_ids_by_empleado(empleado_id: int) -> list[int]:
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT puesto_id
            FROM empleado_puestos
            WHERE empleado_id = %s
              AND activo = 1
            ORDER BY puesto_id
            """,
            (empleado_id,),
        )
        return [int(row["puesto_id"]) for row in cursor.fetchall()]
    finally:
        cursor.close()
        db.close()


def replace_for_empleado(
    empleado_id: int,
    *,
    empresa_id: int,
    sector_id: int,
    puesto_ids: list[int],
    puesto_principal_id: int | None = None,
):
    db = get_db()
    cursor = db.cursor()
    try:
        normalized_ids = []
        seen = set()
        for puesto_id in puesto_ids or []:
            puesto_id = int(puesto_id)
            if puesto_principal_id and puesto_id == int(puesto_principal_id):
                continue
            if puesto_id in seen:
                continue
            seen.add(puesto_id)
            normalized_ids.append(puesto_id)

        cursor.execute(
            "DELETE FROM empleado_puestos WHERE empleado_id = %s",
            (empleado_id,),
        )
        for puesto_id in normalized_ids:
            cursor.execute(
                """
                INSERT INTO empleado_puestos (
                    empleado_id,
                    empresa_id,
                    sector_id,
                    puesto_id,
                    activo
                )
                VALUES (%s,%s,%s,%s,1)
                """,
                (empleado_id, empresa_id, sector_id, puesto_id),
            )
        db.commit()
        return True
    finally:
        cursor.close()
        db.close()
