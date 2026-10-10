(() => {
  const form = document.querySelector('[data-epp-resolution]');
  if (!form) return;
  const quantities = [...form.querySelectorAll('[data-requested]')];
  const reason = form.querySelector('[name="motivo"]');
  const label = form.querySelector('[data-reason-label]');
  function updateReason() {
    const reduced = quantities.some(input => input.value !== '' && Number(input.value) < Number(input.dataset.requested));
    reason.required = reduced;
    reason.setCustomValidity(reduced && !reason.value.trim() ? 'Indicá el motivo de la reducción o del rechazo.' : '');
    label.textContent = reduced ? 'Obligatorio: estás reduciendo o rechazando cantidades.' : 'Obligatorio si reducís cantidades o rechazás artículos.';
  }
  form.addEventListener('input', updateReason);
  updateReason();
})();
