// Formulario de sucursal: ubicacion con un pin arrastrable y el circulo del radio permitido. Completa los campos
// latitud y longitud. Datos opcionales en <script type="application/json" id="su-datos">: fichadas recientes de sus
// empleados (puntos grises), la sugerencia (punto central de esas fichadas) y los QR de puerta activos.
(function () {
  var DEFECTO = [-34.6037, -58.3816];

  function numero(input) {
    var valor = parseFloat(String(input.value || "").replace(",", "."));
    return isFinite(valor) ? valor : null;
  }

  function iniciar() {
    var contenedor = document.getElementById("su-mapa");
    var lat = document.getElementById("su-lat");
    var lon = document.getElementById("su-lon");
    var radio = document.getElementById("su-radio");
    if (!contenedor || !lat || !lon || !window.L) return;
    var fuente = document.getElementById("su-datos");
    var datos = fuente ? JSON.parse(fuente.textContent || "{}") : {};
    var aviso = document.getElementById("su-radio-aviso");

    var mapa = L.map(contenedor, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
    }).addTo(mapa);
    mapa.on("focus", function () { mapa.scrollWheelZoom.enable(); });
    mapa.on("blur", function () { mapa.scrollWheelZoom.disable(); });

    var limites = [];
    (datos.puntos || []).forEach(function (p) {
      limites.push([p[0], p[1]]);
      L.circleMarker([p[0], p[1]], { radius: 4, color: "#4b5563", weight: 1, fillColor: "#9ca3af", fillOpacity: 0.7,
                                     interactive: false }).addTo(mapa);
    });
    (datos.qrs || []).forEach(function (q) {
      L.circle([q.lat, q.lon], { radius: q.tolerancia || 30, color: q.desactualizado ? "#dc2626" : "#2f5597", weight: 1,
                                 dashArray: "4 4", fillOpacity: 0.05 })
        .bindTooltip(q.desactualizado ? "QR activo con otra ubicación (desactualizado)" : "QR activo").addTo(mapa);
    });

    var inicial = numero(lat) !== null && numero(lon) !== null ? [numero(lat), numero(lon)]
      : (datos.sugerencia ? [datos.sugerencia.lat, datos.sugerencia.lon] : null);
    var icono = L.divIcon({
      className: "su-pin", iconSize: [30, 42], iconAnchor: [15, 41],
      html: "<svg viewBox=\"0 0 24 34\" width=\"30\" height=\"42\" aria-hidden=\"true\"><path d=\"M12 1C6 1 1 5.9 1 12c0 8.2 11 21 11 21s11-12.8 11-21C23 5.9 18 1 12 1z\" fill=\"#16a34a\" stroke=\"#ffffff\" stroke-width=\"1.5\"/><circle cx=\"12\" cy=\"12\" r=\"4.6\" fill=\"#ffffff\"/></svg>",
    });
    var pin = L.marker(inicial || DEFECTO, { icon: icono, draggable: true, autoPan: true, title: "Ubicación de la sucursal" })
      .addTo(mapa);
    var circulo = L.circle(inicial || DEFECTO, { radius: numero(radio) || 0, color: "#16a34a", weight: 2, fillOpacity: 0.12 })
      .addTo(mapa);
    if (!inicial) pin.setOpacity(0.5);

    function mostrarRadio() {
      var r = numero(radio);
      circulo.setRadius(r && r > 0 ? r : 0);
      if (aviso) aviso.hidden = !(r && r > 0 && r < 50);
    }

    function ubicar(punto, centrar) {
      pin.setLatLng(punto).setOpacity(1);
      circulo.setLatLng(punto);
      lat.value = punto[0].toFixed(7);
      lon.value = punto[1].toFixed(7);
      if (centrar) mapa.setView(punto, Math.max(mapa.getZoom() || 0, 17));
    }

    pin.on("dragend", function () {
      var p = pin.getLatLng();
      ubicar([p.lat, p.lng], false);
    });
    mapa.on("click", function (e) { ubicar([e.latlng.lat, e.latlng.lng], false); });
    [lat, lon].forEach(function (input) {
      input.addEventListener("change", function () {
        if (numero(lat) !== null && numero(lon) !== null) ubicar([numero(lat), numero(lon)], true);
      });
    });
    if (radio) radio.addEventListener("input", mostrarRadio);
    mostrarRadio();

    var sugerencia = document.getElementById("su-sugerencia");
    if (sugerencia && datos.sugerencia) {
      sugerencia.addEventListener("click", function () { ubicar([datos.sugerencia.lat, datos.sugerencia.lon], true); });
    }
    var miUbicacion = document.getElementById("su-mi-ubicacion");
    if (miUbicacion) {
      if (!navigator.geolocation) miUbicacion.hidden = true;
      miUbicacion.addEventListener("click", function () {
        miUbicacion.disabled = true;
        navigator.geolocation.getCurrentPosition(function (pos) {
          miUbicacion.disabled = false;
          ubicar([pos.coords.latitude, pos.coords.longitude], true);
        }, function () {
          miUbicacion.disabled = false;
          window.alert("No se pudo obtener tu ubicación. Revisá el permiso de ubicación del navegador.");
        }, { enableHighAccuracy: true, timeout: 15000 });
      });
    }

    if (inicial) limites.push(inicial);
    if (limites.length > 1) mapa.fitBounds(limites, { padding: [32, 32], maxZoom: 17 });
    else mapa.setView(inicial || DEFECTO, inicial ? 17 : 11);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
