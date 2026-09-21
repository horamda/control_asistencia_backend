from extensions import get_db


def get_legajo_filter_catalogs():
    """Fresh, minimal directory filters in a single database round trip."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT 'empresas' AS catalogo, id, razon_social AS nombre,
                   id AS empresa_id, razon_social AS empresa_nombre
            FROM empresas
            UNION ALL
            SELECT 'sucursales', s.id, s.nombre, s.empresa_id, e.razon_social
            FROM sucursales s JOIN empresas e ON e.id = s.empresa_id
            UNION ALL
            SELECT 'sectores', s.id, s.nombre, s.empresa_id, e.razon_social
            FROM sectores s JOIN empresas e ON e.id = s.empresa_id
            ORDER BY empresa_nombre, nombre, id
        """)
        catalogs = {'empresas': [], 'sucursales': [], 'sectores': []}
        for row in cursor.fetchall():
            key = row.pop('catalogo')
            if key == 'empresas':
                row['razon_social'] = row['nombre']
            catalogs[key].append(row)
        return catalogs
    finally:
        cursor.close()
        db.close()
