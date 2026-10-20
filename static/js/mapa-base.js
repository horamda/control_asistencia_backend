// Base comun de los mapas del panel (Leaflet local): fondos para elegir (calles, satelite, claro), boton de pantalla
// completa y utilidades. Se carga despues de leaflet.js y antes del script de cada mapa.
(function () {
  var CLAVE_FONDO = "fichaya_mapa_fondo";

  function fondos() {
    return {
      "Calles": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
      }),
      "Satélite": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 19, attribution: "Imágenes &copy; Esri, Maxar, Earthstar Geographics",
      }),
      "Claro": L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
        maxZoom: 19, subdomains: "abcd",
        attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> &copy; <a href=\"https://carto.com/attributions\">CARTO</a>",
      }),
    };
  }

  function leer(clave) {
    try { return window.localStorage.getItem(clave); } catch (e) { return null; }
  }

  function guardar(clave, valor) {
    try { window.localStorage.setItem(clave, valor); } catch (e) { /* navegador sin almacenamiento */ }
  }

  function pantallaCompleta(mapa, contenedor) {
    var control = L.control({ position: "topleft" });
    control.onAdd = function () {
      var boton = L.DomUtil.create("button", "mapa-pantalla-completa btn-ghost");
      boton.type = "button";
      boton.title = "Pantalla completa";
      boton.setAttribute("aria-label", "Pantalla completa");
      boton.setAttribute("aria-pressed", "false");
      boton.innerHTML = "<svg viewBox=\"0 0 24 24\" width=\"18\" height=\"18\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"><path d=\"M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5\"/></svg>";
      L.DomEvent.disableClickPropagation(boton);
      function cambiar(activa) {
        contenedor.classList.toggle("mapa-completo", activa);
        document.documentElement.classList.toggle("mapa-completo-abierto", activa);
        boton.setAttribute("aria-pressed", activa ? "true" : "false");
        boton.title = activa ? "Salir de pantalla completa" : "Pantalla completa";
        setTimeout(function () { mapa.invalidateSize(); }, 50);
      }
      L.DomEvent.on(boton, "click", function (e) {
        L.DomEvent.preventDefault(e);
        cambiar(!contenedor.classList.contains("mapa-completo"));
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && contenedor.classList.contains("mapa-completo")) cambiar(false);
      });
      return boton;
    };
    control.addTo(mapa);
  }

  /** Crea el mapa con fondos y pantalla completa. overlays: {nombre: capa} para el selector de capas. */
  function crear(contenedor, overlays) {
    var mapa = L.map(contenedor, { scrollWheelZoom: false });
    var capas = fondos();
    var elegido = leer(CLAVE_FONDO);
    (capas[elegido] || capas["Calles"]).addTo(mapa);
    L.control.layers(capas, overlays || {}, { position: "topright", collapsed: true }).addTo(mapa);
    mapa.on("baselayerchange", function (e) { guardar(CLAVE_FONDO, e.name); });
    mapa.on("focus", function () { mapa.scrollWheelZoom.enable(); });
    mapa.on("blur", function () { mapa.scrollWheelZoom.disable(); });
    pantallaCompleta(mapa, contenedor);
    return mapa;
  }

  function texto(valor) {
    var div = document.createElement("div");
    div.textContent = valor == null ? "" : String(valor);
    return div.innerHTML;
  }

  function enlaceGoogle(lat, lon) {
    return "<a href=\"https://www.google.com/maps?q=" + Number(lat).toFixed(6) + "," + Number(lon).toFixed(6) +
      "\" target=\"_blank\" rel=\"noopener noreferrer\">Ver en Google Maps</a>";
  }

  window.FichaMapa = { crear: crear, texto: texto, enlaceGoogle: enlaceGoogle };
})();
