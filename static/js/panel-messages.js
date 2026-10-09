(() => {
  const host = document.getElementById('panel-messages');
  const busy = new Map();
  function prepare(message) {
    message.querySelector('[data-dismiss-message]').onclick = () => message.remove();
    if (['success', 'ok'].includes(message.dataset.tone)) {
      let timer;
      const start = () => { clearTimeout(timer); timer = setTimeout(() => message.remove(), 7000); };
      message.addEventListener('mouseenter', () => clearTimeout(timer));
      message.addEventListener('focusin', () => clearTimeout(timer));
      message.addEventListener('mouseleave', start);
      message.addEventListener('focusout', start);
      start();
    }
  }
  function notify(text, tone = 'info') {
    const node = document.createElement('div');
    node.className = 'panel-message'; node.dataset.tone = tone;
    node.setAttribute('role', ['error', 'danger'].includes(tone) ? 'alert' : 'status');
    const title = document.createElement('strong');
    title.textContent = tone === 'success' ? '✓ Confirmación' : tone === 'error' ? '! Error' : 'Información';
    const body = document.createElement('div'); body.textContent = text;
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '×';
    close.dataset.dismissMessage = ''; close.setAttribute('aria-label', 'Cerrar mensaje');
    node.append(title, body, close); host.append(node); prepare(node); return node;
  }
  function reset(form) {
    const state = busy.get(form); if (!state) return;
    clearTimeout(state.timer); state.notice?.remove();
    if (state.button) {
      if (state.button.tagName === 'INPUT') state.button.value = state.text;
      else state.button.innerHTML = state.text;
      state.button.removeAttribute('aria-disabled');
    }
    form.removeAttribute('aria-busy'); busy.delete(form);
  }
  window.PanelUI = {notify, reset};
  host.querySelectorAll('.panel-message').forEach(prepare);
  document.addEventListener('submit', event => {
    if (busy.has(event.target)) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    const form = event.target, button = event.submitter;
    // Existing inline confirmations already explain the specific operation.
    if (form.hasAttribute('onsubmit') || button?.hasAttribute('onclick')) return;
    const message = button?.dataset.confirm || form.dataset.confirm;
    const dangerous = button?.classList.contains('btn-danger') || /\/eliminar(?:\/|$)/.test(form.action);
    if ((message || dangerous) && !window.confirm(message || `¿Confirmás la acción «${button?.textContent.trim() || 'Eliminar registro'}»?`)) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-confirm]');
    if (link && !window.confirm(link.dataset.confirm)) event.preventDefault();
  });
  window.addEventListener('submit', event => {
    const form = event.target, button = event.submitter;
    if (event.defaultPrevented || form.method.toLowerCase() !== 'post' || form.dataset.feedback === 'manual') return;
    if ((button?.formTarget || form.target) === '_blank' || /export|descargar/.test(button?.formAction || form.action)) return;
    const state = {button, text: button?.tagName === 'INPUT' ? button.value : button?.innerHTML};
    busy.set(form, state); form.setAttribute('aria-busy', 'true');
    if (button) {
      // aria-disabled preserves the clicked button's name/value in the submitted payload.
      button.setAttribute('aria-disabled', 'true');
      if (button.tagName !== 'INPUT') button.textContent = 'Procesando…';
    }
    state.timer = setTimeout(() => {
      state.notice = notify('La operación está demorando. No vuelvas a enviarla sin comprobar antes si se guardó. Si el navegador informa un error de conexión, volvé al formulario para revisar los datos.', 'warning');
    }, 15000);
  });
  window.addEventListener('pageshow', () => [...busy.keys()].forEach(reset));
  let errorNumber = 0;
  document.addEventListener('invalid', event => {
    const field = event.target;
    if (!field.form || field.type === 'hidden') return;
    let error = field.parentElement.querySelector(`[data-field-error="${field.dataset.feedbackId || ''}"]`);
    if (!error) {
      field.dataset.feedbackId = `panel-field-${++errorNumber}`;
      error = document.createElement('div'); error.id = field.dataset.feedbackId;
      error.dataset.fieldError = error.id; error.className = 'panel-field-error';
      field.insertAdjacentElement('afterend', error);
      field.setAttribute('aria-describedby', [field.getAttribute('aria-describedby'), error.id].filter(Boolean).join(' '));
    }
    field.setAttribute('aria-invalid', 'true'); error.textContent = field.validationMessage;
  }, true);
  document.addEventListener('input', event => {
    const field = event.target;
    if (!field.dataset.feedbackId || !field.validity.valid) return;
    field.removeAttribute('aria-invalid');
    const error = document.getElementById(field.dataset.feedbackId); if (error) error.textContent = '';
  });
})();
