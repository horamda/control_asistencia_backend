// Formulario de reuniones (y de comunicados, que usa el mismo selector de destinatarios):
// campos segun la frecuencia, sector completo que incluye sus puestos, busqueda de personas
// y cobertura en vivo de convocados.
(() => {
  const form = document.querySelector('[data-reu-form]');
  if (!form) return;

  // --- Frecuencia (solo reuniones) ----------------------------------------------
  const frecuencia = form.querySelector('[data-reu-frecuencia]');
  const mensual = form.querySelector('[data-reu-mensual]');
  function toggleFrecuencia() {
    const valor = frecuencia.value;
    form.querySelectorAll('[data-reu-show]').forEach((el) => {
      let visible = el.dataset.reuShow.split(' ').includes(valor);
      if (visible && el.dataset.reuMensualShow) visible = el.dataset.reuMensualShow === mensual.value;
      el.hidden = !visible;
      el.querySelectorAll('input,select').forEach((input) => { input.disabled = !visible; });
    });
  }
  if (frecuencia) {
    frecuencia.addEventListener('change', () => {
      // Diaria: por defecto de lunes a viernes.
      if (frecuencia.value === 'diaria' && !form.querySelector('input[name="dias_semana"]:checked')) {
        form.querySelectorAll('input[name="dias_semana"]').forEach((input) => { input.checked = Number(input.value) < 5; });
      }
      toggleFrecuencia();
    });
    mensual.addEventListener('change', toggleFrecuencia);
    toggleFrecuencia();
  }

  // --- Participantes -----------------------------------------------------------
  const box = form.querySelector('[data-reu-participantes]');
  const output = box.querySelector('[data-reu-coverage]');
  const todos = box.querySelector('[data-reu-todos]');
  const reglas = box.querySelector('[data-reu-reglas]');
  const contador = box.querySelector('[data-reu-personas-count]');
  // Textos de la cobertura: el formulario de comunicados dice "Llega a" en vez de "Convoca a".
  const verbo = box.dataset.reuVerbo || 'Convoca a';
  const vacio = box.dataset.reuVacio || 'Todavía no hay convocados. Elegí toda la empresa, sectores, puestos o personas.';
  const enviar = form.querySelector('[data-reu-enviar]');
  // Comunicados: con "Programar" elegido, la confirmacion habla de programar (ver comunicados.js).
  const programado = form.querySelector('[data-com-cuando-opcion][value="programar"]');
  function confirmar(n) {
    if (!enviar) return;
    const empleados = `${n} empleado${n === 1 ? '' : 's'}`;
    enviar.dataset.confirm = programado && programado.checked
      ? `¿Programar el comunicado? Hoy le llegaría a ${empleados}; los destinatarios se recalculan en cada envío.`
      : `¿Enviar el comunicado a ${empleados}? Les llega como notificación y queda en su bandeja de la app.`;
    enviar.dataset.comEmpleados = String(n);
  }
  let empleados = [];
  try {
    empleados = JSON.parse(box.querySelector('[data-reu-coverage-data]').textContent || '[]');
  } catch (_) { empleados = []; }

  function matches(rule, combo) {
    const [sector, puesto] = rule.split(':');
    const [cSector, cPuesto] = combo.split(':');
    if (!rule.includes(':')) return cSector === rule;  // todo el sector
    return (sector === '' || sector === cSector) && puesto === cPuesto;
  }

  // --- Sedes: lugar y hora solo para las sucursales marcadas ---------------------
  const sedes = [...form.querySelectorAll('[data-reu-sede]')];
  function sedesElegidas() {
    sedes.forEach((sede) => {
      const marcada = sede.querySelector('[data-reu-sede-check]').checked;
      sede.classList.toggle('is-whole', marcada);
      sede.querySelectorAll('.reu-sede-fields input').forEach((input) => { input.disabled = !marcada; });
    });
    return new Set(sedes.map((sede) => sede.querySelector('[data-reu-sede-check]'))
      .filter((input) => input.checked).map((input) => Number(input.value)));
  }
  sedes.forEach((sede) => sede.addEventListener('change', update));

  function update() {
    const sucursales = sedesElegidas();
    const enSede = (e) => !sucursales.size || sucursales.has(e.s);
    const empresa = todos.checked;
    reglas.classList.toggle('is-disabled', empresa);
    box.querySelectorAll('[data-epp-sector]').forEach((sector) => {
      const all = sector.querySelector('[data-epp-sector-all]');
      all.disabled = empresa;
      sector.querySelectorAll('.epp-sector-puestos input').forEach((input) => { input.disabled = empresa || all.checked; });
      sector.classList.toggle('is-whole', all.checked && !empresa);
    });
    reglas.querySelectorAll('.epp-sector:not([data-epp-sector]) input').forEach((input) => { input.disabled = empresa; });
    const rules = [...reglas.querySelectorAll('input[name="regla"]:checked:not(:disabled)')].map((i) => i.value);
    const personas = new Set([...box.querySelectorAll('input[name="empleado"]:checked')].map((i) => Number(i.value)));
    contador.textContent = personas.size ? `${personas.size} elegida${personas.size === 1 ? '' : 's'}` : '';
    // Con sucursales elegidas solo cuentan sus empleados (cada uno va a la de su sucursal).
    const base = empleados.filter(enSede);
    const total = base.length;
    output.classList.remove('is-warning');
    if (empresa) {
      output.textContent = sucursales.size
        ? `${verbo} todos los empleados de las sucursales elegidas: ${total}.`
        : `${verbo} toda la empresa: ${total} empleados.`;
      confirmar(total);
      return;
    }
    const alcance = base.filter((e) => personas.has(e.id)
      || e.c.some((combo) => rules.some((rule) => matches(rule, combo)))).length;
    if (!alcance) {
      output.textContent = vacio;
      output.classList.add('is-warning');
    } else {
      output.textContent = `${verbo} ${alcance} de ${total} empleados${sucursales.size ? ' de las sucursales elegidas' : ''}.`;
    }
    confirmar(alcance);
  }
  box.addEventListener('change', update);

  const buscar = box.querySelector('[data-reu-buscar]');
  buscar.addEventListener('input', () => {
    const texto = buscar.value.trim().toLowerCase();
    box.querySelectorAll('[data-reu-persona]').forEach((label) => {
      label.hidden = Boolean(texto) && !label.dataset.texto.includes(texto);
    });
  });
  // Enter en el buscador no envia el formulario.
  buscar.addEventListener('keydown', (event) => { if (event.key === 'Enter') event.preventDefault(); });
  update();
})();
