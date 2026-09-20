"""Read the operational SKAP workbook without executing formulas or macros."""
from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_BYTES = 12 * 1024 * 1024


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", "".join(c for c in text if not unicodedata.combining(c)).upper()).split())


def name_key(value):
    return tuple(sorted(normalize(value).split()))


def _column_number(column):
    value = 0
    for letter in column:
        value = value * 26 + ord(letter) - ord('A') + 1
    return value


def _number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _read_sheets(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("El Excel supera los 12 MB permitidos.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(f.file_size for f in archive.infolist()) > 80 * 1024 * 1024:
                raise ValueError("El contenido descomprimido del Excel es demasiado grande.")
            def xml(path):
                data = archive.read(path)
                if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                    raise ValueError("El Excel contiene XML no permitido.")
                return ET.fromstring(data)
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = ["".join(t.text or "" for t in x.findall(".//s:t", NS)) for x in xml("xl/sharedStrings.xml")]
            rels = {r.get("Id"): r.get("Target") for r in xml("xl/_rels/workbook.xml.rels") if r.get("TargetMode") != "External"}
            result = []
            for sheet in xml("xl/workbook.xml").find("s:sheets", NS):
                target = rels.get(sheet.get(RID), "")
                path = target.lstrip("/") if target.startswith("/") else "xl/" + target
                if ".." in PurePosixPath(path).parts or not path.startswith("xl/"):
                    raise ValueError("Referencia de hoja inválida.")
                root = xml(path)
                cells, formulas = {}, {}
                for cell in root.findall("s:sheetData/s:row/s:c", NS):
                    address = cell.get("r")
                    value = cell.find("s:v", NS)
                    value = value.text if value is not None else "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                    if cell.get("t") == "s" and value:
                        value = strings[int(value)]
                    if value is not None and str(value).strip():
                        cells[address] = str(value).strip()
                    formula = cell.find("s:f", NS)
                    if formula is not None:
                        formulas[address] = formula.text or "(fórmula compartida)"
                result.append((sheet.get("name"), cells, formulas))
            return result
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError) as exc:
        raise ValueError("No se pudo leer el archivo .xlsx.") from exc


def summarize(responses):
    def metric(items):
        numeric = [r for r in items if r["estado"] == "evaluado"]
        missing = sum(r["estado"] == "sin_evaluar" for r in items)
        expected = sum(r["estandar"] for r in numeric)
        obtained = sum(r["puntaje"] for r in numeric)
        credited = sum(min(r["puntaje"], r["estandar"]) for r in numeric)
        partial = round(100 * credited / expected, 2) if expected else None
        return {"total": len(items), "evaluadas": len(numeric), "no_aplica": sum(r["estado"] == "no_aplica" for r in items),
                "faltantes": missing, "obtenido": obtained, "esperado": expected,
                "acreditado": credited, "expertas": sum(r["puntaje"] == 4 for r in numeric),
                "cumplimiento_pct": partial if not missing else None, "parcial_pct": partial,
                "brechas": sum(r["puntaje"] < r["estandar"] for r in numeric)}
    result = metric(responses)
    result["criticas"] = metric([r for r in responses if r["criticidad"] == "A"])
    result["criticidad_sin_definir"] = sum(not r["criticidad"] for r in responses)
    if result["criticidad_sin_definir"]:
        result["criticas"]["cumplimiento_pct"] = None
    result["bloques"] = {b: metric([r for r in responses if r["bloque"] == b]) for b in dict.fromkeys(r["bloque"] for r in responses)}
    return result


def parse_workbook(raw: bytes, filename: str = "matriz.xlsx") -> dict:
    evaluations, training, warnings = [], [], []
    for name, cells, formulas in _read_sheets(raw):
        if normalize(name).startswith("PLAN DE FORMACION"):
            block = "General"
            for row in range(3, 2000):
                block = cells.get(f"B{row}", block)
                if cells.get(f"D{row}"):
                    training.append({"hoja": name, "fila": row, "bloque": block, "criticidad": cells.get(f"C{row}"),
                                     "competencia": cells[f"D{row}"], "alcance": cells.get(f"E{row}"), "material": cells.get(f"F{row}")})
            continue
        year_cells = [(a, re.search(r"EVALUACION\s+(\d{4})", normalize(v))) for a, v in cells.items()]
        years = [(a, int(m.group(1))) for a, m in year_cells if m]
        if not years:
            continue
        year = years[0][1]
        if not 1900 <= year <= 2100:
            raise ValueError(f"Año inválido en {name}.")
        header_rows = [int(a[1:]) for a, v in cells.items() if re.fullmatch(r"F\d+", a) and normalize(v).startswith("ESTANDAR")]
        if len(header_rows) != 1:
            raise ValueError(f"No se reconoce el encabezado de {name}.")
        header = header_rows[0]
        role = cells.get(f"D{header}") or name
        people = [(re.sub(r"\d", "", a), v) for a, v in cells.items()
                  if re.fullmatch(r"[A-Z]+" + str(header), a) and _column_number(re.sub(r"\d", "", a)) >= 8]
        block, competencies = "General", []
        last_standard_row = max([int(a[1:]) for a in cells if re.fullmatch(r'F\d+',a)], default=header)
        for row in range(header + 1, 2000):
            description = cells.get(f"D{row}")
            standard = _number(cells.get(f"F{row}"))
            if description and standard is not None:
                if standard != int(standard) or not 0 <= standard <= 4:
                    raise ValueError(f"Estándar fuera de escala en {name}!F{row}.")
                priority = normalize(cells.get(f"C{row}"))
                if priority not in {"A", "B", "C"}:
                    priority = None
                    warnings.append(f"{name}!C{row}: criticidad sin definir.")
                competencies.append({"fila": row, "competencia": description, "bloque": block,
                                     "criticidad": priority, "estandar": int(standard)})
            elif description and row > header + 3 and row < last_standard_row:
                block = description
        if not competencies or not people:
            raise ValueError(f"No se encontraron personas o competencias en {name}.")
        for col, person in people:
            responses = []
            for competency in competencies:
                address = f"{col}{competency['fila']}"
                raw_score = cells.get(address)
                if address in formulas:
                    raise ValueError(f"{name}!{address}: una calificación debe ser un dato, no una fórmula.")
                score = _number(raw_score)
                if raw_score is None:
                    state, score = "sin_evaluar", None
                elif normalize(raw_score) in {"NA", "N A"}:
                    state, score = "no_aplica", None
                elif score is not None and score == int(score) and 0 <= score <= 4:
                    state, score = "evaluado", int(score)
                else:
                    raise ValueError(f"{name}!{address}: puntaje inválido ({raw_score}).")
                responses.append({**competency, "celda": address, "valor_original": raw_score, "estado": state, "puntaje": score})
            original = {}
            for address, label in cells.items():
                if re.fullmatch(r"F\d+", address) and normalize(label) in {"GENERAL", "CRITICAS"}:
                    source = f"{col}{address[1:]}"
                    original[normalize(label).lower()] = {"valor": _number(cells.get(source)), "celda": source, "formula": formulas.get(source)}
            evaluations.append({"clave": f"{name}:{col}", "hoja": name, "nombre_original": person,
                                "sucursal": "Dolores" if normalize(name).endswith(" DOL") else "Casa Central",
                                "rol": role, "anio": year, "fecha_evaluacion": None, "evaluador": None,
                                "respuestas": responses, "resumen": summarize(responses), "resultados_originales": original})
    if not evaluations:
        raise ValueError("El archivo no contiene matrices SKAP reconocibles.")
    return {"archivo": PurePosixPath(filename.replace("\\", "/")).name, "sha256": hashlib.sha256(raw).hexdigest(),
            "evaluaciones": evaluations, "formacion": training, "advertencias": warnings,
            "version": 1, "escala": "operativa_0_4"}


def match_employees(payload, employees, branches, overrides=None, aliases=None):
    """Exact normalized full-name matches only; ambiguity must be resolved explicitly."""
    overrides = overrides or {}
    aliases = aliases or {}
    employees_by_id = {int(e["id"]): e for e in employees}
    for ev in payload["evaluaciones"]:
        branch_candidates = [s for s in branches if normalize(s["nombre"]) == normalize(ev["sucursal"])]
        matches = [e for e in employees if name_key(f"{e['apellido']} {e['nombre']}") == name_key(ev["nombre_original"])]
        ev["candidatos"] = [{"id": e["id"], "legajo": e["legajo"], "nombre": f"{e['apellido']} {e['nombre']}"} for e in matches]
        selected = None
        if ev["clave"] in overrides and str(overrides[ev["clave"]]).strip():
            selected = employees_by_id.get(int(overrides[ev["clave"]]))
            if not selected:
                raise ValueError("El legajo seleccionado no pertenece al alcance autorizado.")
            ev['alias_confirmado'] = name_key(ev['nombre_original']) != name_key(f"{selected['apellido']} {selected['nombre']}")
        else:
            local = [e for e in matches if any(e["sucursal_id"] == s["id"] and e["empresa_id"] == s["empresa_id"] for s in branch_candidates)]
            if len(local) == 1:
                selected = local[0]
            elif len(matches) == 1:
                selected = matches[0]
            elif not matches:
                selected = employees_by_id.get(aliases.get(' '.join(name_key(ev['nombre_original']))))
        ev["empleado_id"] = selected["id"] if selected else None
        ev["legajo"] = selected["legajo"] if selected else None
        ev["empresa_id"] = selected["empresa_id"] if selected else None
        valid_branches = [s for s in branch_candidates if selected and s["empresa_id"] == selected["empresa_id"]]
        ev["sucursal_id"] = valid_branches[0]["id"] if len(valid_branches) == 1 else None
        ev["sucursal_actual_distinta"] = bool(selected and ev["sucursal_id"] and selected["sucursal_id"] != ev["sucursal_id"])
        ev["vinculo"] = "resuelto" if selected and ev["sucursal_id"] else "pendiente"
    payload["pendientes"] = sum(e["vinculo"] != "resuelto" for e in payload["evaluaciones"])
    return payload
