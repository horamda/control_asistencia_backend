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

    // Swipe left to close sidebar on touch devices
    var sidebar = document.getElementById("app-sidebar");
    var touchStartX = 0;
    if (sidebar) {
      sidebar.addEventListener("touchstart", function (e) {
        touchStartX = e.touches[0].clientX;
      }, { passive: true });
      sidebar.addEventListener("touchend", function (e) {
        var dx = e.changedTouches[0].clientX - touchStartX;
        if (dx < -60) setOpen(false);
      }, { passive: true });
    }
  }

  // Auto-dismiss flash messages
  function initFlashMessages() {
    var ok = document.querySelectorAll(".alert-ok");
    ok.forEach(function (el) {
      setTimeout(function () {
        el.style.transition = "opacity 0.5s ease";
        el.style.opacity = "0";
        setTimeout(function () { el.style.display = "none"; }, 520);
      }, 4000);
    });
  }

  // Submit button loading state — prevents double submit
  function initSubmitLoading() {
    document.querySelectorAll("form:not([method='get'])").forEach(function (form) {
      form.addEventListener("submit", function () {
        var btn = form.querySelector("button[type='submit'], input[type='submit']");
        if (!btn || btn.getAttribute("data-loading") === "1") return;
        btn.setAttribute("data-loading", "1");
        btn.setAttribute("disabled", "disabled");
        btn.setAttribute("data-original-text", btn.textContent || btn.value);
        if (btn.tagName.toLowerCase() === "button") {
          btn.textContent = "Guardando\u2026";
        } else {
          btn.value = "Guardando\u2026";
        }
      });
    });
  }

  // Escape key closes sidebar
  function initEscapeKey() {
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && document.body.classList.contains("nav-open")) {
        document.body.classList.remove("nav-open");
        var toggle = document.getElementById("nav-toggle");
        if (toggle) toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  // Collapsible filter form on mobile
  function initFilterToggle() {
    var MOBILE_BP = 760;
    document.querySelectorAll("form[method='get']").forEach(function (form) {
      if (form.closest(".auth-layout")) return;
      if (form.getAttribute("data-filter-bound") === "1") return;
      form.setAttribute("data-filter-bound", "1");

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-secondary filter-toggle-btn";
      btn.setAttribute("aria-expanded", "false");
      btn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/></svg> Filtros';
      form.parentNode.insertBefore(btn, form);

      function isMobile() { return window.innerWidth <= MOBILE_BP; }

      function applyState(forceOpen) {
        if (!isMobile()) {
          form.style.display = "";
          btn.style.display = "none";
          return;
        }
        btn.style.display = "";
        var open = forceOpen !== undefined ? forceOpen : btn.getAttribute("aria-expanded") === "true";
        form.style.display = open ? "" : "none";
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        btn.innerHTML = (open
          ? '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> Cerrar filtros'
          : '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/></svg> Filtros');
      }

      btn.addEventListener("click", function () {
        var nowOpen = btn.getAttribute("aria-expanded") !== "true";
        applyState(nowOpen);
      });

      window.addEventListener("resize", function () { applyState(); });
      applyState(false);
    });
  }

  // Scroll to top when clicking pager links
  function initPagerScroll() {
    document.querySelectorAll(".pager a").forEach(function (a) {
      a.addEventListener("click", function () {
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
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
    initFlashMessages();
    initSubmitLoading();
    initEscapeKey();
    initFilterToggle();
    initPagerScroll();
  });
})();
