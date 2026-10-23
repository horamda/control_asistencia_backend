(() => {
  const page = document.querySelector('.sh-page, .content-stack');
  if (!page) return;
  document.querySelectorAll('.sh-module-nav a').forEach(link => {
    if (new URL(link.href).pathname === location.pathname) link.setAttribute('aria-current', 'page');
  });
  // Keep the native select as the submitted value and enhance it with checkboxes.
  page.querySelectorAll('[data-search-select]').forEach(search => {
    if (!search.closest('.sh-report-form')) return;
    const select = page.querySelector('select[name="' + search.dataset.searchSelect + '"]');
    if (!select || !select.multiple) return;
    const original = select.closest('label');
    const group = document.createElement('div');
    group.className = 'sh-person-picker';
    const title = document.createElement('label');
    search.id = 'search-' + select.name;
    title.htmlFor = search.id;
    title.textContent = original.firstChild.textContent.trim();
    const list = document.createElement('div');
    list.className = 'sh-picker-list';
    list.setAttribute('role', 'group');
    list.setAttribute('aria-label', select.getAttribute('aria-label'));
    const count = document.createElement('p');
    count.className = 'sh-picker-count';
    count.setAttribute('aria-live', 'polite');
    const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
    const rows = [...select.options].map(option => {
      const label = document.createElement('label');
      label.className = 'sh-picker-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = option.selected;
      checkbox.addEventListener('change', () => {
        option.selected = checkbox.checked;
        select.dispatchEvent(new Event('change', { bubbles: true }));
        refresh();
      });
      const text = document.createElement('span');
      text.textContent = option.text;
      label.append(checkbox, text);
      list.append(label);
      return { option, label };
    });
    function refresh() {
      const query = normalize(search.value.trim());
      rows.forEach(({ option, label }) => {
        label.hidden = !option.selected && !normalize(option.text).includes(query);
      });
      const visible = rows.filter(row => !row.label.hidden).length;
      count.textContent = select.selectedOptions.length + ' seleccionados · ' + (visible ? visible + ' disponibles' : 'Sin coincidencias');
    }
    original.replaceWith(group);
    select.hidden = true;
    group.append(title, search, select, list, count);
    search.addEventListener('input', refresh);
    refresh();
  });
  page.querySelectorAll('.sh-review-form').forEach(form => {
    const reason = form.querySelector('textarea[name="motivo"]');
    if (!reason || !form.querySelector('[value="rechazado"]')) return;
    reason.addEventListener('input', () => reason.setCustomValidity(''));
    form.addEventListener('submit', event => {
      if (event.submitter?.value === 'rechazado' && !reason.value.trim()) {
        event.preventDefault();
        reason.setCustomValidity('Indicá el motivo para rechazar el reporte.');
        reason.reportValidity();
      }
    });
    form.querySelector('[value="aprobado"]').addEventListener('click', () => reason.setCustomValidity(''));
  });
  // Listado: aprobar varios pendientes de una vez. El boton se habilita y cuenta los marcados.
  const lote = page.querySelector('#sh-aprobar-varios');
  if (lote) {
    const marcas = [...page.querySelectorAll('[data-sh-lote]')];
    const todos = lote.querySelector('[data-sh-marcar-todos]');
    const boton = lote.querySelector('[data-sh-lote-boton]');
    const actualizar = () => {
      const n = marcas.filter(m => m.checked).length;
      boton.disabled = n === 0;
      boton.textContent = n ? 'Aprobar seleccionados (' + n + ')' : 'Aprobar seleccionados';
      todos.checked = n > 0 && n === marcas.length;
      todos.indeterminate = n > 0 && n < marcas.length;
    };
    todos.addEventListener('change', () => { marcas.forEach(m => { m.checked = todos.checked; }); actualizar(); });
    marcas.forEach(m => m.addEventListener('change', actualizar));
    actualizar();
  }
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
