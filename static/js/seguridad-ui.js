(() => {
  const page = document.querySelector('.sh-page, .content-stack');
  if (!page) return;
  document.querySelectorAll('.sh-module-nav a').forEach(link => {
    if (new URL(link.href).pathname === location.pathname) link.setAttribute('aria-current', 'page');
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
