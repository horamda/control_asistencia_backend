(function () {
  var THEME_KEY = "ca_theme";

  function getStoredTheme() {
    try {
      var value = localStorage.getItem(THEME_KEY);
      return value === "dark" || value === "light" ? value : null;
    } catch (_) {
      return null;
    }
  }

  function getSystemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function getCurrentTheme() {
    var attr = document.documentElement.getAttribute("data-theme");
    if (attr === "dark" || attr === "light") return attr;
    return getStoredTheme() || getSystemTheme();
  }

  function updateThemeToggleLabel(theme) {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    var textNode = button.querySelector(".theme-toggle-text");
    var isDark = theme === "dark";
    button.setAttribute("aria-pressed", isDark ? "true" : "false");
    button.setAttribute("title", isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
    if (textNode) {
      textNode.textContent = isDark ? "Modo claro" : "Modo oscuro";
    }
  }

  function applyTheme(theme, persist) {
    var next = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    updateThemeToggleLabel(next);
    if (persist) {
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (_) {}
    }
  }

  function initThemeToggle() {
    var button = document.getElementById("theme-toggle");
    if (!button) return;

    var initialTheme = getStoredTheme() || getCurrentTheme();
    applyTheme(initialTheme, false);

    button.addEventListener("click", function () {
      var current = getCurrentTheme();
      var next = current === "dark" ? "light" : "dark";
      applyTheme(next, true);
    });
  }

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

  function initNavGroups() {
    var groups = document.querySelectorAll(".nav-group[data-collapsible='1']");
    if (!groups.length) return;

    function setGroupOpen(group, open) {
      var toggle = group.querySelector(".nav-group-toggle");
      group.classList.toggle("open", open);
      if (toggle) {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
      }
    }

    groups.forEach(function (group) {
      var toggle = group.querySelector(".nav-group-toggle");
      if (!toggle) return;

      var hasActiveLink = !!group.querySelector(".nav-link.active");
      setGroupOpen(group, hasActiveLink);

      toggle.addEventListener("click", function () {
        var shouldOpen = !group.classList.contains("open");
        groups.forEach(function (other) {
          if (other === group) return;
          setGroupOpen(other, false);
        });
        setGroupOpen(group, shouldOpen);
      });
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

  function addDataConfirm() {
    document.querySelectorAll("[data-confirm]").forEach(function (node) {
      if (node.getAttribute("data-confirm-bound") === "1") return;
      node.setAttribute("data-confirm-bound", "1");
      var message = node.getAttribute("data-confirm") || "Confirma esta accion?";
      var tag = (node.tagName || "").toLowerCase();
      if (tag === "form") {
        node.addEventListener("submit", function (event) {
          if (!window.confirm(message)) {
            event.preventDefault();
          }
        });
        return;
      }
      node.addEventListener("click", function (event) {
        if (!window.confirm(message)) {
          event.preventDefault();
        }
      });
    });
  }

  function initNavToggle() {
    var body = document.body;
    var toggle = document.getElementById("nav-toggle");
    var close = document.getElementById("sidebar-close");
    var overlay = document.getElementById("nav-overlay");
    if (!body || !toggle || !close || !overlay) return;

    function setOpen(open) {
      if (open) {
        body.classList.add("nav-open");
        toggle.setAttribute("aria-expanded", "true");
        return;
      }
      body.classList.remove("nav-open");
      toggle.setAttribute("aria-expanded", "false");
    }

    toggle.addEventListener("click", function () {
      setOpen(!body.classList.contains("nav-open"));
    });
    close.addEventListener("click", function () {
      setOpen(false);
    });
    overlay.addEventListener("click", function () {
      setOpen(false);
    });
    document.querySelectorAll(".nav-link").forEach(function (link) {
      link.addEventListener("click", function () {
        setOpen(false);
      });
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 1120) {
        setOpen(false);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initThemeToggle();
    initNavToggle();
    normalizeHeading();
    markActiveNav();
    initNavGroups();
    addDeleteConfirm();
    addDataConfirm();
  });
})();
