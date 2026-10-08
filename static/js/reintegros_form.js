(() => {
  const form = document.getElementById('reintegro-form');
  if (!form) return;
  const list = document.getElementById('reintegro-gastos');
  const add = document.getElementById('agregar-gasto');
  const error = document.getElementById('reintegro-form-error');
  let next = list.children.length;
  const rows = () => [...list.querySelectorAll('[data-expense]')];
  function refresh() {
    let cents = 0;
    rows().forEach((row, i) => {
      row.querySelector('[data-number]').textContent = i + 1;
      const value = row.querySelector('[data-amount]').value;
      if (/^\d+(\.\d{1,2})?$/.test(value)) {
        const [whole, fraction = ''] = value.split('.');
        cents += Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
      }
    });
    document.getElementById('reintegro-total').textContent = new Intl.NumberFormat('es-AR', {style: 'currency', currency: 'ARS'}).format(cents / 100);
    add.disabled = rows().length >= 50;
  }
  add.addEventListener('click', () => {
    if (rows().length >= 50) return;
    const fragment = document.getElementById('reintegro-gasto-template').content.cloneNode(true);
    fragment.querySelectorAll('[name]').forEach(el => el.name = el.name.replace('__key__', String(next)));
    fragment.querySelector('[name="linea"]').value = next++;
    list.append(fragment);
    refresh();
    list.lastElementChild.querySelector('input[type="date"]').focus();
  });
  list.addEventListener('click', e => {
    if (e.target.closest('[data-remove]')) {
      e.target.closest('[data-expense]').remove();
      refresh();
    }
  });
  list.addEventListener('input', refresh);
  form.addEventListener('submit', e => {
    error.textContent = '';
    if (e.submitter?.value === 'borrador') return;
    let bytes = 0;
    for (const row of rows()) {
      const files = [...row.querySelector('input[type="file"]').files];
      const count = files.length + row.querySelectorAll('input[type="checkbox"]:checked').length;
      if (count < 1 || count > 3) error.textContent = 'Cada gasto debe tener entre 1 y 3 comprobantes.';
      for (const file of files) {
        bytes += file.size;
        if (file.size > 5 * 1024 * 1024) error.textContent = 'Cada foto debe pesar como máximo 5 MB.';
      }
    }
    const odometer = form.querySelector('input[name="odometro"]')?.files[0];
    if (odometer) {
      bytes += odometer.size;
      if (odometer.size > 5 * 1024 * 1024) error.textContent = 'La foto del odómetro debe pesar como máximo 5 MB.';
    }
    if (bytes > 27 * 1024 * 1024) error.textContent = 'Los archivos superan los 27 MB por envío.';
    if (error.textContent) { e.preventDefault(); error.scrollIntoView({block: 'center'}); }
  });
  const search = document.getElementById('buscar-empleado');
  if (search) search.addEventListener('input', () => {
    const query = search.value.toLocaleLowerCase();
    [...document.getElementById('reintegro-empleado').options].forEach(option => {
      option.hidden = Boolean(option.value) && !option.selected && !option.text.toLocaleLowerCase().includes(query);
    });
  });
  refresh();
})();
