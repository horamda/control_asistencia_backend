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
