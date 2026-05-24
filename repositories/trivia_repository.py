import datetime

from extensions import get_db


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _one(cursor) -> dict | None:
    return cursor.fetchone()


def _all(cursor) -> list[dict]:
    return cursor.fetchall() or []


def _now() -> datetime.datetime:
    return datetime.datetime.now()


# ---------------------------------------------------------------------------
# TRIVIAS
# ---------------------------------------------------------------------------

def get_trivia_by_id(trivia_id: int) -> dict | None:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM trivias WHERE id = %s LIMIT 1", (int(trivia_id),))
        return _one(cur)
    finally:
        cur.close(); db.close()


def get_trivias_activas() -> list[dict]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT * FROM trivias WHERE estado = 'activa' ORDER BY fecha_inicio DESC"
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def get_trivia_activa_para_empleado(empleado_id: int) -> dict | None:
    """Devuelve la trivia activa visible para el empleado según sus sectores asignados."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT t.*
            FROM trivias t
            WHERE t.estado = 'activa'
              AND (
                  -- Sin sectores asignados → aplica a todos
                  NOT EXISTS (SELECT 1 FROM trivia_sectores ts WHERE ts.trivia_id = t.id)
                  OR
                  -- El sector del empleado está en la lista
                  EXISTS (
                      SELECT 1 FROM trivia_sectores ts
                      WHERE ts.trivia_id = t.id
                        AND ts.sector_id = (
                            SELECT e.sector_id FROM empleados e WHERE e.id = %s LIMIT 1
                        )
                  )
              )
            ORDER BY t.fecha_inicio DESC
            LIMIT 1
            """,
            (int(empleado_id),),
        )
        return _one(cur)
    finally:
        cur.close(); db.close()


def get_sectores_trivia(trivia_id: int) -> list[dict]:
    """Devuelve [{id, nombre}, ...] de los sectores asignados a la trivia."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT s.id, s.nombre
            FROM trivia_sectores ts
            JOIN sectores s ON s.id = ts.sector_id
            WHERE ts.trivia_id = %s
            ORDER BY s.nombre
            """,
            (int(trivia_id),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def set_sectores_trivia(trivia_id: int, sector_ids: list[int]):
    """Reemplaza los sectores de una trivia (DELETE + INSERT en una transacción)."""
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM trivia_sectores WHERE trivia_id = %s", (int(trivia_id),))
        if sector_ids:
            cur.executemany(
                "INSERT INTO trivia_sectores (trivia_id, sector_id) VALUES (%s, %s)",
                [(int(trivia_id), int(sid)) for sid in sector_ids],
            )
        db.commit()
    finally:
        cur.close(); db.close()


def get_trivias_a_activar() -> list[dict]:
    """Trivias programadas cuya fecha_inicio ya llegó."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT * FROM trivias WHERE estado = 'programada' AND fecha_inicio <= %s",
            (_now(),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def get_trivias_a_finalizar() -> list[dict]:
    """Trivias activas cuya fecha_fin ya llegó."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT * FROM trivias WHERE estado = 'activa' AND fecha_fin <= %s",
            (_now(),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def get_trivias_page(page: int, per_page: int, *, estado: str | None = None,
                     anio: int | None = None) -> tuple[list[dict], int]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        where, params = [], []
        if estado:
            where.append("estado = %s"); params.append(estado)
        if anio:
            where.append("anio = %s"); params.append(int(anio))
        clause = ("WHERE " + " AND ".join(where)) if where else ""

        cur.execute(f"SELECT COUNT(*) AS total FROM trivias {clause}", params)
        total = (_one(cur) or {}).get("total", 0)

        offset = (page - 1) * per_page
        cur.execute(
            f"SELECT * FROM trivias {clause} ORDER BY id DESC LIMIT %s OFFSET %s",
            params + [per_page, offset],
        )
        return _all(cur), int(total)
    finally:
        cur.close(); db.close()


def get_trivias_finalizadas(page: int, per_page: int) -> tuple[list[dict], int]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("SELECT COUNT(*) AS total FROM trivias WHERE estado = 'finalizada'")
        total = (_one(cur) or {}).get("total", 0)

        offset = (page - 1) * per_page
        cur.execute(
            """
            SELECT t.*,
                   tg.empleado_nombre AS ganador_nombre,
                   tg.empleado_dni    AS ganador_dni,
                   tg.puntos_total    AS ganador_puntos
            FROM trivias t
            LEFT JOIN trivia_ganadores tg ON tg.trivia_id = t.id
            WHERE t.estado = 'finalizada'
            ORDER BY t.fecha_fin DESC
            LIMIT %s OFFSET %s
            """,
            (per_page, offset),
        )
        return _all(cur), int(total)
    finally:
        cur.close(); db.close()


def create_trivia(data: dict) -> int:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO trivias
                (titulo, descripcion, fecha_inicio, fecha_fin, estado,
                 premio, mensaje_ganador, anio)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                data["titulo"], data.get("descripcion"),
                data["fecha_inicio"], data["fecha_fin"],
                data.get("estado", "programada"),
                data.get("premio"), data.get("mensaje_ganador"),
                int(data["anio"]),
            ),
        )
        trivia_id = cur.lastrowid
        sector_ids = [int(s) for s in (data.get("sector_ids") or [])]
        if sector_ids:
            cur.executemany(
                "INSERT INTO trivia_sectores (trivia_id, sector_id) VALUES (%s, %s)",
                [(trivia_id, sid) for sid in sector_ids],
            )
        db.commit()
        return trivia_id
    finally:
        cur.close(); db.close()


