// Catalogo: tabla con busqueda/filtros y alta/edicion en un dialogo. Lo usan Conceptos de viaticos,
// Conceptos de reposicion y Categorias de EPP y Catalogos de Seguridad e Higiene.
//
// Marcado (ids fijos, uno por pagina):
//   #concept-create, #concept-search, #concept-filter (estado), #concept-count, #concept-empty(+ -action)
//   filas: <tr data-concept-row data-name data-active [data-<campo>...]>
//   editar: <button data-edit-concept data-id data-name data-active [data-<campo>...]>
//   dialogo: #concept-dialog [data-singular="concepto"] [data-plural="conceptos"] [data-genero="m|f"]
//            #concept-form, #concept-id, #concept-name, #concept-active, #concept-save, #concept-error
//   campos extra: [data-concept-field="<campo>"] (se completa desde data-<campo> del boton Editar)
//                 [data-create-only] / [data-edit-only]: se muestran (y envian) solo al crear / editar
//   filtros extra: <select data-row-filter="<campo>"> filtra por data-<campo> de la fila
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
  const extraFilters = [...document.querySelectorAll('[data-row-filter]')];
  const rows = [...document.querySelectorAll('[data-concept-row]')];
  const singular = dialog.dataset.singular || 'concepto';
  const plural = dialog.dataset.plural || 'conceptos';
  const nuevo = dialog.dataset.genero === 'f' ? 'Nueva' : 'Nuevo';
  const crear = `Crear ${singular}`;
  const normalize = value => (value || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase().trim();

  function setMode(editing) {
    form.querySelectorAll('[data-create-only]').forEach(el => {
      el.hidden = editing;
      el.querySelectorAll('input,select,textarea').forEach(input => { input.disabled = editing; });
    });
    form.querySelectorAll('[data-edit-only]').forEach(el => {
      el.hidden = !editing;
      el.querySelectorAll('input,select,textarea').forEach(input => { input.disabled = !editing; });
    });
  }

  function open(button) {
    form.reset();
    id.value = button?.dataset.id || '';
    name.value = button?.dataset.name || '';
    active.value = button?.dataset.active || '1';
    form.querySelectorAll('[data-concept-field]').forEach(field => {
      const value = button?.dataset[field.dataset.conceptField];
      if (value !== undefined) field.value = value;
    });
    setMode(Boolean(id.value));
    error.hidden = true;
    name.setCustomValidity('');
    document.getElementById('concept-dialog-title').textContent = id.value ? `Editar ${singular}` : `${nuevo} ${singular}`;
    save.textContent = id.value ? 'Guardar cambios' : crear;
    save.disabled = false;
    dialog.showModal();
    name.focus();
  }

  document.getElementById('concept-create')?.addEventListener('click', () => open());
  document.querySelectorAll('[data-edit-concept]').forEach(button => button.addEventListener('click', () => open(button)));
  document.querySelectorAll('[data-close-concept]').forEach(button => button.addEventListener('click', () => dialog.close()));
  name.addEventListener('input', () => name.setCustomValidity(''));
  form.addEventListener('submit', event => {
    name.value = name.value.trim();
    if (!name.value) {
      event.preventDefault();
      name.setCustomValidity(`Ingresá el nombre del ${singular}.`);
      name.reportValidity();
      return;
    }
    save.disabled = true;
    save.textContent = 'Guardando…';
  });

  function update() {
    const query = normalize(search?.value);
    let visible = 0;
    rows.forEach(row => {
      const extra = extraFilters.every(sel => !sel.value || row.dataset[sel.dataset.rowFilter] === sel.value);
      row.hidden = !normalize(row.dataset.name).includes(query)
        || Boolean(filter?.value && row.dataset.active !== filter.value) || !extra;
      if (!row.hidden) visible++;
    });
    const count = document.getElementById('concept-count');
    if (count) count.textContent = `${visible} de ${rows.length} ${plural}`;
    const empty = document.getElementById('concept-empty');
    if (empty) empty.hidden = visible !== 0;
  }
  search?.addEventListener('input', update);
  filter?.addEventListener('change', update);
  extraFilters.forEach(sel => sel.addEventListener('change', update));
  document.getElementById('concept-empty-action')?.addEventListener('click', () => {
    if (!rows.length) return open();
    if (search) search.value = '';
    if (filter) filter.value = '';
    extraFilters.forEach(sel => { sel.value = ''; });
    update();
    search?.focus();
  });
  window.addEventListener('pageshow', () => {
    save.disabled = false;
    save.textContent = id.value ? 'Guardar cambios' : crear;
  });
  update();
  if (dialog.dataset.reopen === '1') {
    setMode(Boolean(id.value));
    dialog.showModal();
    name.focus();
  }
})();
