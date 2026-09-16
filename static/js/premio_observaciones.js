(function () {
  var field = document.getElementById("premio-observaciones");
  if (!field) return;
  var count = document.getElementById("observaciones-count");
  var status = document.getElementById("observaciones-status");
  var limit = field.maxLength;

  function update() {
    // Match the browser's maxlength counting, including emoji surrogate pairs.
    var used = field.value.length;
    var remaining = Math.max(0, limit - used);
    count.textContent = used.toLocaleString("es-AR") + " / 5.000 caracteres";
    count.classList.toggle("is-near-limit", remaining <= 500);
    var message = used > limit
      ? "El texto supera el límite. Reducilo a 5.000 caracteres para guardar."
      : remaining === 0
        ? "Llegaste al límite de 5.000 caracteres."
        : remaining <= 500 ? "Te quedan " + remaining + " caracteres disponibles." : "";
    if (status.textContent !== message) status.textContent = message;
    field.setCustomValidity(used > limit ? message : "");
  }

  field.addEventListener("input", update);
  window.addEventListener("pageshow", update);
  update();
})();
