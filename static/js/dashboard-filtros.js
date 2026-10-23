/* Filtro empresa/sucursal del inicio: solo muestra las sucursales de la empresa elegida y resume el alcance. */
(function () {
  var empresa = document.getElementById("dashboard-empresa");
  var sucursal = document.getElementById("dashboard-sucursal");
  var resumen = document.getElementById("dashboard-filter-meta");
  if (!empresa || !sucursal) return;

  function filtrarSucursales() {
    var empresaId = String(empresa.value || "");
    var elegida = String(sucursal.value || "");
    var conservar = false;
    var visibles = 0;
    Array.from(sucursal.options).forEach(function (opt) {
      if (!opt.value) return;
      var visible = !empresaId || String(opt.getAttribute("data-empresa-id") || "") === empresaId;
      opt.hidden = !visible;
      opt.disabled = !visible;
      if (visible) visibles += 1;
      if (visible && String(opt.value) === elegida) conservar = true;
    });
    if (!conservar) sucursal.value = "";
    sucursal.disabled = visibles === 0 && !!empresaId;
  }

  function actualizarResumen() {
    if (!resumen) return;
    var e = empresa.value ? empresa.options[empresa.selectedIndex].textContent.trim() : "";
    var s = sucursal.value ? sucursal.options[sucursal.selectedIndex].textContent.trim() : "";
    resumen.textContent = !e && !s ? "Todas las empresas y sucursales."
      : e && !s ? "Empresa: " + e + "."
      : (e ? e + " / " : "") + s + ".";
  }

  empresa.addEventListener("change", function () {
    filtrarSucursales();
    actualizarResumen();
  });
  sucursal.addEventListener("change", actualizarResumen);
  filtrarSucursales();
  actualizarResumen();
})();
