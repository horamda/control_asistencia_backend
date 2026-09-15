from datetime import datetime, timedelta, timezone
import hashlib

from repositories.presencia_repository import get_daily_presence


ARGENTINA = timezone(timedelta(hours=-3))


def summarize_presence(empleados, marcas):
    """Cada empleado cuenta una vez; la última marca determina su estado."""
    latest = {}
    latest_time = {}
    latest_location = {}
    ingresaron = set()
    for marca in marcas:  # Orden cronológico garantizado por el repositorio.
        empleado_id = marca["empleado_id"]
        latest[empleado_id] = marca["accion"]
        latest_time[empleado_id] = str(marca.get("hora") or "")
        latest_location[empleado_id] = (
            str(marca.get("metodo") or "").lower() == "qr" and marca.get("gps_ok") == 1
        )
        if marca["accion"] == "ingreso":
            ingresaron.add(empleado_id)
    empresas = {}
    sucursales = {}
    for empleado in empleados:
        group = empresas.setdefault(empleado["empresa_id"], {
            "id": empleado["empresa_id"], "nombre": empleado["empresa"],
            "empleados": 0, "presentes": 0, "vinieron": 0,
            "retirados": 0, "sin_ingreso": 0,
        })
        empleado_id = empleado["id"]
        vino = empleado_id in ingresaron
        presente = latest.get(empleado_id) == "ingreso"
        branch_key = (empleado["empresa_id"], empleado.get("sucursal_id"))
        branch = sucursales.setdefault(branch_key, {
            "id": empleado.get("sucursal_id"), "empresa": empleado["empresa"],
            "nombre": empleado.get("sucursal") or "Sin sucursal",
            "empleados": 0, "presentes": 0, "vinieron": 0, "retirados": 0, "sin_ingreso": 0,
            "sectores": {}, "modalidades": {}, "personas": [], "personal": [], "sin_ingreso_personas": [],
        })
        sector = branch["sectores"].setdefault(empleado.get("sector_id"), {
            "nombre": empleado.get("sector") or "Sin sector",
            "empleados": 0, "presentes": 0, "vinieron": 0, "retirados": 0, "sin_ingreso": 0,
        })
        modalidad = str(empleado.get("modalidad") or "").strip().lower()
        labels = {"presencial": "Presencial", "remoto": "Remoto", "hibrido": "H\u00edbrido"}
        if modalidad not in labels:
            modalidad = "sin_definir"
        person = {
                "clave": hashlib.sha256(f"empleado:{empleado['empresa_id']}:{empleado_id}".encode()).hexdigest()[:24],
                "nombre": " ".join(str(empleado.get(key) or "").strip()
                                   for key in ("apellido", "nombre")).strip() or "Nombre sin registrar",
                "sector": empleado.get("sector") or "Sin sector",
                "modalidad": labels.get(modalidad, "Sin definir"),
                "modalidad_codigo": modalidad,
                "ultimo_ingreso": latest_time.get(empleado_id, ""),
                "ingreso_validado": latest_location.get(empleado_id, False),
                "estado": "sin_salida" if presente else "con_salida" if vino else "solo_salida" if latest.get(empleado_id) == "egreso" else "sin_fichadas",
            }
        branch["personal"].append(person)
        if presente:
            branch["personas"].append(person)
        if not vino:
            branch["sin_ingreso_personas"].append(person)
        modality_groups = []
        for parent in (branch, sector):
            item = parent.setdefault("modalidades", {}).setdefault(modalidad, {
                "codigo": modalidad, "nombre": labels.get(modalidad, "Sin definir"),
                "empleados": 0, "presentes": 0, "vinieron": 0, "retirados": 0, "sin_ingreso": 0,
            })
            modality_groups.append(item)
        for item in (branch, sector, *modality_groups):
            item["empleados"] += 1
            item["presentes"] += int(presente)
            item["vinieron"] += int(vino)
            item["retirados"] += int(vino and not presente)
            item["sin_ingreso"] += int(not vino)
        group["empleados"] += 1
        group["presentes"] += int(presente)
        group["vinieron"] += int(vino)
        group["retirados"] += int(vino and not presente)
        group["sin_ingreso"] += int(not vino)
    rows = sorted(empresas.values(), key=lambda row: row["nombre"].casefold())
    totals = {key: sum(row[key] for row in rows) for key in (
        "empleados", "presentes", "vinieron", "retirados", "sin_ingreso"
    )}
    branch_order = {"casa central": 0, "dolores": 1}
    branches = sorted(sucursales.values(), key=lambda b: (
        branch_order.get(b["nombre"].strip().casefold(), 2), b["nombre"].casefold(), b["empresa"].casefold()
    ))
    for branch in branches:
        for field in ("personas", "personal", "sin_ingreso_personas"):
            branch[field].sort(key=lambda p: (p["sector"].casefold(), p["nombre"].casefold()))
        branch["sectores"] = sorted(branch["sectores"].values(), key=lambda s: s["nombre"].casefold())
        for parent in (branch, *branch["sectores"]):
            parent["modalidades"] = sorted(parent["modalidades"].values(), key=lambda m: (
                ["presencial", "remoto", "hibrido", "sin_definir"].index(m["codigo"])
            ))
    return {"totales": totals, "empresas": rows, "sucursales": branches}


def build_presence(empresa_id=None):
    now = datetime.now(ARGENTINA)
    empleados, marcas = get_daily_presence(
        now.date().isoformat(), now.strftime("%H:%M:%S"), empresa_id
    )
    return {
        **summarize_presence(empleados, marcas),
        "fecha": now.date().isoformat(), "actualizado": now.isoformat(),
        "intervalo_segundos": 30,
    }
