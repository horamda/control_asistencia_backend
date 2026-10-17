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

// Nuevo comunicado: "Enviar ahora" o "Programar" (frecuencia, dias, fin) y el texto del boton.
(() => {
  const caja = document.querySelector('[data-com-cuando]');
  if (!caja) return;
  const programar = caja.querySelector('[data-com-programar]');
  const frecuencia = caja.querySelector('[data-com-frecuencia]');
  const termina = caja.querySelector('[data-com-termina]');
  const boton = document.querySelector('[data-com-enviar]');

  function actualizar() {
    const elegido = caja.querySelector('[data-com-cuando-opcion]:checked');
    const programado = elegido && elegido.value === 'programar';
    programar.hidden = !programado;
    caja.querySelectorAll('[data-com-frecuencia-show]').forEach((el) => {
      el.hidden = !el.dataset.comFrecuenciaShow.split(' ').includes(frecuencia.value);
    });
    caja.querySelectorAll('[data-com-termina-show]').forEach((el) => {
      el.hidden = el.dataset.comTerminaShow !== termina.value;
    });
    if (!boton) return;
    boton.textContent = programado ? 'Programar comunicado' : 'Enviar comunicado';
    const n = Number(boton.dataset.comEmpleados || 0);
    const empleados = `${n} empleado${n === 1 ? '' : 's'}`;
    boton.dataset.confirm = programado
      ? `¿Programar el comunicado? Hoy le llegaría a ${empleados}; los destinatarios se recalculan en cada envío.`
      : `¿Enviar el comunicado a ${empleados}? Les llega como notificación y queda en su bandeja de la app.`;
  }

  caja.addEventListener('change', actualizar);
  actualizar();
})();

// Configuracion de avisos: los horarios del resumen solo se muestran si se elige "Resumen".
(() => {
  document.querySelectorAll('[data-com-regla]').forEach((regla) => {
    const resumen = regla.querySelector('[data-com-resumen]');
    if (!resumen) return;
    const actualizar = () => {
      const elegido = regla.querySelector('[data-com-momento]:checked');
      resumen.hidden = !elegido || elegido.value !== 'resumen';
    };
    regla.addEventListener('change', actualizar);
    actualizar();
  });
})();
