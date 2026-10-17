"""Comunicados programados: una vez, diario, semanal o mensual, a una hora, hasta una fecha o cantidad de envios.

Los destinatarios se guardan como reglas (las mismas del formulario) y se resuelven en cada envio: quien
ingresa despues recibe los siguientes. Cada envio crea un comunicado comun (con su lectura y acuses) que
recuerda su programacion (comunicados.programado_id). El scheduler revisa cada minuto los vencidos.

"Solo dias habiles" saltea domingos y los dias no laborables del calendario de la empresa; en la frecuencia
mensual, si el dia cae en uno no habil, el envio pasa al siguiente dia habil.
"""
import calendar
import datetime as dt
import json
import logging

from repositories import carga_repository as db
from repositories.asistencia_dia_no_laborable_repository import get_dates as dias_no_laborables
from services import comunicado_service as com
from services.carga_service import CargaError as Error, now_local

logger = logging.getLogger(__name__)
FRECUENCIAS = {"una_vez": "Una vez", "diaria": "Todos los días", "semanal": "Semanal", "mensual": "Mensual"}
DIAS = {1: "lunes", 2: "martes", 3: "miércoles", 4: "jueves", 5: "viernes", 6: "sábado", 7: "domingo"}
HORIZONTE_DIAS = 800  # mas alla, la programacion se da por terminada


def _fecha(valor, nombre):
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    try:
        return dt.date.fromisoformat(str(valor or "").strip()[:10])
    except ValueError:
        raise Error(f"{nombre}: fecha inválida.") from None