def update_trivia(trivia_id: int, data: dict):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            UPDATE trivias
            SET titulo=%s, descripcion=%s, fecha_inicio=%s, fecha_fin=%s,
                estado=%s, premio=%s, mensaje_ganador=%s, anio=%s
            WHERE id=%s
            """,
            (
                data["titulo"], data.get("descripcion"),
                data["fecha_inicio"], data["fecha_fin"],
                data.get("estado", "programada"),
                data.get("premio"), data.get("mensaje_ganador"),
                int(data["anio"]),
                int(trivia_id),
            ),
        )
        sector_ids = [int(s) for s in (data.get("sector_ids") or [])]
        cur.execute("DELETE FROM trivia_sectores WHERE trivia_id = %s", (int(trivia_id),))
        if sector_ids:
            cur.executemany(
                "INSERT INTO trivia_sectores (trivia_id, sector_id) VALUES (%s, %s)",
                [(int(trivia_id), sid) for sid in sector_ids],
            )
        db.commit()
    finally:
        cur.close(); db.close()


def set_trivia_estado(trivia_id: int, estado: str):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "UPDATE trivias SET estado = %s WHERE id = %s",
            (estado, int(trivia_id)),
        )
        db.commit()
    finally:
        cur.close(); db.close()


# ---------------------------------------------------------------------------
# PREGUNTAS
# ---------------------------------------------------------------------------

def get_preguntas_para_jugar(trivia_id: int) -> list[dict]:
    """Sin campo respuesta_correcta para no exponerlo al cliente."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id, trivia_id, texto, opcion_a, opcion_b, opcion_c, opcion_d,
                   puntos, orden
            FROM trivia_preguntas
            WHERE trivia_id = %s AND activa = 1
            ORDER BY orden ASC, id ASC
            """,
            (int(trivia_id),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def get_preguntas_admin(trivia_id: int) -> list[dict]:
    """Con respuesta_correcta, solo para panel admin."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT * FROM trivia_preguntas
            WHERE trivia_id = %s
            ORDER BY orden ASC, id ASC
            """,
            (int(trivia_id),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def get_pregunta_by_id(pregunta_id: int) -> dict | None:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT * FROM trivia_preguntas WHERE id = %s LIMIT 1", (int(pregunta_id),)
        )
        return _one(cur)
    finally:
        cur.close(); db.close()


def create_pregunta(trivia_id: int, data: dict) -> int:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO trivia_preguntas
                (trivia_id, texto, opcion_a, opcion_b, opcion_c, opcion_d,
                 respuesta_correcta, puntos, activa, orden)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(trivia_id),
                data["texto"],
                data["opcion_a"], data["opcion_b"],
                data["opcion_c"], data["opcion_d"],
                data["respuesta_correcta"].upper(),
                int(data.get("puntos", 10)),
                int(data.get("activa", 1)),
                int(data.get("orden", 0)),
            ),
        )
        db.commit()
        return cur.lastrowid
    finally:
        cur.close(); db.close()


def update_pregunta(pregunta_id: int, data: dict):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            UPDATE trivia_preguntas
            SET texto=%s, opcion_a=%s, opcion_b=%s, opcion_c=%s, opcion_d=%s,
                respuesta_correcta=%s, puntos=%s, activa=%s, orden=%s
            WHERE id=%s
            """,
            (
                data["texto"],
                data["opcion_a"], data["opcion_b"],
                data["opcion_c"], data["opcion_d"],
                data["respuesta_correcta"].upper(),
                int(data.get("puntos", 10)),
                int(data.get("activa", 1)),
                int(data.get("orden", 0)),
                int(pregunta_id),
            ),
        )
        db.commit()
    finally:
        cur.close(); db.close()


