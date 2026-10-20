// Mapa de fichadas (panel, solo lectura). Los datos vienen en <script type="application/json" id="mf-datos">.
// Leaflet local (static/vendor/leaflet) y mosaicos de OpenStreetMap con su atribucion.
(function () {
  var COLORES = { dentro: "#1e8a4c", fuera: "#c53a4d", sin_validar: "#6b7280" };
  var ACCIONES = { ingreso: "Ingreso", egreso: "Egreso" };

  function texto(valor) {
    var div = document.createElement("div");
    div.textContent = valor == null ? "" : String(valor);
    return div.innerHTML;
  }

  function popup(p) {
    var lineas = [
      "<strong>" + texto(p.empleado) + "</strong>" + (p.legajo ? " · " + texto(p.legajo) : ""),
      texto(p.fecha) + " " + texto(p.hora) + " · " + texto(ACCIONES[p.accion] || p.accion) + " (" + texto(p.metodo || "-") + ")",
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

  function iniciar() {
    var contenedor = document.getElementById("mf-mapa");
    var fuente = document.getElementById("mf-datos");
    if (!contenedor || !fuente || !window.L) return;
    var datos = JSON.parse(fuente.textContent || "{}");
    var mapa = L.map(contenedor, { preferCanvas: true, scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
    }).addTo(mapa);
    mapa.on("focus", function () { mapa.scrollWheelZoom.enable(); });
    mapa.on("blur", function () { mapa.scrollWheelZoom.disable(); });

    var limites = [];
    (datos.referencias || []).forEach(function (r) {
      if (r.lat == null || r.lon == null) return;
      limites.push([r.lat, r.lon]);
      if (r.radio) {
        L.circle([r.lat, r.lon], { radius: r.radio, color: "#2f5597", weight: 1, fillOpacity: 0.08 })
          .bindTooltip(texto(r.nombre) + " · radio " + texto(r.radio) + " m").addTo(mapa);
      }
      L.circleMarker([r.lat, r.lon], { radius: 4, color: "#2f5597", fillOpacity: 1 }).bindTooltip(texto(r.nombre)).addTo(mapa);
    });

    var marcadores = (datos.puntos || []).map(function (p) {
      limites.push([p.lat, p.lon]);
      if (p.precision) {
        L.circle([p.lat, p.lon], {
          radius: p.precision, color: COLORES[p.estado] || COLORES.sin_validar, weight: 0, fillOpacity: 0.12, interactive: false,
        }).addTo(mapa);
      }
      if (p.estado === "fuera" && p.ref) {
        L.polyline([[p.lat, p.lon], p.ref], { color: COLORES.fuera, weight: 1, dashArray: "4 4" }).addTo(mapa);
      }
      var simulada = p.simulada === true;
      return L.circleMarker([p.lat, p.lon], {
        radius: simulada ? 9 : 7, color: simulada ? "#7c3aed" : "#ffffff", weight: simulada ? 3 : 1.5,
        fillColor: COLORES[p.estado] || COLORES.sin_validar, fillOpacity: 0.95,
      }).bindPopup(popup(p)).addTo(mapa);
    });

    if (limites.length) mapa.fitBounds(limites, { padding: [24, 24], maxZoom: 17 });
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
