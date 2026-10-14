// Comportamientos declarativos por atributos data-*, en lugar de handlers
// inline (onclick/onchange/...), para que la CSP pueda bloquear scripts inline.
//   data-autosubmit           en <select>/<input>: envia su formulario al cambiar.
//   data-print                en <a>/<button>: abre el dialogo de impresion.
//   data-href="url"           en cualquier elemento: navega al hacer click.
//   data-href-ignore          dentro de un data-href: ese area no navega.
//   data-fallback="url"       en <img>: imagen alternativa si falla la carga.
//   data-password-toggle="id" en <button>: muestra u oculta ese campo de clave.
//   data-date-range           en un contenedor con [data-range-from], [data-range-to],
//                             [data-range-submit] y [data-range-help]: habilita el
//                             boton solo con un rango valido y no futuro.
// Las confirmaciones (data-confirm) las resuelve panel-messages.js.
(function () {
  document.addEventListener("change", function (event) {
    var field = event.target.closest && event.target.closest("[data-autosubmit]");
    if (field && field.form) {
      // submit() no dispara el evento "submit": htmx no lo veria.
      if (field.form.hasAttribute("hx-get") && field.form.requestSubmit) {
        field.form.requestSubmit();
      } else {
        field.form.submit();
      }
    }
  });

  document.addEventListener("click", function (event) {
    var target = event.target.closest ? event.target : event.target.parentElement;
    if (!target) return;

    var printable = target.closest("[data-print]");
    if (printable) {
      event.preventDefault();
      window.print();
      return;
    }

    var passwordToggle = target.closest("[data-password-toggle]");
    if (passwordToggle) {
      var input = document.getElementById(passwordToggle.getAttribute("data-password-toggle"));
      if (!input) return;
      var reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      passwordToggle.setAttribute("aria-label", reveal ? "Ocultar contraseña" : "Mostrar contraseña");
      passwordToggle.classList.toggle("active", reveal);
      return;
    }

    var navigable = target.closest("[data-href]");
    if (navigable && !target.closest("a, button, input, select, textarea, label, [data-href-ignore]")) {
      window.location = navigable.getAttribute("data-href");
    }
  }, true);

  function refreshDateRange(container) {
    var from = container.querySelector("[data-range-from]");
    var to = container.querySelector("[data-range-to]");
    var submit = container.querySelector("[data-range-submit]");
    var help = container.querySelector("[data-range-help]");
    if (!from || !to || !submit || !help) return;
    var today = to.max || from.max || "";
    var message = "El sistema evaluara horario asignado y excepciones dia por dia.";
    if (!from.value || !to.value) {
      message = "Complete desde y hasta para habilitar la generacion por rango.";
    } else if (from.value > to.value) {
      message = "El rango es invalido: desde no puede ser mayor a hasta.";
    } else if (today && (from.value > today || to.value > today)) {
      message = "No se permite generar asistencia para fechas futuras.";
    }
    submit.disabled = message.indexOf("El sistema") !== 0;
    help.textContent = message;
  }

  function refreshAllDateRanges() {
    document.querySelectorAll("[data-date-range]").forEach(refreshDateRange);
  }

  document.addEventListener("input", function (event) {
    var container = event.target.closest && event.target.closest("[data-date-range]");
    if (container) refreshDateRange(container);
  });
  document.addEventListener("htmx:afterSettle", refreshAllDateRanges);

  function useFallback(img) {
    var fallback = img.getAttribute("data-fallback");
    if (fallback && img.getAttribute("src") !== fallback) {
      img.setAttribute("src", fallback);
    }
  }

  // "error" no burbujea: se escucha en captura. Las imagenes que fallaron antes
  // de cargar este script se corrigen al terminar de cargar el documento.
  document.addEventListener("error", function (event) {
    if (event.target.tagName === "IMG" && event.target.hasAttribute("data-fallback")) {
      useFallback(event.target);
    }
  }, true);

  function fixBrokenImages() {
    document.querySelectorAll("img[data-fallback]").forEach(function (img) {
      if (img.complete && img.naturalWidth === 0) useFallback(img);
    });
  }

  function onReady() {
    fixBrokenImages();
    refreshAllDateRanges();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }
})();
