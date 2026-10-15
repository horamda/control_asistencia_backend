(() => {
  const input = document.getElementById('epp-image-input');
  if (!input) return;
  const preview = document.getElementById('epp-preview');
  const empty = document.getElementById('epp-preview-empty');
  const feedback = document.getElementById('epp-image-feedback');
  const original = preview.getAttribute('src');
  let objectUrl;
  function restore() {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    if (original) preview.src = original;
    else preview.removeAttribute('src');
    preview.hidden = !original;
    empty.hidden = !!original;
  }
  input.addEventListener('change', () => {
    restore();
    input.setCustomValidity('');
    feedback.textContent = '';
    feedback.classList.remove('is-error');
    const file = input.files[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      const message = 'Seleccioná una imagen JPG, PNG o WEBP de hasta 5 MB.';
      input.setCustomValidity(message);
      feedback.textContent = message;
      feedback.classList.add('is-error');
      return;
    }
    objectUrl = URL.createObjectURL(file);
    preview.src = objectUrl;
    preview.hidden = false;
    empty.hidden = true;
    feedback.textContent = 'Vista previa: ' + file.name;
  });
  preview.addEventListener('error', () => {
    if (!objectUrl) return;
    restore();
    const message = 'No se pudo leer la imagen. Elegí otro archivo.';
    input.setCustomValidity(message);
    feedback.textContent = message;
    feedback.classList.add('is-error');
  });
  window.addEventListener('pagehide', () => { if (objectUrl) URL.revokeObjectURL(objectUrl); });
})();

// Disponibilidad por sector + puesto: "todo el sector" incluye sus puestos y
// la cobertura muestra a cuantos empleados alcanza la seleccion actual.
(() => {
  const box = document.querySelector('[data-epp-eligibility]');
  if (!box) return;
  const output = box.querySelector('[data-epp-coverage]');
  let empleados = [];
  try {
    empleados = JSON.parse(box.querySelector('[data-epp-coverage-data]').textContent || '[]');
  } catch (_) { empleados = []; }

  function matches(rule, combo) {
    const [sector, puesto] = rule.split(':');
    const [cSector, cPuesto] = combo.split(':');
    if (!rule.includes(':')) return cSector === rule;  // todo el sector
    return (sector === '' || sector === cSector) && puesto === cPuesto;
  }

  function update() {
    box.querySelectorAll('[data-epp-sector]').forEach((sector) => {
      const all = sector.querySelector('[data-epp-sector-all]').checked;
      sector.querySelectorAll('.epp-sector-puestos input').forEach((input) => { input.disabled = all; });
      sector.classList.toggle('is-whole', all);
    });
    const rules = [...box.querySelectorAll('input[name="habilitacion"]:checked:not(:disabled)')].map((i) => i.value);
    const total = empleados.length;
    output.classList.remove('is-warning');
    if (!rules.length) {
      output.textContent = `Disponible para todos (${total} empleados).`;
      return;
    }
    const alcance = empleados.filter((combos) => combos.some((combo) => rules.some((rule) => matches(rule, combo)))).length;
    if (!alcance) {
      output.textContent = 'Con esta selección no lo puede pedir ningún empleado. Revisá sectores y puestos.';
      output.classList.add('is-warning');
    } else {
      output.textContent = `Alcanza a ${alcance} de ${total} empleados.`;
    }
  }

  box.addEventListener('change', update);
  update();
})();