def delete_pregunta(pregunta_id: int):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM trivia_preguntas WHERE id = %s", (int(pregunta_id),))
        db.commit()
    finally:
        cur.close(); db.close()


# ---------------------------------------------------------------------------
# RESULTADOS (participación)
# ---------------------------------------------------------------------------

def get_resultado_by_trivia_empleado(trivia_id: int, empleado_id: int) -> dict | None:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT * FROM trivia_resultados
            WHERE trivia_id = %s AND empleado_id = %s
            LIMIT 1
            """,
            (int(trivia_id), int(empleado_id)),
        )
        return _one(cur)
    finally:
        cur.close(); db.close()


def create_resultado_inicio(trivia_id: int, empleado_id: int, empleado_dni: str) -> int:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO trivia_resultados
                (trivia_id, empleado_id, empleado_dni, fecha_inicio_participacion, estado_resultado)
            VALUES (%s, %s, %s, %s, 'en_progreso')
            """,
            (int(trivia_id), int(empleado_id), empleado_dni, _now()),
        )
        db.commit()
        return cur.lastrowid
    finally:
        cur.close(); db.close()


def update_resultado_final(resultado_id: int, data: dict):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            UPDATE trivia_resultados
            SET fecha_finalizacion      = %s,
                tiempo_total_segundos   = %s,
                puntos_total            = %s,
                correctas               = %s,
                incorrectas             = %s,
                estado_resultado        = 'completado'
            WHERE id = %s
            """,
            (
                data["fecha_finalizacion"],
                int(data["tiempo_total_segundos"]),
                int(data["puntos_total"]),
                int(data["correctas"]),
                int(data["incorrectas"]),
                int(resultado_id),
            ),
        )
        db.commit()
    finally:
        cur.close(); db.close()


def get_ranking_trivia(trivia_id: int) -> list[dict]:
    """
    Ranking ordenado: puntaje DESC, tiempo ASC, inicio ASC, fin ASC.
    Solo participaciones completadas.
    """
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT
                tr.*,
                CONCAT(e.apellido, ' ', e.nombre) AS empleado_nombre,
                e.sector_id
            FROM trivia_resultados tr
            JOIN empleados e ON e.id = tr.empleado_id
            WHERE tr.trivia_id = %s AND tr.estado_resultado = 'completado'
            ORDER BY
                tr.puntos_total            DESC,
                tr.tiempo_total_segundos   ASC,
                tr.fecha_inicio_participacion ASC,
                tr.fecha_finalizacion      ASC
            """,
            (int(trivia_id),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def set_posiciones_ranking(trivia_id: int, ordered_ids: list[int]):
    """Actualiza posicion y es_ganador para todos los resultados de una trivia."""
    if not ordered_ids:
        return
    db = get_db()
    cur = db.cursor()
    try:
        for pos, resultado_id in enumerate(ordered_ids, start=1):
            cur.execute(
                """
                UPDATE trivia_resultados
                SET posicion = %s, es_ganador = %s
                WHERE id = %s AND trivia_id = %s
                """,
                (pos, 1 if pos == 1 else 0, int(resultado_id), int(trivia_id)),
            )
        db.commit()
    finally:
        cur.close(); db.close()


def get_historial_empleado(empleado_id: int) -> list[dict]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT
                tr.*,
                t.titulo, t.descripcion, t.fecha_inicio, t.fecha_fin,
                t.premio, t.mensaje_ganador, t.estado AS estado_trivia
            FROM trivia_resultados tr
            JOIN trivias t ON t.id = tr.trivia_id
            WHERE tr.empleado_id = %s
            ORDER BY tr.fecha_inicio_participacion DESC
            """,
            (int(empleado_id),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


# ---------------------------------------------------------------------------
# RESPUESTAS individuales
# ---------------------------------------------------------------------------

def save_respuesta(data: dict) -> int:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO trivia_respuestas
                (trivia_id, pregunta_id, empleado_id, empleado_dni,
                 respuesta_seleccionada, correcta, puntos_obtenidos,
                 tiempo_respuesta_segundos, fecha_respuesta)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(data["trivia_id"]),
                int(data["pregunta_id"]),
                int(data["empleado_id"]),
                data["empleado_dni"],
                data["respuesta_seleccionada"].upper(),
                int(data["correcta"]),
                int(data["puntos_obtenidos"]),
                data.get("tiempo_respuesta_segundos"),
                data.get("fecha_respuesta") or _now(),
            ),
        )
        db.commit()
        return cur.lastrowid
    finally:
        cur.close(); db.close()


def save_respuestas_bulk(rows: list[dict]):
    """Inserta múltiples respuestas en una sola transacción."""
    if not rows:
        return
    db = get_db()
    cur = db.cursor()
    try:
        values = [
            (
                int(r["trivia_id"]), int(r["pregunta_id"]),
                int(r["empleado_id"]), r["empleado_dni"],
                r["respuesta_seleccionada"].upper(),
                int(r["correcta"]), int(r["puntos_obtenidos"]),
                r.get("tiempo_respuesta_segundos"),
                r.get("fecha_respuesta") or _now(),
            )
            for r in rows
        ]
        cur.executemany(
            """
            INSERT INTO trivia_respuestas
                (trivia_id, pregunta_id, empleado_id, empleado_dni,
                 respuesta_seleccionada, correcta, puntos_obtenidos,
                 tiempo_respuesta_segundos, fecha_respuesta)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            values,
        )
        db.commit()
    finally:
        cur.close(); db.close()


