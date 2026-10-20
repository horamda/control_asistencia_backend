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

    var capaFichadas = L.layerGroup();
    var capaQr = L.layerGroup();
    var mapa = window.FichaMapa ? FichaMapa.crear(contenedor, { "Fichadas recientes": capaFichadas, "QR activos": capaQr })
      : L.map(contenedor);
    capaFichadas.addTo(mapa);
    capaQr.addTo(mapa);

    var limites = [];
    (datos.puntos || []).forEach(function (p) {
      limites.push([p[0], p[1]]);
      L.circleMarker([p[0], p[1]], { radius: 4, color: "#4b5563", weight: 1, fillColor: "#9ca3af", fillOpacity: 0.7,
                                     interactive: false }).addTo(capaFichadas);
    });
    (datos.qrs || []).forEach(function (q) {
      L.circle([q.lat, q.lon], { radius: q.tolerancia || 30, color: q.desactualizado ? "#dc2626" : "#2f5597", weight: 1,
                                 dashArray: "4 4", fillOpacity: 0.05 })
        .bindTooltip(q.desactualizado ? "QR generado con otra ubicación: se valida contra la actual de la sucursal" : "QR activo").addTo(capaQr);
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

    buscador(ubicar);

    if (inicial) limites.push(inicial);
    if (limites.length > 1) mapa.fitBounds(limites, { padding: [32, 32], maxZoom: 17 });
    else mapa.setView(inicial || DEFECTO, inicial ? 17 : 11);
  }

  // Buscador de direcciones: lo resuelve el servidor (/sucursales/geocodificar, OpenStreetMap). Elegir un resultado
  // mueve el pin; se confirma al guardar el formulario.
  function buscador(ubicar) {
    var caja = document.querySelector(".su-buscar");
    var campo = document.getElementById("su-buscar");
    var boton = document.getElementById("su-buscar-btn");
    var lista = document.getElementById("su-resultados");
    var estado = document.getElementById("su-buscar-estado");
    if (!caja || !campo || !boton || !lista || !window.fetch) {
      if (caja) caja.hidden = true;
      return;
    }
    function avisar(mensaje) {
      estado.textContent = mensaje || "";
      estado.hidden = !mensaje;
    }
    function buscar() {
      var q = campo.value.trim();
      lista.hidden = true;
      lista.innerHTML = "";
      if (q.length < 4) { avisar("Escribí al menos 4 letras de la dirección."); return; }
      avisar("Buscando…");
      boton.disabled = true;
      fetch(caja.getAttribute("data-url") + "?q=" + encodeURIComponent(q), { credentials: "same-origin",
                                                                           headers: { Accept: "application/json" } })
        .then(function (r) { return r.json().then(function (cuerpo) { return { ok: r.ok, cuerpo: cuerpo }; }); })
        .then(function (res) {
          if (!res.ok) { avisar(res.cuerpo.error || "No se pudo buscar."); return; }
          var resultados = res.cuerpo.resultados || [];
          if (!resultados.length) { avisar("No se encontró esa dirección. Probá con calle, número y ciudad."); return; }
          avisar("Elegí el resultado correcto y revisá el pin en el mapa:");
          resultados.forEach(function (r) {
            var item = document.createElement("li");
            var opcion = document.createElement("button");
            opcion.type = "button";
            opcion.className = "su-resultado btn-ghost";
            opcion.textContent = r.nombre;
            opcion.addEventListener("click", function () {
              ubicar([r.lat, r.lon], true);
              lista.hidden = true;
              avisar("Pin ubicado en: " + r.nombre + ". Revisalo con la vista Satélite y guardá.");
            });
            item.appendChild(opcion);
            lista.appendChild(item);
          });
          lista.hidden = false;
        })
        .catch(function () { avisar("No se pudo buscar. Probá de nuevo o ubicá el pin a mano."); })
        .then(function () { boton.disabled = false; });
    }
    boton.addEventListener("click", buscar);
    campo.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); buscar(); }  // no enviar el formulario de la sucursal
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
