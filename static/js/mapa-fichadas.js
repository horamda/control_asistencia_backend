// Mapa de fichadas (panel, solo lectura). Los datos vienen en <script type="application/json" id="mf-datos">.
// Base comun en mapa-base.js (fondos y pantalla completa); agrupado de pines con Leaflet.markercluster (local).
// Cada fichada es un pin: verde el ingreso, naranja el egreso; el centro blanco si quedo dentro del radio, rojo si
// quedo fuera y gris si no se valido; borde violeta si el telefono marco el GPS como simulado. Los pines cercanos se
// agrupan en un circulo con la cantidad (borde rojo si alguno quedo fuera del radio).
(function () {
  var ACCIONES = { ingreso: "Ingreso", egreso: "Egreso" };
  var COLOR_ACCION = { ingreso: "#16a34a", egreso: "#ea580c" };
  var COLOR_CENTRO = { dentro: "#ffffff", fuera: "#dc2626", sin_validar: "#9ca3af" };

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
    var t = FichaMapa.texto;
    var lineas = [
      "<strong>" + t(p.empleado) + "</strong>" + (p.legajo ? " · " + t(p.legajo) : ""),
      "<span class=\"mf-pop-accion mf-pop-" + t(p.accion) + "\">" + t(ACCIONES[p.accion] || p.accion) + "</span> " +
        t(p.fecha) + " " + t(p.hora) + " (" + t(p.metodo || "-") + ")",
    ];
    if (p.sucursal) lineas.push("Sucursal: " + t(p.sucursal));
    if (p.estado === "fuera") lineas.push("<span class=\"mf-pop-fuera\">Fuera del radio</span>");
    if (p.estado === "dentro") lineas.push("<span class=\"mf-pop-dentro\">Dentro del radio</span>");
    if (p.distancia != null) lineas.push("A " + t(p.distancia) + " m del punto" + (p.tolerancia ? " (radio " + t(p.tolerancia) + " m)" : ""));
    if (p.precision != null) lineas.push("Precisión del GPS: ±" + t(p.precision) + " m");
    (p.alertas || []).forEach(function (a) {
      if (a !== "Fuera del radio") lineas.push("<span class=\"mf-pop-fuera\">" + t(a) + "</span>");
    });
    lineas.push(FichaMapa.enlaceGoogle(p.lat, p.lon));
    return lineas.join("<br>");
  }

  function grupo(accion) {
    return L.markerClusterGroup({
      showCoverageOnHover: false, spiderfyOnMaxZoom: true, maxClusterRadius: 45, chunkedLoading: true,
      iconCreateFunction: function (cluster) {
        var hijos = cluster.getAllChildMarkers();
        var fuera = hijos.some(function (m) { return m.options.estado === "fuera"; });
        var n = cluster.getChildCount();
        var tam = n < 10 ? 34 : n < 100 ? 40 : 48;
        return L.divIcon({
          className: "mf-grupo mf-grupo-" + accion + (fuera ? " mf-grupo-fuera" : ""),
          html: "<span>" + n + "</span>", iconSize: [tam, tam],
        });
      },
    });
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
        "<span><i class=\"mf-ley-grupo\"></i>Varias fichadas juntas (rojo: alguna fuera)</span>" +
        "<span><i class=\"mf-ley-zona\"></i>Sucursal o punto de validación</span>";
      return div;
    };
    control.addTo(mapa);
  }

  function iniciar() {
    var contenedor = document.getElementById("mf-mapa");
    var fuente = document.getElementById("mf-datos");
    if (!contenedor || !fuente || !window.L || !window.FichaMapa) return;
    var datos = JSON.parse(fuente.textContent || "{}");
    var t = FichaMapa.texto;

    var grupos = { ingreso: grupo("ingreso"), egreso: grupo("egreso") };
    var referencias = L.layerGroup();
    var precision = L.layerGroup();
    var mapa = FichaMapa.crear(contenedor, {
      "Ingresos": grupos.ingreso, "Egresos": grupos.egreso, "Sucursales y QR": referencias, "Precisión del GPS": precision,
    });
    [grupos.ingreso, grupos.egreso, referencias, precision].forEach(function (capa) { capa.addTo(mapa); });
    leyenda(mapa);

    var limites = [];
    (datos.referencias || []).forEach(function (r) {
      if (r.lat == null || r.lon == null) return;
      limites.push([r.lat, r.lon]);
      if (r.radio) {
        L.circle([r.lat, r.lon], { radius: r.radio, color: "#2f5597", weight: 1, fillOpacity: 0.08 })
          .bindTooltip(t(r.nombre) + " · radio " + t(r.radio) + " m").addTo(referencias);
      }
      L.circleMarker([r.lat, r.lon], { radius: 5, color: "#2f5597", weight: 2, fillColor: "#ffffff", fillOpacity: 1 })
        .bindTooltip(t(r.nombre)).addTo(referencias);
    });

    var marcadores = (datos.puntos || []).map(function (p) {
      limites.push([p.lat, p.lon]);
      if (p.precision) {
        L.circle([p.lat, p.lon], {
          radius: p.precision, color: COLOR_ACCION[p.accion] || "#6b7280", weight: 0, fillOpacity: 0.12, interactive: false,
        }).addTo(precision);
      }
      var marcador = L.marker([p.lat, p.lon], { icon: pin(p), estado: p.estado, riseOnHover: true,
                                                title: (ACCIONES[p.accion] || p.accion) + " · " + p.empleado })
        .bindPopup(popup(p));
      (grupos[p.accion] || grupos.ingreso).addLayer(marcador);
      marcador.grupo = grupos[p.accion] || grupos.ingreso;
      return marcador;
    });

    if (limites.length) mapa.fitBounds(limites, { padding: [32, 32], maxZoom: 17 });
    else mapa.setView([-34.6037, -58.3816], 11);

    document.querySelectorAll(".mf-item[data-punto]").forEach(function (boton) {
      boton.addEventListener("click", function () {
        var marcador = marcadores[Number(boton.getAttribute("data-punto"))];
        if (!marcador) return;
        if (!mapa.hasLayer(marcador.grupo)) marcador.grupo.addTo(mapa);
        contenedor.scrollIntoView({ behavior: "smooth", block: "nearest" });
        marcador.grupo.zoomToShowLayer(marcador, function () { marcador.openPopup(); });
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
