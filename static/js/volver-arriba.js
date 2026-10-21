/* Boton "Volver arriba" del panel: aparece despues de bajar una pantalla y media y sube con un desplazamiento suave.
   Vive fuera de #page-content, asi sobrevive a la navegacion por htmx. En el celular se ubica arriba de la barra de
   botones que queda fija abajo de los formularios (Guardar, Volver), para no taparla. */
(function () {
  if (!document.querySelector(".app-shell") || document.getElementById("volver-arriba")) return;

  var boton = document.createElement("button");
  boton.type = "button";
  boton.id = "volver-arriba";
  boton.className = "volver-arriba btn-ghost";
  boton.title = "Volver arriba";
  boton.setAttribute("aria-label", "Volver arriba");
  boton.hidden = true;
  boton.innerHTML =
    '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">' +
    '<path fill="currentColor" d="M12 4.6 4.8 11.8l1.4 1.4L11 8.4V20h2V8.4l4.8 4.8 1.4-1.4z"/></svg>';
  document.body.appendChild(boton);

  var MARGEN = 16;
  var pendiente = false;

  function barraFija() {
    var barras = document.querySelectorAll('#page-content form:not([method="get"]) > .actions:last-child');
    for (var i = 0; i < barras.length; i++) {
      if (window.getComputedStyle(barras[i]).position !== "sticky") continue;
      var r = barras[i].getBoundingClientRect();
      if (r.height && r.top < window.innerHeight && r.bottom > 0) return r;
    }
    return null;
  }

  function actualizar() {
    pendiente = false;
    boton.hidden = window.scrollY < Math.max(400, window.innerHeight * 1.5);
    if (boton.hidden) return;
    var barra = barraFija();
    boton.style.bottom = barra ? Math.max(MARGEN, window.innerHeight - barra.top + 12) + "px" : "";
  }

  function programar() {
    if (pendiente) return;
    pendiente = true;
    window.requestAnimationFrame(actualizar);
  }

  boton.addEventListener("click", function () {
    var reducido = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reducido ? "auto" : "smooth" });
  });
  window.addEventListener("scroll", programar, { passive: true });
  window.addEventListener("resize", programar);
  document.body.addEventListener("htmx:afterSwap", programar);
  actualizar();
})();
