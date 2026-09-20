(() => {
  const shell = document.getElementById('notifications-shell');
  if (!shell) return;
  const panel = document.getElementById('notifications-panel');
  const toggle = document.getElementById('notifications-toggle');
  let loading = false;
  async function load() {
    if (loading) return;
    loading = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(shell.dataset.notificationsUrl, {
        credentials: 'same-origin', signal: controller.signal,
        headers: {Accept: 'application/json'}, cache: 'no-store'
      });
      if (!response.ok) throw new Error('alerts unavailable');
      const data = await response.json();
      // This HTML is rendered by the authenticated same-origin Jinja endpoint.
      panel.innerHTML = data.html;
      toggle.classList.toggle('has-alerts', data.total > 0);
      toggle.setAttribute('aria-label', `Alertas pendientes: ${data.total}`);
      let badge = toggle.querySelector('.notifications-badge');
      if (data.total > 0) {
        if (!badge) { badge = document.createElement('span'); badge.className = 'notifications-badge'; toggle.append(badge); }
        badge.textContent = data.total < 100 ? data.total : '99+';
      } else if (badge) badge.remove();
    } catch (_) {
      panel.replaceChildren();
      const message = document.createElement('div');
      message.className = 'notifications-empty';
      message.textContent = 'No se pudieron cargar las alertas. ';
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'btn btn-secondary'; retry.textContent = 'Reintentar';
      retry.addEventListener('click', load);
      message.append(retry); panel.append(message);
    } finally { clearTimeout(timeout); loading = false; }
  }
  // Let the document become visible before starting the secondary request.
  requestAnimationFrame(() => setTimeout(load, 0));
})();
