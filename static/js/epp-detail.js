// Resolucion de un pedido: Aprobar / Menos / Rechazar por articulo, resumen en vivo,
// motivo solo cuando hace falta y boton que dice que va a pasar.
// Sin JS queda el campo numerico de cada articulo (mismo envio al servidor).
(() => {
  const form = document.querySelector('[data-epp-resolution]');
  if (!form) return;
  const lines = [...form.querySelectorAll('[data-epp-line]')];
  const reasonBox = form.querySelector('[data-epp-reason]');
  const reason = form.querySelector('[name="motivo"]');
  const summary = form.querySelector('[data-epp-summary]');
  const submit = form.querySelector('[data-epp-submit]');
  const quick = document.querySelector('[data-epp-quick]');

  lines.forEach((line) => {
    line.querySelector('[data-epp-choice]').hidden = false;
  });
  if (quick) quick.hidden = false;

  function plural(n, uno, varios) { return `${n} ${n === 1 ? uno : varios}`; }

  function update() {
    let todo = 0; let menos = 0; let rechazados = 0;
    lines.forEach((line) => {
      const input = line.querySelector('[data-requested]');
      const pedido = Number(input.dataset.requested);
      const modo = (line.querySelector('input[type=radio]:checked') || {}).value || 'todo';
      const amount = line.querySelector('[data-epp-amount]');
      amount.hidden = modo !== 'menos';
      if (modo === 'todo') input.value = pedido;
      if (modo === 'rechazar') input.value = 0;
      if (modo === 'menos') {
        input.max = Math.max(1, pedido - 1);
        input.min = 1;
        if (Number(input.value) >= pedido || Number(input.value) < 1) input.value = Math.max(1, pedido - 1);
      } else {
        input.min = 0;
        input.max = pedido;
      }
      line.dataset.modo = modo;
      if (modo === 'todo') todo += 1; else if (modo === 'menos') menos += 1; else rechazados += 1;
    });
    const cambios = menos + rechazados;
    reasonBox.hidden = !cambios;
    reason.required = cambios > 0;
    reason.setCustomValidity(cambios && !reason.value.trim() ? 'Contale al solicitante por qué reducís o rechazás.' : '');
    if (!cambios) {
      summary.textContent = 'Se aprueba todo lo solicitado.';
      submit.textContent = 'Aprobar pedido';
      submit.classList.remove('btn-danger');
    } else if (rechazados === lines.length) {
      summary.textContent = 'Se rechaza el pedido completo.';
      submit.textContent = 'Rechazar pedido';
      submit.classList.add('btn-danger');
    } else {
      const partes = [];
      if (todo) partes.push(`${plural(todo, 'artículo', 'artículos')} completo${todo === 1 ? '' : 's'}`);
      if (menos) partes.push(`${plural(menos, 'artículo', 'artículos')} con menos unidades`);
      if (rechazados) partes.push(`${plural(rechazados, 'rechazado', 'rechazados')}`);
      summary.textContent = `Se aprueba con cambios: ${partes.join(', ')}.`;
      submit.textContent = 'Aprobar con cambios';
      submit.classList.remove('btn-danger');
    }
  }

  form.addEventListener('change', update);
  form.addEventListener('input', update);
  if (quick) {
    quick.addEventListener('click', (event) => {
      const button = event.target.closest('[data-epp-all]');
      if (!button) return;
      lines.forEach((line) => {
        const radio = line.querySelector(`input[type=radio][value="${button.dataset.eppAll}"]`);
        if (radio) radio.checked = true;
      });
      update();
      if (button.dataset.eppAll === 'rechazar') reason.focus();
    });
  }
  update();
})();

// Entrega: el boton muestra cuantas unidades se registran.
(() => {
  const form = document.querySelector('[data-epp-delivery]');
  if (!form) return;
  const inputs = [...form.querySelectorAll('[data-epp-deliver]')];
  const submit = form.querySelector('[data-epp-deliver-submit]');
  function update() {
    const total = inputs.reduce((acc, input) => acc + (Number(input.value) || 0), 0);
    submit.textContent = total ? `Registrar entrega de ${total} unidad${total === 1 ? '' : 'es'}` : 'Indicá qué se entrega';
    submit.disabled = total === 0;
  }
  form.addEventListener('input', update);
  update();
})();
