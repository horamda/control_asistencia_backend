from collections import Counter

from extensions import get_db


def _full_name(row: dict, *, prefix: str = "") -> str:
    apellido = str(row.get(f"{prefix}apellido") or "").strip()
    nombre = str(row.get(f"{prefix}nombre") or "").strip()
    return " ".join(part for part in [apellido, nombre] if part)


def _sector_filters(empresa_id: int | None, activo: int | None):
    where = []
    params = []
    if empresa_id:
        where.append("s.empresa_id = %s")
        params.append(int(empresa_id))
    if activo in (0, 1):
        where.append("s.activo = %s")
        params.append(int(activo))
    return ("WHERE " + " AND ".join(where)) if where else "", params


def _employee_filters(empresa_id: int | None):
    where = ["emp.activo = 1"]
    params = []
    if empresa_id:
        where.append("emp.empresa_id = %s")
        params.append(int(empresa_id))
    return "WHERE " + " AND ".join(where), params


def _can_attach_to_parent(node: dict, parent: dict | None, by_id: dict[int, dict]) -> bool:
    if not parent:
        return False
    if parent.get("empresa_id") != node.get("empresa_id"):
        return False

    seen = {node.get("id")}
    current = parent
    while current:
        current_id = current.get("id")
        if current_id in seen:
            return False
        seen.add(current_id)
        current = by_id.get(current.get("sector_padre_id"))
    return True


def _append_extra_puesto(employee: dict, assignment: dict):
    extra = {
        "sector_id": assignment.get("sector_id"),
        "puesto_id": assignment.get("puesto_id"),
        "puesto_nombre": assignment.get("puesto_nombre"),
    }
    employee.setdefault("puestos_adicionales", []).append(extra)


def _assign_totals(node: dict) -> int:
    total = len(node["empleados"])
    for child in node["children"]:
        total += _assign_totals(child)
    node["dotacion_directa"] = len(node["empleados"])
    node["dotacion_total"] = total
    return total


def _build_employee_tree(employees: list) -> list:
    sector_ids = {e["id"] for e in employees}
    by_id = {e["id"]: {**e, "subordinados": []} for e in employees}
    roots = []
    for emp in by_id.values():
        parent_id = emp.get("reporta_a_empleado_id")
        if parent_id and parent_id in sector_ids and parent_id in by_id:
            by_id[parent_id]["subordinados"].append(emp)
        else:
            roots.append(emp)
    return roots


def _compute_puestos_resumen(employees: list) -> list:
    counter: Counter = Counter()
    for emp in employees:
        nombre = emp.get("puesto_nombre")
        if nombre:
            counter[nombre] += 1
    return [{"nombre": k, "count": v} for k, v in counter.most_common()]


