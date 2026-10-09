(() => {
  const form = document.getElementById('epp-order');
  if (!form) return;
  form.addEventListener('submit', event => {
    const items = [...form.querySelectorAll('[data-epp-item]')].filter(row => Number(row.querySelector('[data-quantity]').value) > 0).map(row => ({articulo_id:Number(row.dataset.eppItem),talle:row.querySelector('[data-size]').value,cantidad:Number(row.querySelector('[data-quantity]').value),medidas:row.querySelector('[data-measures]').value}));
    if (!items.length || items.length > 50 || items.some(item => !item.talle)) {
      event.preventDefault();
      document.getElementById('epp-form-error').textContent = 'Seleccione entre 1 y 50 artículos indicando sus cantidades y talles.';
      return;
    }
    document.getElementById('epp-payload').value = JSON.stringify({accion:event.submitter?.value || 'enviar',revision:form.dataset.revision || undefined,envio_id:form.elements.envio_id.value,motivo:form.elements.motivo.value,items});
  });
})();
