(() => {
  const dialog = document.getElementById('concept-dialog');
  if (!dialog) return;
  const form = document.getElementById('concept-form');
  const name = document.getElementById('concept-name');
  const id = document.getElementById('concept-id');
  const active = document.getElementById('concept-active');
  const save = document.getElementById('concept-save');
  const error = document.getElementById('concept-error');
  const search = document.getElementById('concept-search');
  const filter = document.getElementById('concept-filter');
  const rows = [...document.querySelectorAll('[data-concept-row]')];
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim();
  function open(button) {
    form.reset();
    id.value = button?.dataset.id || '';
    name.value = button?.dataset.name || '';
    active.value = button?.dataset.active || '1';
    error.hidden = true;
    name.setCustomValidity('');
    document.getElementById('concept-dialog-title').textContent = id.value ? 'Editar concepto' : 'Nuevo concepto';
    save.textContent = id.value ? 'Guardar cambios' : 'Crear concepto';
    save.disabled = false;
    dialog.showModal();
    name.focus();
  }
  document.getElementById('concept-create').addEventListener('click', () => open());
  document.querySelectorAll('[data-edit-concept]').forEach(button => button.addEventListener('click', () => open(button)));
  document.querySelectorAll('[data-close-concept]').forEach(button => button.addEventListener('click', () => dialog.close()));
  name.addEventListener('input', () => name.setCustomValidity(''));
  form.addEventListener('submit', event => {
    name.value = name.value.trim();
    if (!name.value) {
      event.preventDefault();
      name.setCustomValidity('Ingresá el nombre del concepto.');
      name.reportValidity();
      return;
    }
    save.disabled = true;
    save.textContent = 'Guardando…';
  });
  function update() {
    const query = normalize(search.value);
    let visible = 0;
    rows.forEach(row => {
      row.hidden = !normalize(row.dataset.name).includes(query) || Boolean(filter.value && row.dataset.active !== filter.value);
      if (!row.hidden) visible++;
    });
    document.getElementById('concept-count').textContent = `${visible} de ${rows.length} conceptos`;
    document.getElementById('concept-empty').hidden = visible !== 0;
  }
  search.addEventListener('input', update);
  filter.addEventListener('change', update);
  document.getElementById('concept-empty-action').addEventListener('click', () => {
    if (!rows.length) return open();
    search.value = '';
    filter.value = '';
    update();
    search.focus();
  });
  window.addEventListener('pageshow', () => {
    save.disabled = false;
    save.textContent = id.value ? 'Guardar cambios' : 'Crear concepto';
  });
  update();
  if (dialog.dataset.reopen === '1') {
    dialog.showModal();
    name.focus();
  }
})();