# ---------------------------------------------------------------------------
# GANADORES
# ---------------------------------------------------------------------------

def save_ganador(data: dict):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT INTO trivia_ganadores
                (trivia_id, empleado_id, empleado_dni, empleado_nombre,
                 puntos_total, tiempo_total_segundos, posicion)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                empleado_id           = VALUES(empleado_id),
                empleado_dni          = VALUES(empleado_dni),
                empleado_nombre       = VALUES(empleado_nombre),
                puntos_total          = VALUES(puntos_total),
                tiempo_total_segundos = VALUES(tiempo_total_segundos),
                posicion              = VALUES(posicion)
            """,
            (
                int(data["trivia_id"]),
                int(data["empleado_id"]),
                data["empleado_dni"],
                data.get("empleado_nombre"),
                data.get("puntos_total"),
                data.get("tiempo_total_segundos"),
                data.get("posicion", 1),
            ),
        )
        db.commit()
    finally:
        cur.close(); db.close()


def get_ganador_trivia(trivia_id: int) -> dict | None:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT tg.*, t.titulo, t.premio, t.mensaje_ganador
            FROM trivia_ganadores tg
            JOIN trivias t ON t.id = tg.trivia_id
            WHERE tg.trivia_id = %s
            LIMIT 1
            """,
            (int(trivia_id),),
        )
        return _one(cur)
    finally:
        cur.close(); db.close()


def get_historial_con_ganadores(page: int, per_page: int) -> tuple[list[dict], int]:
    return get_trivias_finalizadas(page, per_page)


# ---------------------------------------------------------------------------
# NOTIFICACIONES
# ---------------------------------------------------------------------------

def get_empleados_sin_participar(trivia_id: int) -> list[dict]:
    """Empleados activos que deberían ver la trivia y aún no participaron."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT e.id AS empleado_id, e.dni AS empleado_dni,
                   CONCAT(e.apellido, ' ', e.nombre) AS empleado_nombre
            FROM empleados e
            WHERE e.activo = 1
              AND (
                  NOT EXISTS (SELECT 1 FROM trivia_sectores ts WHERE ts.trivia_id = %s)
                  OR EXISTS (
                      SELECT 1 FROM trivia_sectores ts
                      WHERE ts.trivia_id = %s AND ts.sector_id = e.sector_id
                  )
              )
              AND e.id NOT IN (
                  SELECT empleado_id FROM trivia_resultados WHERE trivia_id = %s
              )
            """,
            (int(trivia_id), int(trivia_id), int(trivia_id)),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def exists_notificacion(trivia_id: int, empleado_id: int, tipo: str) -> bool:
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            SELECT 1 FROM trivia_notificaciones
            WHERE trivia_id = %s AND empleado_id = %s AND tipo = %s
            LIMIT 1
            """,
            (int(trivia_id), int(empleado_id), tipo),
        )
        return cur.fetchone() is not None
    finally:
        cur.close(); db.close()


def save_notificacion(data: dict):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            INSERT IGNORE INTO trivia_notificaciones
                (trivia_id, empleado_id, empleado_dni, tipo, mensaje)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                int(data["trivia_id"]),
                int(data["empleado_id"]),
                data["empleado_dni"],
                data["tipo"],
                data.get("mensaje"),
            ),
        )
        db.commit()
    finally:
        cur.close(); db.close()


def get_notificaciones_no_leidas(empleado_id: int) -> list[dict]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT tn.*, t.titulo AS trivia_titulo, t.fecha_fin
            FROM trivia_notificaciones tn
            JOIN trivias t ON t.id = tn.trivia_id
            WHERE tn.empleado_id = %s AND tn.leida = 0
            ORDER BY tn.enviada_en DESC
            """,
            (int(empleado_id),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def marcar_notificacion_leida(notificacion_id: int, empleado_id: int):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            """
            UPDATE trivia_notificaciones
            SET leida = 1
            WHERE id = %s AND empleado_id = %s
            """,
            (int(notificacion_id), int(empleado_id)),
        )
        db.commit()
    finally:
        cur.close(); db.close()


