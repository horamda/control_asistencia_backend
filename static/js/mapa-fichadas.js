// Mapa de fichadas (panel, solo lectura). Los datos vienen en <script type="application/json" id="mf-datos">.
// Leaflet local (static/vendor/leaflet) y mosaicos de OpenStreetMap con su atribucion.
// Cada fichada es un pin: verde el ingreso, naranja el egreso; el centro blanco si quedo dentro del radio, rojo si
// quedo fuera y gris si no se valido; borde violeta si el telefono marco el GPS como simulado.
(function () {
  var ACCIONES = { ingreso: "Ingreso", egreso: "Egreso" };
  var COLOR_ACCION = { ingreso: "#16a34a", egreso: "#ea580c" };
  var COLOR_CENTRO = { dentro: "#ffffff", fuera: "#dc2626", sin_validar: "#9ca3af" };

  function texto(valor) {
    var div = document.createElement("div");
    div.textContent = valor == null ? "" : String(valor);
    return div.innerHTML;
  }

  function pin(p) {
    var relleno = COLOR_ACCION[p.accion] || "#6b7280";
    var centro = COLOR_CENTRO[p.estado] || COLOR_CENTRO.sin_validar;
    var borde = p.simulada === true ? "#7c3aed" : "#ffffff";
    var svg = "<svg viewBox=\"0 0 24 34\" width=\"24\" height=\"34\" aria-hidden=\"true\">" +
      "<path d=\"M12 1C6 1 1 5.9 1 12c0 8.2 11 21 11 21s11-12.8 11-21C23 5.9 18 1 12 1z\" fill=\"" + relleno +
      "\" stroke=\"" + borde + "\" stroke-width=\"" + (p.simulada === true ? 3 : 1.5) + "\"/>" +
      "<circle cx=\"12\" cy=\"12\" r=\"4.6\" fill=\"" + centro + "\" stroke=\"rgba(0,0,0,.25)\" stroke-width=\"1\"/></svg>";
    return L.divIcon({ className: "mf-pin", html: svg, iconSize: [24, 34], iconAnchor: [12, 33], popupAnchor: [0, -30] });
  }

  function popup(p) {
    var lineas = [
      "<strong>" + texto(p.empleado) + "</strong>" + (p.legajo ? " · " + texto(p.legajo) : ""),
      "<span class=\"mf-pop-accion mf-pop-" + texto(p.accion) + "\">" + texto(ACCIONES[p.accion] || p.accion) + "</span> " +
        texto(p.fecha) + " " + texto(p.hora) + " (" + texto(p.metodo || "-") + ")",
    ];
    if (p.sucursal) lineas.push("Sucursal: " + texto(p.sucursal));
    if (p.estado === "fuera") lineas.push("<span class=\"mf-pop-fuera\">Fuera del radio</span>");
    if (p.estado === "dentro") lineas.push("<span class=\"mf-pop-dentro\">Dentro del radio</span>");
    if (p.distancia != null) lineas.push("A " + texto(p.distancia) + " m del punto" + (p.tolerancia ? " (radio " + texto(p.tolerancia) + " m)" : ""));
    if (p.precision != null) lineas.push("Precisión del GPS: ±" + texto(p.precision) + " m");
    (p.alertas || []).forEach(function (a) {
      if (a !== "Fuera del radio") lineas.push("<span class=\"mf-pop-fuera\">" + texto(a) + "</span>");
    });
    return lineas.join("<br>");
  }

  function leyenda(mapa) {
    var control = L.control({ position: "bottomleft" });
    control.onAdd = function () {
      var div = L.DomUtil.create("div", "mf-leyenda");
      div.innerHTML =
        "<span><i class=\"mf-ley-pin\" style=\"background:" + COLOR_ACCION.ingreso + "\"></i>Ingreso</span>" +
        "<span><i class=\"mf-ley-pin\" style=\"background:" + COLOR_ACCION.egreso + "\"></i>Egreso</span>" +
        "<span><i class=\"mf-ley-centro\" style=\"background:" + COLOR_CENTRO.dentro + "\"></i>Dentro del radio</span>" +
        "<span><i class=\"mf-ley-centro\" style=\"background:" + COLOR_CENTRO.fuera + "\"></i>Fuera del radio</span>" +
        "<span><i class=\"mf-ley-zona\"></i>Sucursal o punto de validación</span>";
      return div;
    };
    control.addTo(mapa);
  }

  function iniciar() {
    var contenedor = document.getElementById("mf-mapa");
    var fuente = document.getElementById("mf-datos");
    if (!contenedor || !fuente || !window.L) return;
    var datos = JSON.parse(fuente.textContent || "{}");
    var mapa = L.map(contenedor, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
    }).addTo(mapa);
    mapa.on("focus", function () { mapa.scrollWheelZoom.enable(); });
    mapa.on("blur", function () { mapa.scrollWheelZoom.disable(); });
    leyenda(mapa);

    var limites = [];
    (datos.referencias || []).forEach(function (r) {
      if (r.lat == null || r.lon == null) return;
      limites.push([r.lat, r.lon]);
      if (r.radio) {
        L.circle([r.lat, r.lon], { radius: r.radio, color: "#2f5597", weight: 1, fillOpacity: 0.08 })
          .bindTooltip(texto(r.nombre) + " · radio " + texto(r.radio) + " m").addTo(mapa);
      }
      L.circleMarker([r.lat, r.lon], { radius: 5, color: "#2f5597", weight: 2, fillColor: "#ffffff", fillOpacity: 1 })
        .bindTooltip(texto(r.nombre)).addTo(mapa);
    });

    var marcadores = (datos.puntos || []).map(function (p) {
      limites.push([p.lat, p.lon]);
      if (p.precision) {
        L.circle([p.lat, p.lon], {
          radius: p.precision, color: COLOR_ACCION[p.accion] || "#6b7280", weight: 0, fillOpacity: 0.12, interactive: false,
        }).addTo(mapa);
      }
      return L.marker([p.lat, p.lon], { icon: pin(p), title: (ACCIONES[p.accion] || p.accion) + " · " + p.empleado,
                                       riseOnHover: true })
        .bindPopup(popup(p)).addTo(mapa);
    });

    if (limites.length) mapa.fitBounds(limites, { padding: [32, 32], maxZoom: 17 });
    else mapa.setView([-34.6037, -58.3816], 11);

    document.querySelectorAll(".mf-item[data-punto]").forEach(function (boton) {
      boton.addEventListener("click", function () {
        var marcador = marcadores[Number(boton.getAttribute("data-punto"))];
        if (!marcador) return;
        mapa.setView(marcador.getLatLng(), Math.max(mapa.getZoom(), 17));
        marcador.openPopup();
        contenedor.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