def _hora(valor):
    if isinstance(valor, dt.timedelta):
        segundos = int(valor.total_seconds()) % 86400
        return dt.time(segundos // 3600, segundos % 3600 // 60)
    if isinstance(valor, dt.time):
        return valor.replace(second=0, microsecond=0)
    try:
        horas, minutos = str(valor or "").strip()[:5].split(":")
        return dt.time(int(horas), int(minutos))
    except ValueError:
        raise Error("Indicá la hora de envío (HH:MM).") from None


class Habiles:
    """Dias habiles de una empresa: no domingo ni no laborable del calendario (consultado por mes)."""

    def __init__(self, empresa_id, consulta=dias_no_laborables):
        self.empresa_id, self.consulta, self.meses = empresa_id, consulta, {}

    def __call__(self, fecha):
        if fecha.isoweekday() == 7:
            return False
        clave = (fecha.year, fecha.month)
        if clave not in self.meses:
            try:
                self.meses[clave] = set(self.consulta(year=fecha.year, month=fecha.month, empresa_id=self.empresa_id))
            except Exception:
                logger.warning("comunicado_programado_calendario_error", exc_info=True)
                self.meses[clave] = set()
        return fecha.isoformat() not in self.meses[clave]


def _dia_del_mes(anio, mes, dia):
    return dt.date(anio, mes, min(int(dia), calendar.monthrange(anio, mes)[1]))


def proxima(prog, despues, habil=None):
    """Proximo envio estrictamente posterior a `despues`, o None si la programacion termino."""
    habil = habil or (lambda fecha: True)
    hora = _hora(prog["hora"])
    inicio = _fecha(prog["fecha_inicio"], "Inicio")
    fin = _fecha(prog["fecha_fin"], "Fin") if prog.get("fecha_fin") else None
    if prog.get("max_envios") and int(prog.get("envios") or 0) >= int(prog["max_envios"]):
        return None
    frecuencia = prog["frecuencia"]
    solo_habiles = bool(prog.get("solo_habiles"))

    def valida(momento):
        return momento > despues and (fin is None or momento.date() <= fin)

    if frecuencia == "una_vez":
        momento = dt.datetime.combine(inicio, hora)
        return momento if int(prog.get("envios") or 0) == 0 and valida(momento) else None
    if frecuencia == "mensual":
        fecha = max(inicio, despues.date()).replace(day=1)
        for _ in range(HORIZONTE_DIAS // 28):
            dia = _dia_del_mes(fecha.year, fecha.month, prog["dia_mes"])
            if solo_habiles:
                while not habil(dia):
                    dia += dt.timedelta(days=1)
            momento = dt.datetime.combine(dia, hora)
            if dia >= inicio and valida(momento):
                return momento
            if fin and dia > fin:
                return None
            fecha = (fecha.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return None
    dias_semana = {int(d) for d in str(prog.get("dias_semana") or "").split(",") if d.strip().isdigit()}
    fecha = max(inicio, despues.date())
    for _ in range(HORIZONTE_DIAS):
        if fin and fecha > fin:
            return None
        if (frecuencia == "diaria" or fecha.isoweekday() in dias_semana) and (not solo_habiles or habil(fecha)):
            momento = dt.datetime.combine(fecha, hora)
            if valida(momento):
                return momento
        fecha += dt.timedelta(days=1)
    return None


def descripcion(prog):
    """Texto legible: 'Lunes y jueves a las 08:00 (solo hábiles)'."""
    hora = _hora(prog["hora"]).strftime("%H:%M")
    frecuencia = prog["frecuencia"]
    if frecuencia == "una_vez":
        texto = f"El {_fecha(prog['fecha_inicio'], 'Inicio'):%d/%m/%Y} a las {hora}"
    elif frecuencia == "diaria":
        texto = f"Todos los días a las {hora}"
    elif frecuencia == "semanal":
        dias = [DIAS[int(d)] for d in str(prog.get("dias_semana") or "").split(",") if d.strip().isdigit()]
        nombres = ", ".join(dias[:-1]) + (" y " if len(dias) > 1 else "") + dias[-1] if dias else "—"
        texto = f"{nombres.capitalize()} a las {hora}"
    else:
        texto = f"El día {prog['dia_mes']} de cada mes a las {hora}"
    if prog.get("solo_habiles") and frecuencia != "una_vez":
        texto += " (solo hábiles)"
    if prog.get("fecha_fin"):
        texto += f", hasta el {_fecha(prog['fecha_fin'], 'Fin'):%d/%m/%Y}"
    if prog.get("max_envios"):
        texto += f", {prog['max_envios']} envíos"
    return texto


def _programacion(form, ahora):
    """Campos de la programacion a partir del formulario, validados."""
    frecuencia = form.get("frecuencia")
    if frecuencia not in FRECUENCIAS:
        raise Error("Elegí la frecuencia del envío.")
    prog = dict(frecuencia=frecuencia, hora=_hora(form.get("hora")),
                fecha_inicio=_fecha(form.get("fecha_inicio") or ahora.date().isoformat(), "Desde"),
                fecha_fin=None, dias_semana=None, dia_mes=None, max_envios=None, envios=0,
                solo_habiles=1 if form.get("solo_habiles") and frecuencia != "una_vez" else 0)
    if frecuencia == "semanal":
        dias = sorted({int(d) for d in form.getlist("dias_semana") if str(d).isdigit() and 1 <= int(d) <= 7})
        if not dias:
            raise Error("Elegí al menos un día de la semana.")
        prog["dias_semana"] = ",".join(map(str, dias))
    if frecuencia == "mensual":
        try:
            prog["dia_mes"] = int(form.get("dia_mes") or 0)
        except ValueError:
            prog["dia_mes"] = 0
        if not 1 <= prog["dia_mes"] <= 31:
            raise Error("El día del mes va de 1 a 31.")
    if frecuencia != "una_vez":
        termina = form.get("termina") or "nunca"
        if termina == "fecha":
            prog["fecha_fin"] = _fecha(form.get("fecha_fin"), "Hasta")
            if prog["fecha_fin"] < prog["fecha_inicio"]:
                raise Error("La fecha de fin no puede ser anterior al inicio.")
        elif termina == "cantidad":
            try:
                prog["max_envios"] = int(form.get("max_envios") or 0)
            except ValueError:
                prog["max_envios"] = 0
            if not 1 <= prog["max_envios"] <= 1000:
                raise Error("La cantidad de envíos va de 1 a 1000.")
    return prog


def programar(who, data, form, imagen=None, base_url=None):
    """Valida mensaje, destinatarios y programacion; guarda y calcula el primer envio."""
    titulo = com._texto(data, "titulo", com.TITULO_MAX, "el título")
    mensaje = com._texto(data, "mensaje", com.MENSAJE_MAX, "el mensaje")
    ahora = now_local().replace(microsecond=0)
    prog = _programacion(form, ahora)
    primero = proxima(prog, ahora, Habiles(who["empresa_id"]))
    if not primero:
        raise Error("Con esas fechas no queda ningún envío por hacer. Revisá el día y la hora.")
    with db.transaction(read_only=True) as c:
        reglas = com._reglas(c, who["empresa_id"], data)
        sucursales = com._sucursales(c, who["empresa_id"], data.get("sucursales"))
        if not com.destinatarios(c, who["empresa_id"], reglas, sucursales):
            raise Error("Con esa selección hoy no hay empleados activos para recibirlo.")
        alcance = com._alcance(c, who["empresa_id"], reglas, sucursales)
    contenido, contenido_push = com._imagen_subida(imagen)
    destinatarios = dict(reglas=list(data.get("reglas") or []), empleados=list(data.get("empleados") or []),
                         sucursales=list(data.get("sucursales") or []), base_url=base_url)
    with db.transaction() as c:
        pid = db.insert(c, "comunicados_programados", dict(
            empresa_id=who["empresa_id"], titulo=titulo, mensaje=mensaje, imagen=contenido, imagen_push=contenido_push,
            destinatarios=json.dumps(destinatarios), alcance=alcance, frecuencia=prog["frecuencia"], hora=prog["hora"],
            fecha_inicio=prog["fecha_inicio"], fecha_fin=prog["fecha_fin"], dias_semana=prog["dias_semana"],
            dia_mes=prog["dia_mes"], solo_habiles=prog["solo_habiles"], max_envios=prog["max_envios"], envios=0,
            proximo_envio=primero, estado="activo", creado_por=who.get("user_id"), creado_at=ahora))
    return pid, primero


def ejecutar_vencidos(ahora=None, limite=20):
    """Scheduler (cada minuto): envia los programados cuya hora llego y calcula el siguiente envio."""
    ahora = ahora or now_local()
    with db.transaction(read_only=True) as c:
        vencidos = db.all_rows(c, """SELECT id FROM comunicados_programados
                                     WHERE estado='activo' AND proximo_envio <= %s ORDER BY proximo_envio LIMIT %s""",
                               (ahora, int(limite)))
    enviados = 0
    for fila in vencidos:
        try:
            enviados += _ejecutar(fila["id"], ahora)
        except Exception:
            logger.warning("comunicado_programado_error", exc_info=True, extra={"extra": {"programado_id": fila["id"]}})
    return enviados


def _ejecutar(pid, ahora):
    with db.transaction() as c:  # reserva: otro proceso no lo manda dos veces
        prog = db.one(c, "SELECT * FROM comunicados_programados WHERE id=%s FOR UPDATE", (pid,))
        if not prog or prog["estado"] != "activo" or prog["proximo_envio"] is None or prog["proximo_envio"] > ahora:
            return 0
        siguiente_base = dict(prog, envios=int(prog["envios"]) + 1)
        siguiente = proxima(siguiente_base, max(ahora, prog["proximo_envio"]), Habiles(prog["empresa_id"]))
        c.execute("""UPDATE comunicados_programados SET envios=envios+1, ultimo_envio=%s, proximo_envio=%s, estado=%s
                     WHERE id=%s""", (ahora.replace(microsecond=0), siguiente, "activo" if siguiente else "finalizado", pid))
    destinatarios = json.loads(prog["destinatarios"] or "{}")
    data = dict(titulo=prog["titulo"], mensaje=prog["mensaje"], reglas=destinatarios.get("reglas") or [],
                empleados=destinatarios.get("empleados") or [], sucursales=destinatarios.get("sucursales") or [])
    try:
        com.enviar_contenido({"empresa_id": prog["empresa_id"], "user_id": prog["creado_por"]}, data,
                             prog["imagen"], prog["imagen_push"], programado_id=pid,
                             base_url=destinatarios.get("base_url"))
    except Error as error:  # p. ej. hoy nadie cumple el filtro: se saltea este envio y sigue la programacion
        logger.info("comunicado_programado_sin_envio", extra={"extra": {"programado_id": pid, "motivo": str(error)}})
        return 0
    return 1


# --- Panel -------------------------------------------------------------------------------------------

def listado(who):
    with db.transaction(read_only=True) as c:
        filas = db.all_rows(c, """SELECT id, titulo, mensaje, alcance, frecuencia, hora, fecha_inicio, fecha_fin,
                                         dias_semana, dia_mes, solo_habiles, max_envios, envios, proximo_envio,
                                         ultimo_envio, estado, creado_at, (imagen IS NOT NULL) AS tiene_imagen
                                  FROM comunicados_programados WHERE empresa_id=%s
                                  ORDER BY estado='finalizado', proximo_envio IS NULL, proximo_envio, id DESC""",
                            (who["empresa_id"],))
    for fila in filas:
        fila["descripcion"] = descripcion(fila)
    return dict(programados=filas)


def _obtener(c, who, pid):
    fila = db.one(c, "SELECT * FROM comunicados_programados WHERE id=%s AND empresa_id=%s FOR UPDATE",
                  (int(pid), who["empresa_id"]))
    if not fila:
        raise Error("Programación no encontrada.", 404)
    return fila


def pausar(who, pid):
    with db.transaction() as c:
        prog = _obtener(c, who, pid)
        if prog["estado"] != "activo":
            raise Error("Solo se pausa una programación activa.")
        c.execute("UPDATE comunicados_programados SET estado='pausado' WHERE id=%s", (prog["id"],))
    return prog


def reanudar(who, pid):
    """Sigue desde ahora: los envios que caian mientras estuvo pausada no se mandan."""
    ahora = now_local().replace(microsecond=0)
    with db.transaction() as c:
        prog = _obtener(c, who, pid)
        if prog["estado"] != "pausado":
            raise Error("Solo se reanuda una programación pausada.")
        siguiente = proxima(prog, ahora, Habiles(prog["empresa_id"]))
        c.execute("UPDATE comunicados_programados SET estado=%s, proximo_envio=%s WHERE id=%s",
                  ("activo" if siguiente else "finalizado", siguiente, prog["id"]))
    return prog, siguiente


def eliminar(who, pid):
    """Borra la programacion; los comunicados ya enviados quedan en Enviados."""
    with db.transaction() as c:
        prog = _obtener(c, who, pid)
        c.execute("UPDATE comunicados SET programado_id=NULL WHERE programado_id=%s", (prog["id"],))
        c.execute("DELETE FROM comunicados_programados WHERE id=%s", (prog["id"],))
    return prog
