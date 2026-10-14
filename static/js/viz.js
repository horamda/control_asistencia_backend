// Tooltip y crosshair de los graficos SVG de templates/_charts.html.
// Delegado en document: funciona igual con el contenido que inserta htmx.
// Los datos salen de data-tooltips del <figure>; el texto se arma con
// textContent (nunca innerHTML).
(function () {
  function readTooltips(figure) {
    if (!figure._vizTooltips) {
      try {
        figure._vizTooltips = JSON.parse(figure.getAttribute("data-tooltips") || "[]");
      } catch (_) {
        figure._vizTooltips = [];
      }
    }
    return figure._vizTooltips;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function show(hit) {
    var figure = hit.closest("figure[data-tooltips]");
    if (!figure) return;
    var data = readTooltips(figure)[Number(hit.getAttribute("data-index"))];
    var tooltip = figure.querySelector(".viz-tooltip");
    if (!data || !tooltip) return;

    tooltip.textContent = "";
    tooltip.appendChild(el("div", "viz-tooltip-title", data.title));
    (data.rows || []).forEach(function (row) {
      var line = el("div", "viz-tooltip-row");
      line.appendChild(el("span", "viz-key viz-" + row.key));
      line.appendChild(el("strong", "", row.value));
      line.appendChild(el("span", "viz-tooltip-name", row.name));
      tooltip.appendChild(line);
    });
    if (data.note) tooltip.appendChild(el("div", "viz-tooltip-note", data.note));

    var svg = hit.ownerSVGElement;
    var crosshair = svg && svg.querySelector(".viz-crosshair");
    if (crosshair && hit.hasAttribute("data-x")) {
      crosshair.setAttribute("x1", hit.getAttribute("data-x"));
      crosshair.setAttribute("x2", hit.getAttribute("data-x"));
      crosshair.setAttribute("visibility", "visible");
    }
    figure.querySelectorAll(".viz-hit.is-active").forEach(function (node) {
      node.classList.remove("is-active");
    });
    hit.classList.add("is-active");

    tooltip.hidden = false;
    var box = figure.getBoundingClientRect();
    var mark = hit.getBoundingClientRect();
    var anchorX = mark.left + mark.width / 2 - box.left;
    var left = anchorX + 14;
    if (left + tooltip.offsetWidth > box.width) left = anchorX - 14 - tooltip.offsetWidth;
    tooltip.style.left = Math.max(0, left) + "px";
    tooltip.style.top = Math.max(0, mark.top - box.top) + "px";
  }

  function hide(hit) {
    var figure = hit.closest("figure[data-tooltips]");
    if (!figure) return;
    var tooltip = figure.querySelector(".viz-tooltip");
    if (tooltip) tooltip.hidden = true;
    var crosshair = hit.ownerSVGElement && hit.ownerSVGElement.querySelector(".viz-crosshair");
    if (crosshair) crosshair.setAttribute("visibility", "hidden");
    hit.classList.remove("is-active");
  }

  function hitFrom(event) {
    return event.target.closest ? event.target.closest(".viz-hit") : null;
  }

  document.addEventListener("pointerover", function (event) {
    var hit = hitFrom(event);
    if (hit) show(hit);
  });
  document.addEventListener("pointerout", function (event) {
    var hit = hitFrom(event);
    if (hit && !(event.relatedTarget && hit.contains(event.relatedTarget))) hide(hit);
  });
  document.addEventListener("focusin", function (event) {
    var hit = hitFrom(event);
    if (hit) show(hit);
  });
  document.addEventListener("focusout", function (event) {
    var hit = hitFrom(event);
    if (hit) hide(hit);
  });
})();
