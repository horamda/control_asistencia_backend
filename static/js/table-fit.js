// Tablas que se adaptan al espacio real de su panel (no al ancho de ventana):
// con el menu abierto, en notebooks o tablets el panel puede ser mas angosto
// que la tabla aunque la pantalla "sea de escritorio".
//   - Si la tabla tiene etiquetas por celda (td[data-label]) y no entra, pasa a
//     tarjetas (.is-cards): cada fila es una tarjeta con sus campos en columnas.
//   - Si no tiene etiquetas (importaciones, reportes) se desplaza en horizontal
//     y muestra una sombra del lado donde hay mas columnas.
// data-no-cards en el contenedor mantiene siempre la tabla.
// En mobile (<= 760px) las .table-cards ya son tarjetas por CSS (panel.css).
(function () {
  var mobile = window.matchMedia("(max-width: 760px)");
  var observed = new Set();
  var resizeObserver = window.ResizeObserver ? new ResizeObserver(function (entries) {
    entries.forEach(function (entry) { update(entry.target); });
  }) : null;

  function tableOf(wrap) {
    for (var i = 0; i < wrap.children.length; i++) {
      if (wrap.children[i].tagName === "TABLE") return wrap.children[i];
    }
    return null;
  }

  function updateScrollHint(wrap) {
    var max = wrap.scrollWidth - wrap.clientWidth;
    var scrollable = !wrap.classList.contains("is-cards") && max > 1;
    wrap.classList.toggle("has-more-left", scrollable && wrap.scrollLeft > 1);
    wrap.classList.toggle("has-more-right", scrollable && wrap.scrollLeft < max - 1);
  }

  function update(wrap) {
    var table = tableOf(wrap);
    if (!table || !wrap.clientWidth) return;
    var cssCards = mobile.matches && wrap.classList.contains("table-cards");
    var canCards = !cssCards && !wrap.hasAttribute("data-no-cards") && !!table.querySelector("td[data-label]");
    // Se mide siempre en modo tabla; el cambio de clase y la lectura ocurren
    // en el mismo cuadro, sin parpadeo.
    wrap.classList.remove("is-cards");
    if (canCards && table.scrollWidth > wrap.clientWidth + 1) {
      wrap.classList.add("is-cards");
    }
    updateScrollHint(wrap);
  }

  // Tablas sueltas que desbordan su contenedor: se envuelven para que se
  // desplacen dentro del panel en lugar de ensanchar toda la pagina.
  function wrapLooseTables() {
    document.querySelectorAll("#page-content table, .embedded-layout table").forEach(function (table) {
      if (table.closest(".table-responsive, svg")) return;
      var parent = table.parentElement;
      if (!parent || table.offsetWidth <= parent.clientWidth + 1) return;
      var overflowX = window.getComputedStyle(parent).overflowX;
      if (overflowX === "auto" || overflowX === "scroll") return;
      var wrap = document.createElement("div");
      wrap.className = "table-responsive";
      parent.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }

  function observeTables() {
    // Las tablas que htmx reemplazo ya no estan en el documento: se sueltan.
    observed.forEach(function (wrap) {
      if (wrap.isConnected) return;
      observed.delete(wrap);
      if (resizeObserver) resizeObserver.unobserve(wrap);
    });
    wrapLooseTables();
    document.querySelectorAll(".table-responsive").forEach(function (wrap) {
      if (observed.has(wrap)) return;
      observed.add(wrap);
      wrap.addEventListener("scroll", function () { updateScrollHint(wrap); }, { passive: true });
      if (resizeObserver) resizeObserver.observe(wrap);
      update(wrap);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", observeTables);
  } else {
    observeTables();
  }
  // Contenido nuevo de htmx (filtros, paginacion, dashboard).
  document.addEventListener("htmx:afterSettle", observeTables);
  if (!resizeObserver) {
    window.addEventListener("resize", function () {
      document.querySelectorAll(".table-responsive").forEach(update);
    });
  }
  // Al imprimir se usa la tabla completa; al volver se recalcula.
  window.addEventListener("beforeprint", function () {
    document.querySelectorAll(".table-responsive.is-cards").forEach(function (wrap) {
      wrap.classList.remove("is-cards");
    });
  });
  window.addEventListener("afterprint", function () {
    document.querySelectorAll(".table-responsive").forEach(update);
  });
  var onMediaChange = function () { document.querySelectorAll(".table-responsive").forEach(update); };
  if (mobile.addEventListener) mobile.addEventListener("change", onMediaChange);
})();
