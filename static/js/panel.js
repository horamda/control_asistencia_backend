(function () {
  function normalizeHeading() {
    var content = document.querySelector(".page-content");
    var titleNode = document.getElementById("page-title");
    if (!content || !titleNode) return;
    var h2 = content.querySelector("h2");
    if (h2 && h2.textContent.trim()) {
      titleNode.textContent = h2.textContent.trim();
    }
  }

  function markActiveNav() {
    var path = window.location.pathname || "";
    var links = document.querySelectorAll(".nav-link");
    links.forEach(function (link) {
      var href = link.getAttribute("href") || "";
      if (!href || href === "/") return;
      if (path === href || (href !== "/dashboard" && path.indexOf(href) === 0)) {
        link.classList.add("active");
      }
    });
  }

  function styleStates() {
    document.querySelectorAll("td").forEach(function (cell) {
      var text = (cell.textContent || "").trim().toLowerCase();
      if (text === "activo" || text === "ok") {
        cell.innerHTML = '<span class="badge ok">' + cell.textContent.trim() + "</span>";
      } else if (text === "inactivo" || text === "ausente") {
        cell.innerHTML = '<span class="badge danger">' + cell.textContent.trim() + "</span>";
      } else if (text === "tarde" || text === "salida_anticipada" || text === "suspendido") {
        cell.innerHTML = '<span class="badge warning">' + cell.textContent.trim() + "</span>";
      }
    });
  }

  function addDeleteConfirm() {
    document.querySelectorAll("form[action*='/eliminar/']").forEach(function (form) {
      if (form.getAttribute("data-confirm-bound") === "1") return;
      form.setAttribute("data-confirm-bound", "1");
      form.addEventListener("submit", function (event) {
        if (!window.confirm("Confirma eliminar este registro?")) {
          event.preventDefault();
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    normalizeHeading();
    markActiveNav();
    styleStates();
    addDeleteConfirm();
  });
})();
