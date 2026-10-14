// Filtros y paginacion sin recargar la pagina, en todos los modulos.
// Mejora automaticamente, dentro de #page-content:
//   - formularios GET de filtros,
//   - enlaces de la paginacion (.pager),
//   - enlaces "Limpiar/Quitar filtros" que apuntan a la misma pagina del filtro.
// El servidor responde la pagina completa (sin cambios en las rutas) y htmx
// toma solo #page-content: el menu no se recarga y la URL se actualiza.
// Los campos de texto de esos formularios buscan mientras se escribe (pausa
// de 400 ms); data-no-live en un campo lo desactiva.
// Se excluyen: paginas marcadas data-no-ajax (tienen JavaScript propio),
// elementos con data-no-ajax, exportaciones/descargas y formularios con target.
(function () {
  var EXPORT_PATTERN = /export|descargar|\.(xlsx?|csv|pdf)(\?|$)/i;
  var LIVE_FIELDS = "input[type=search], input[type=text], input:not([type])";
  var LIVE_DELAY_MS = 400;
  var typingField = null;

  function samePath(url, other) {
    try {
      return new URL(url, window.location.href).pathname === new URL(other, window.location.href).pathname;
    } catch (_) {
      return false;
    }
  }

  function isEligibleForm(form) {
    if ((form.getAttribute("method") || "get").toLowerCase() !== "get") return false;
    if (form.hasAttribute("data-no-ajax") || form.target) return false;
    var action = form.getAttribute("action") || window.location.pathname;
    if (EXPORT_PATTERN.test(action) || !samePath(action, window.location.href)) return false;
    // Botones que envian a otra URL o ventana (p. ej. "Exportar") quedan como estan.
    return !form.querySelector("[formaction], [formtarget]");
  }

  function enhance(element, url, swap) {
    element.setAttribute("hx-get", url);
    element.setAttribute("hx-target", "#page-content");
    element.setAttribute("hx-select", "#page-content");
    element.setAttribute("hx-swap", swap);
    element.setAttribute("hx-push-url", "true");
    element.setAttribute("hx-indicator", "#page-content");
  }

  function enhanceContent() {
    var content = document.getElementById("page-content");
    if (!content || !window.htmx || content.hasAttribute("data-no-ajax")) return;

    content.querySelectorAll("form").forEach(function (form) {
      if (form.hasAttribute("hx-get") || !isEligibleForm(form)) return;
      enhance(form, form.getAttribute("action") || window.location.pathname, "outerHTML");
      form.querySelectorAll("a[href]").forEach(function (link) {
        if (!link.hasAttribute("data-no-ajax") && samePath(link.href, window.location.href)) {
          enhance(link, link.getAttribute("href"), "outerHTML");
        }
      });
    });

    content.querySelectorAll(".pager a[href]").forEach(function (link) {
      if (link.hasAttribute("hx-get") || link.hasAttribute("data-no-ajax")) return;
      if (EXPORT_PATTERN.test(link.getAttribute("href")) || !samePath(link.href, window.location.href)) return;
      enhance(link, link.getAttribute("href"), "outerHTML show:window:top");
    });

    window.htmx.process(content);
  }

  function notifyError(message) {
    if (window.PanelUI && window.PanelUI.notify) {
      window.PanelUI.notify(message, "error");
    }
  }

  function isLiveField(field) {
    return field && field.matches && field.matches(LIVE_FIELDS) && !field.hasAttribute("data-no-live") &&
      field.name && field.form && field.form.hasAttribute("hx-get");
  }

  function scheduleSearch(form) {
    window.clearTimeout(form._liveTimer);
    form._liveTimer = window.setTimeout(function () {
      if (form.isConnected && form.requestSubmit) form.requestSubmit();
    }, LIVE_DELAY_MS);
  }

  document.addEventListener("input", function (event) {
    if (isLiveField(event.target)) scheduleSearch(event.target.form);
  });

  // El reemplazo crea un campo nuevo: se guarda lo que se esta escribiendo
  // (puede haber cambiado mientras viajaba el pedido) para restaurarlo.
  document.addEventListener("htmx:beforeSwap", function (event) {
    if (!event.detail.target || event.detail.target.id !== "page-content") return;
    var active = document.activeElement;
    typingField = isLiveField(active)
      ? { name: active.name, value: active.value, start: active.selectionStart, end: active.selectionEnd }
      : null;
  });

  function restoreTypingField(content) {
    if (!typingField) return;
    var saved = typingField;
    typingField = null;
    var form = content.querySelector("form[hx-get]");
    var field = form && form.elements.namedItem(saved.name);
    if (!field || !field.focus) return;
    form.setAttribute("data-filters-open", "");
    var outdated = field.value !== saved.value;
    field.value = saved.value;
    field.focus();
    try {
      field.setSelectionRange(saved.start, saved.end);
    } catch (_) {}
    if (outdated) scheduleSearch(form);
  }

  document.addEventListener("DOMContentLoaded", enhanceContent);

  // El contenido nuevo llega sin los atributos: se vuelve a mejorar.
  document.addEventListener("htmx:afterSettle", function (event) {
    if (!event.target || event.target.id !== "page-content") return;
    enhanceContent();
    restoreTypingField(event.target);
  });

  document.addEventListener("htmx:responseError", function (event) {
    if (event.detail.target && event.detail.target.id !== "page-content") return;
    notifyError("No se pudo actualizar el listado (error " + event.detail.xhr.status + "). Intente nuevamente.");
  });

  document.addEventListener("htmx:sendError", function () {
    notifyError("Sin conexion con el servidor. Revise la red e intente nuevamente.");
  });
})();
