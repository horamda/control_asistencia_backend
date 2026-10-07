(() => {
  const page = document.querySelector('.sh-page, .content-stack');
  if (!page) return;
  const status = document.createElement('div');
  status.className = 'sh-process-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.hidden = true;
  page.prepend(status);
  document.querySelectorAll('.sh-module-nav a').forEach(link => {
    if (new URL(link.href).pathname === location.pathname) link.setAttribute('aria-current', 'page');
  });
  const reset = () => {
    document.querySelectorAll('form[data-sh-busy]').forEach(form => {
      delete form.dataset.shBusy;
      form.removeAttribute('aria-busy');
    });
    status.hidden = true;
  };
  window.addEventListener('pageshow', reset);
  page.addEventListener('submit', event => {
    const form = event.target;
    const action = event.submitter?.formAction || form.action;
    if (new URL(action, location.href).pathname.endsWith('/exportar')) return;
    if (form.dataset.shBusy) { event.preventDefault(); return; }
    form.dataset.shBusy = '1';
    form.setAttribute('aria-busy', 'true');
    status.textContent = form.method.toLowerCase() === 'get'
      ? 'Actualizando resultados…'
      : 'Procesando la solicitud. Esperá la confirmación antes de volver a enviar.';
    status.hidden = false;
  });
  page.querySelectorAll('[data-toggle-year]').forEach(control => {
    control.addEventListener('change', () => {
      const chart = control.closest('.sh-annual-chart');
      const checked = chart.querySelectorAll('[data-toggle-year]:checked');
      const message = chart.querySelector('.sh-year-status');
      if (!checked.length) {
        control.checked = true;
        message.textContent = 'Mantené al menos un año visible para comparar.';
        return;
      }
      chart.querySelectorAll('[data-series-year]').forEach(mark => {
        if (mark.dataset.seriesYear === control.dataset.toggleYear) mark.hidden = !control.checked;
      });
      message.textContent = 'Años visibles: ' + [...checked].map(item => item.dataset.toggleYear).join(', ');
    });
  });
})();
