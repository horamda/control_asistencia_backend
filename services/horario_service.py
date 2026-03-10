import datetime

from extensions import get_db


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    text = str(value or "").strip().lower()
    return text in {"1", "true", "si", "yes", "on"}


def _parse_int(value, field_name: str):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} debe ser numerico.")


def _normalize_time(value, field_name: str):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} es requerido.")
    candidates = [text]
    if len(text) == 5:
        candidates.append(f"{text}:00")
    for raw in candidates:
        try:
            parsed = datetime.time.fromisoformat(raw)
            return parsed.strftime("%H:%M:%S")
        except ValueError:
            pass
    raise ValueError(f"{field_name} invalido. Use HH:MM.")


def _to_minutes(value):
    if isinstance(value, datetime.time):
        return value.hour * 60 + value.minute
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 5:
        text = f"{text}:00"
    parsed = datetime.time.fromisoformat(text)
    return parsed.hour * 60 + parsed.minute


def _format_hhmm(value):
    if isinstance(value, datetime.timedelta):
        total_minutes = int(value.total_seconds() // 60)
        hours = (total_minutes // 60) % 24
        minutes = total_minutes % 60
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return text[:5]


def _normalize_bloques(raw_bloques, dia_semana: int):
    if not isinstance(raw_bloques, list):
        raise ValueError(f"Bloques invalidos para dia {dia_semana}.")

    parsed = []
    for i, bloque in enumerate(raw_bloques, start=1):
        if not isinstance(bloque, dict):
            raise ValueError(f"Bloque {i} del dia {dia_semana} invalido.")
        entrada = _normalize_time(
            bloque.get("entrada", bloque.get("hora_entrada")),
            f"Entrada bloque {i} dia {dia_semana}",
        )
        salida = _normalize_time(
            bloque.get("salida", bloque.get("hora_salida")),
            f"Salida bloque {i} dia {dia_semana}",
        )
        if _to_minutes(entrada) >= _to_minutes(salida):
            raise ValueError(f"Bloque {i} del dia {dia_semana}: entrada debe ser menor a salida.")
        parsed.append({
            "hora_entrada": entrada,
            "hora_salida": salida,
        })

    parsed.sort(key=lambda b: _to_minutes(b["hora_entrada"]))
    previous_end = None
    for i, bloque in enumerate(parsed, start=1):
        start_min = _to_minutes(bloque["hora_entrada"])
        end_min = _to_minutes(bloque["hora_salida"])
        if previous_end is not None and start_min < previous_end:
            raise ValueError(f"Hay bloques superpuestos en dia {dia_semana}.")
        previous_end = end_min
        bloque["orden"] = i
    return parsed


def _normalize_dias(raw_dias):
    if not isinstance(raw_dias, list):
        raise ValueError("dias debe ser una lista.")

    dias = []
    seen = set()
    for item in raw_dias:
        if not isinstance(item, dict):
            raise ValueError("Cada dia debe ser un objeto.")
        dia_semana = _parse_int(item.get("dia_semana"), "dia_semana")
        if dia_semana is None or dia_semana < 1 or dia_semana > 7:
            raise ValueError("dia_semana debe estar entre 1 y 7.")
        if dia_semana in seen:
            raise ValueError(f"dia_semana {dia_semana} repetido.")
        seen.add(dia_semana)
        bloques = _normalize_bloques(item.get("bloques") or [], dia_semana)
        if not bloques:
            continue
        dias.append({
            "dia_semana": dia_semana,
            "bloques": bloques,
        })

    if not dias:
        raise ValueError("Debe informar al menos un dia con bloques.")
    dias.sort(key=lambda d: d["dia_semana"])
    return dias


def _normalize_payload(data: dict):
    if not isinstance(data, dict):
        raise ValueError("Payload invalido.")

    empresa_id = _parse_int(data.get("empresa_id"), "empresa_id")
    if not empresa_id:
        raise ValueError("empresa_id es requerido.")
    sucursal_id = _parse_int(data.get("sucursal_id"), "sucursal_id")
    if not sucursal_id:
        raise ValueError("sucursal_id es requerido.")

    nombre = str(data.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("nombre es requerido.")

    tolerancia = _parse_int(data.get("tolerancia_min"), "tolerancia_min")
    if tolerancia is None:
        tolerancia = 5
    if tolerancia < 0:
        raise ValueError("tolerancia_min no puede ser negativa.")

    descripcion = str(data.get("descripcion") or "").strip() or None
    activo = _to_bool(data.get("activo", True))
    dias = _normalize_dias(data.get("dias") or [])

    return {
        "empresa_id": empresa_id,
        "sucursal_id": sucursal_id,
        "nombre": nombre,
        "tolerancia_min": tolerancia,
        "descripcion": descripcion,
        "activo": activo,
        "dias": dias,
    }


def get_horarios_resumen(include_inactive: bool = True):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        where = "" if include_inactive else "WHERE h.activo = 1"
        cursor.execute(f"""
            SELECT
                h.id,
                h.empresa_id,
                e.razon_social AS empresa_nombre,
                h.sucursal_id,
                s.nombre AS sucursal_nombre,
                h.nombre,
                h.tolerancia_min,
                h.descripcion,
                h.activo,
                COUNT(DISTINCT hd.id) AS dias_count,
                COUNT(hdb.id) AS bloques_count
            FROM horarios h
            JOIN empresas e ON e.id = h.empresa_id
            LEFT JOIN sucursales s ON s.id = h.sucursal_id
            LEFT JOIN horario_dias hd ON hd.horario_id = h.id
            LEFT JOIN horario_dia_bloques hdb ON hdb.horario_dia_id = hd.id
            {where}
            GROUP BY h.id, h.empresa_id, e.razon_social, h.sucursal_id, s.nombre, h.nombre, h.tolerancia_min, h.descripcion, h.activo
            ORDER BY e.razon_social, s.nombre, h.nombre
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        db.close()


def get_horario_estructurado(horario_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                h.*,
                e.razon_social AS empresa_nombre,
                s.nombre AS sucursal_nombre
            FROM horarios h
            JOIN empresas e ON e.id = h.empresa_id
            LEFT JOIN sucursales s ON s.id = h.sucursal_id
            WHERE h.id = %s
        """, (horario_id,))
        horario = cursor.fetchone()
        if not horario:
            return None

        cursor.execute("""
            SELECT id, dia_semana
            FROM horario_dias
            WHERE horario_id = %s
            ORDER BY dia_semana
        """, (horario_id,))
        dias_rows = cursor.fetchall()

        dias = []
        for d in dias_rows:
            cursor.execute("""
                SELECT orden, hora_entrada, hora_salida
                FROM horario_dia_bloques
                WHERE horario_dia_id = %s
                ORDER BY orden
            """, (d["id"],))
            bloques_rows = cursor.fetchall()
            bloques = []
            for b in bloques_rows:
                entrada = _format_hhmm(b.get("hora_entrada"))
                salida = _format_hhmm(b.get("hora_salida"))
                bloques.append({
                    "entrada": entrada,
                    "salida": salida,
                })
            dias.append({
                "dia_semana": d["dia_semana"],
                "bloques": bloques,
            })

        return {
            "id": horario["id"],
            "empresa_id": horario["empresa_id"],
            "empresa_nombre": horario["empresa_nombre"],
            "sucursal_id": horario.get("sucursal_id"),
            "sucursal_nombre": horario.get("sucursal_nombre"),
            "nombre": horario["nombre"],
            "tolerancia_min": horario["tolerancia_min"],
            "descripcion": horario["descripcion"],
            "activo": horario["activo"],
            "dias": dias,
        }
    finally:
        cursor.close()
        db.close()


def create_horario_estructurado(data: dict):
    payload = _normalize_payload(data)
    db = get_db()
    cursor = db.cursor()
    try:
        db.start_transaction()
        cursor.execute(
            """
            SELECT id
            FROM sucursales
            WHERE id = %s
              AND empresa_id = %s
            LIMIT 1
            """,
            (payload["sucursal_id"], payload["empresa_id"]),
        )
        if not cursor.fetchone():
            raise ValueError("sucursal_id invalido para la empresa seleccionada.")
        cursor.execute("""
            INSERT INTO horarios (empresa_id, sucursal_id, nombre, tolerancia_min, descripcion, activo)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            payload["empresa_id"],
            payload["sucursal_id"],
            payload["nombre"],
            payload["tolerancia_min"],
            payload["descripcion"],
            1 if payload["activo"] else 0,
        ))
        horario_id = cursor.lastrowid

        for dia in payload["dias"]:
            cursor.execute("""
                INSERT INTO horario_dias (horario_id, dia_semana)
                VALUES (%s,%s)
            """, (horario_id, dia["dia_semana"]))
            dia_id = cursor.lastrowid

            for bloque in dia["bloques"]:
                cursor.execute("""
                    INSERT INTO horario_dia_bloques (empresa_id, horario_dia_id, orden, hora_entrada, hora_salida)
                    VALUES (%s,%s,%s,%s,%s)
                """, (
                    payload["empresa_id"],
                    dia_id,
                    bloque["orden"],
                    bloque["hora_entrada"],
                    bloque["hora_salida"],
                ))

        db.commit()
        return horario_id
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def update_horario_estructurado(horario_id: int, data: dict):
    payload = _normalize_payload(data)
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()

        cursor.execute("SELECT id FROM horarios WHERE id = %s FOR UPDATE", (horario_id,))
        if not cursor.fetchone():
            raise ValueError("Horario no encontrado.")
        cursor.execute(
            """
            SELECT id
            FROM sucursales
            WHERE id = %s
              AND empresa_id = %s
            LIMIT 1
            """,
            (payload["sucursal_id"], payload["empresa_id"]),
        )
        if not cursor.fetchone():
            raise ValueError("sucursal_id invalido para la empresa seleccionada.")

        cursor.execute("""
            UPDATE horarios
            SET empresa_id = %s,
                sucursal_id = %s,
                nombre = %s,
                tolerancia_min = %s,
                descripcion = %s,
                activo = %s
            WHERE id = %s
        """, (
            payload["empresa_id"],
            payload["sucursal_id"],
            payload["nombre"],
            payload["tolerancia_min"],
            payload["descripcion"],
            1 if payload["activo"] else 0,
            horario_id,
        ))

        cursor.execute("DELETE FROM horario_dias WHERE horario_id = %s", (horario_id,))

        for dia in payload["dias"]:
            cursor.execute("""
                INSERT INTO horario_dias (horario_id, dia_semana)
                VALUES (%s,%s)
            """, (horario_id, dia["dia_semana"]))
            dia_id = cursor.lastrowid
            for bloque in dia["bloques"]:
                cursor.execute("""
                    INSERT INTO horario_dia_bloques (empresa_id, horario_dia_id, orden, hora_entrada, hora_salida)
                    VALUES (%s,%s,%s,%s,%s)
                """, (
                    payload["empresa_id"],
                    dia_id,
                    bloque["orden"],
                    bloque["hora_entrada"],
                    bloque["hora_salida"],
                ))

        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()


def delete_horario_estructurado(horario_id: int):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        db.start_transaction()
        cursor.execute("SELECT id FROM horarios WHERE id = %s FOR UPDATE", (horario_id,))
        if not cursor.fetchone():
            raise ValueError("Horario no encontrado.")

        cursor.execute("""
            SELECT 1
            FROM empleado_horarios
            WHERE horario_id = %s
            LIMIT 1
        """, (horario_id,))
        if cursor.fetchone():
            raise ValueError("No se puede eliminar: el horario tiene asignaciones de empleados.")

        cursor.execute("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = 'horario_bloques'
            LIMIT 1
        """)
        if cursor.fetchone():
            # Compatibilidad con datos legacy donde se uso horario_bloques.
            cursor.execute("DELETE FROM horario_bloques WHERE horario_id = %s", (horario_id,))

        cursor.execute("DELETE FROM horario_dias WHERE horario_id = %s", (horario_id,))
        cursor.execute("DELETE FROM horarios WHERE id = %s", (horario_id,))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        cursor.close()
        db.close()
