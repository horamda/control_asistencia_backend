// Nuevo comunicado: vista previa en vivo de como se ve en el celular (con o sin imagen).
// La notificacion de Android la muestra apaisada (2:1); el servidor la arma igual que aca:
// la imagen entera, centrada sobre un fondo desenfocado de ella misma.
(() => {
  const form = document.querySelector('[data-reu-form]');
  const input = form && form.querySelector('[data-com-imagen]');
  const preview = form && form.querySelector('[data-com-preview]');
  if (!input || !preview) return;

  const titulo = form.querySelector('[name="titulo"]');
  const mensaje = form.querySelector('[name="mensaje"]');
  const info = preview.querySelector('[data-com-preview-info]');
  const ayuda = info.textContent;
  let url = null;

  function conImagen(visible) {
    preview.querySelectorAll('[data-com-preview-conimagen]').forEach((el) => { el.hidden = !visible; });
  }

  function textos() {
    const t = titulo.value.trim() || 'Título';
    const m = mensaje.value.trim();
    preview.querySelectorAll('[data-com-preview-titulo]').forEach((el) => { el.textContent = t; });
    preview.querySelectorAll('[data-com-preview-texto]').forEach((el) => { el.textContent = m; });
    preview.querySelectorAll('[data-com-preview-mensaje]').forEach((el) => { el.textContent = m; });
  }

  function avisoTamano(ancho, alto) {
    const partes = [`${ancho} × ${alto} px.`];
    if (ancho < 600) partes.push('Resolución baja: en el celular puede verse borrosa (ideal: 1080 px de ancho).');
    if (alto > ancho * 2) partes.push('Muy alta: en la notificación queda chica; el texto conviene ponerlo en el mensaje.');
    else if (ancho >= alto * 1.8) partes.push('Apaisada: ocupa toda la notificación.');
    else partes.push('En la notificación se ve entera, con fondo desenfocado a los costados.');
    info.textContent = partes.join(' ');
  }

  input.addEventListener('change', () => {
    if (url) URL.revokeObjectURL(url);
    const archivo = input.files && input.files[0];
    if (!archivo) {
      url = null;
      conImagen(false);
      info.textContent = ayuda;
      return;
    }
    url = URL.createObjectURL(archivo);
    preview.querySelectorAll('[data-com-preview-img]').forEach((img) => { img.src = url; });
    preview.querySelectorAll('[data-com-preview-fondo]').forEach((el) => { el.style.backgroundImage = `url("${url}")`; });
    const prueba = new Image();
    prueba.onload = () => avisoTamano(prueba.naturalWidth, prueba.naturalHeight);
    prueba.onerror = () => { info.textContent = 'No se pudo leer la imagen. Probá con un JPG, PNG o WEBP.'; };
    prueba.src = url;
    conImagen(true);
  });
  titulo.addEventListener('input', textos);
  mensaje.addEventListener('input', textos);
  textos();
})();