def get_organigrama(empresa_id: int | None = None, activo: int | None = 1):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        sector_where, sector_params = _sector_filters(empresa_id, activo)
        cursor.execute(f"""
            SELECT
                s.id,
                s.empresa_id,
                emp.razon_social AS empresa_nombre,
                s.nombre,
                s.activo,
                s.sector_padre_id,
                s.responsable_empleado_id,
                sp.nombre AS sector_padre_nombre,
                resp.nombre AS responsable_nombre,
                resp.apellido AS responsable_apellido,
                resp.email AS responsable_email,
                resp.foto AS responsable_foto,
                puesto_resp.nombre AS responsable_puesto_nombre
            FROM sectores s
            JOIN empresas emp ON emp.id = s.empresa_id
            LEFT JOIN sectores sp ON sp.id = s.sector_padre_id
            LEFT JOIN empleados resp ON resp.id = s.responsable_empleado_id
            LEFT JOIN puestos puesto_resp ON puesto_resp.id = resp.puesto_id
            {sector_where}
            ORDER BY emp.razon_social, s.nombre
        """, sector_params)
        sector_rows = cursor.fetchall()

        employee_where, employee_params = _employee_filters(empresa_id)
        cursor.execute(f"""
            SELECT
                emp.id,
                emp.empresa_id,
                empresa.razon_social AS empresa_nombre,
                emp.sector_id,
                emp.nombre,
                emp.apellido,
                emp.email,
                emp.foto,
                emp.reporta_a_empleado_id,
                puesto.nombre AS puesto_nombre
            FROM empleados emp
            JOIN empresas empresa ON empresa.id = emp.empresa_id
            LEFT JOIN puestos puesto ON puesto.id = emp.puesto_id
            {employee_where}
            ORDER BY empresa.razon_social, emp.apellido, emp.nombre
        """, employee_params)
        employee_rows = cursor.fetchall()

        cursor.execute(f"""
            SELECT
                ep.empleado_id,
                ep.empresa_id,
                ep.sector_id,
                ep.puesto_id,
                puesto.nombre AS puesto_nombre
            FROM empleado_puestos ep
            JOIN empleados emp ON emp.id = ep.empleado_id
            JOIN puestos puesto ON puesto.id = ep.puesto_id
            {employee_where}
              AND ep.activo = 1
            ORDER BY ep.empleado_id, puesto.nombre
        """, employee_params)
        extra_assignment_rows = cursor.fetchall()
    finally:
        cursor.close()
        db.close()

    by_id: dict[int, dict] = {}
    companies: dict[int, dict] = {}
    employees_by_id: dict[int, dict] = {}

    for row in sector_rows:
        node = dict(row)
        node["responsable_nombre_completo"] = _full_name(row, prefix="responsable_")
        node["children"] = []
        node["empleados"] = []
        node["dotacion_directa"] = 0
        node["dotacion_total"] = 0
        by_id[int(node["id"])] = node
        companies.setdefault(
            int(node["empresa_id"]),
            {
                "empresa_id": int(node["empresa_id"]),
                "empresa_nombre": node.get("empresa_nombre"),
                "roots": [],
                "empleados_sin_sector": [],
                "total_sectores": 0,
                "total_empleados": 0,
                "responsables_asignados": 0,
            },
        )

    for employee in employee_rows:
        employee = dict(employee)
        employee["nombre_completo"] = _full_name(employee)
        employee["puestos_adicionales"] = []
        employee["asignacion_adicional"] = False
        employees_by_id[int(employee["id"])] = employee
        company = companies.setdefault(
            int(employee["empresa_id"]),
            {
                "empresa_id": int(employee["empresa_id"]),
                "empresa_nombre": employee.get("empresa_nombre"),
                "roots": [],
                "empleados_sin_sector": [],
                "total_sectores": 0,
                "total_empleados": 0,
                "responsables_asignados": 0,
            },
        )
        sector_id = employee.get("sector_id")
        sector = by_id.get(int(sector_id)) if sector_id else None
        if sector and int(sector["empresa_id"]) == int(employee["empresa_id"]):
            sector["empleados"].append(employee)
        else:
            company["empleados_sin_sector"].append(employee)

    for assignment in extra_assignment_rows:
        assignment = dict(assignment)
        base_employee = employees_by_id.get(int(assignment["empleado_id"]))
        if not base_employee:
            continue

        _append_extra_puesto(base_employee, assignment)
        if int(base_employee.get("sector_id") or 0) == int(assignment.get("sector_id") or 0):
            continue

        sector = by_id.get(int(assignment["sector_id"])) if assignment.get("sector_id") else None
        if not sector or int(sector["empresa_id"]) != int(assignment["empresa_id"]):
            continue

        employee_copy = dict(base_employee)
        employee_copy["puesto_nombre"] = assignment.get("puesto_nombre")
        employee_copy["puestos_adicionales"] = []
        employee_copy["asignacion_adicional"] = True
        sector["empleados"].append(employee_copy)

    for node in by_id.values():
        company = companies[int(node["empresa_id"])]
        parent = by_id.get(int(node["sector_padre_id"])) if node.get("sector_padre_id") else None
        if _can_attach_to_parent(node, parent, by_id):
            parent["children"].append(node)
        else:
            company["roots"].append(node)

    for company in companies.values():
        company["roots"].sort(key=lambda item: (str(item.get("nombre") or "").lower(), int(item["id"])))
        for node in by_id.values():
            node["children"].sort(key=lambda item: (str(item.get("nombre") or "").lower(), int(item["id"])))
        company_nodes = [
            node for node in by_id.values()
            if int(node["empresa_id"]) == int(company["empresa_id"])
        ]
        company["total_sectores"] = len(company_nodes)
        company["responsables_asignados"] = sum(1 for node in company_nodes if node.get("responsable_empleado_id"))
        company["total_empleados"] = len(company["empleados_sin_sector"])
        for root in company["roots"]:
            company["total_empleados"] += _assign_totals(root)

    for node in by_id.values():
        node["empleados_tree"] = _build_employee_tree(node["empleados"])
        node["puestos_resumen"] = _compute_puestos_resumen(node["empleados"])

    return sorted(
        companies.values(),
        key=lambda item: str(item.get("empresa_nombre") or "").lower(),
    )