def marcar_todas_notificaciones_leidas(empleado_id: int):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "UPDATE trivia_notificaciones SET leida = 1 WHERE empleado_id = %s",
            (int(empleado_id),),
        )
        db.commit()
    finally:
        cur.close(); db.close()


# ---------------------------------------------------------------------------
# RANKING ANUAL
# ---------------------------------------------------------------------------

def recalcular_ranking_anual(anio: int):
    """
    Recalcula ranking anual desde trivia_resultados para el año dado.
    Usa REPLACE INTO para hacer upsert completo.
    """
    db = get_db()
    cur = db.cursor()
    try:
        # Borrar posiciones viejas del año para recalcular limpio
        cur.execute(
            "DELETE FROM trivia_ranking_anual WHERE anio = %s", (int(anio),)
        )

        cur.execute(
            """
            INSERT INTO trivia_ranking_anual
                (anio, empleado_id, empleado_dni, empleado_nombre,
                 puntos_anuales, trivias_participadas, trivias_ganadas,
                 correctas_totales, incorrectas_totales, tiempo_total_anual)
            SELECT
                %s                                       AS anio,
                tr.empleado_id,
                tr.empleado_dni,
                CONCAT(e.apellido, ' ', e.nombre)        AS empleado_nombre,
                SUM(tr.puntos_total)                     AS puntos_anuales,
                COUNT(tr.id)                             AS trivias_participadas,
                SUM(tr.es_ganador)                       AS trivias_ganadas,
                SUM(tr.correctas)                        AS correctas_totales,
                SUM(tr.incorrectas)                      AS incorrectas_totales,
                SUM(COALESCE(tr.tiempo_total_segundos,0)) AS tiempo_total_anual
            FROM trivia_resultados tr
            JOIN trivias t   ON t.id = tr.trivia_id
            JOIN empleados e ON e.id = tr.empleado_id
            WHERE t.anio = %s AND tr.estado_resultado = 'completado'
            GROUP BY tr.empleado_id, tr.empleado_dni
            """,
            (int(anio), int(anio)),
        )

        # Asignar posiciones según orden del ranking anual
        cur.execute(
            """
            SELECT id FROM trivia_ranking_anual
            WHERE anio = %s
            ORDER BY
                puntos_anuales      DESC,
                trivias_ganadas     DESC,
                correctas_totales   DESC,
                tiempo_total_anual  ASC,
                trivias_participadas DESC
            """,
            (int(anio),),
        )
        ids = [row[0] for row in cur.fetchall()]
        for pos, ra_id in enumerate(ids, start=1):
            cur.execute(
                "UPDATE trivia_ranking_anual SET posicion=%s, es_ganador_anual=%s WHERE id=%s",
                (pos, 1 if pos == 1 else 0, ra_id),
            )

        db.commit()
    finally:
        cur.close(); db.close()


def get_ranking_anual(anio: int) -> list[dict]:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT * FROM trivia_ranking_anual
            WHERE anio = %s
            ORDER BY posicion ASC
            """,
            (int(anio),),
        )
        return _all(cur)
    finally:
        cur.close(); db.close()


def get_ganador_anual(anio: int) -> dict | None:
    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT * FROM trivia_ranking_anual
            WHERE anio = %s AND es_ganador_anual = 1
            LIMIT 1
            """,
            (int(anio),),
        )
        return _one(cur)
    finally:
        cur.close(); db.close()
