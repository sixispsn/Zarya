/* Navigation only: never changes project inputs or calculation results. */
(() => {
  'use strict';
  const path = location.pathname;
  const page = path === '/studio' && new URLSearchParams(location.search).get('view') === 'project' ? 'studio'
    : path === '/studio/projects' || path === '/wizard/projects' ? 'projects'
    : path.startsWith('/wizard/building-model') ? 'building'
    : path.startsWith('/wizard/architecture') ? 'architecture'
    : path.startsWith('/wizard/analyze') ? 'analysis'
    : path.startsWith('/wizard/normatives') ? 'normatives'
    : path === '/wizard' || path.startsWith('/wizard/open/') ? 'editor' : null;
  document.querySelector(`[data-site-page="${page}"]`)?.setAttribute('aria-current', 'page');
  const menu = document.querySelector('.site-tools');
  document.addEventListener('click', event => {
    if (menu?.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu?.open) {
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });
  document.addEventListener('submit', event => {
    const form = event.target.closest('[data-confirm-delete]');
    if (form && !window.confirm(`Удалить проект «${form.dataset.confirmDelete}»?`)) event.preventDefault();
  });
  // Status is read only when the optional menu is opened, not on the white start.
  let radarLoaded = false;
  menu?.addEventListener('toggle', async () => {
    if (!menu.open || radarLoaded) return;
    radarLoaded = true;
    const link = menu.querySelector('[data-site-radar]');
    try {
      const response = await fetch('/wizard/normatives/status.json');
      if (!response.ok) throw new Error('radar');
      const data = await response.json();
      const state = ['green','orange','red'].includes(data.overall_indicator) ? data.overall_indicator : 'gray';
      link.querySelector('i').dataset.state = state;
      link.title = {green:'Проверенные редакции актуальны',orange:'Есть изменения — требуется анализ',red:'Есть нормативные ограничения',gray:'Статус требует проверки'}[state];
    } catch (_) { link.title = 'Статус нормативов временно недоступен'; radarLoaded = false; }
  });
  // A browser-private Studio draft is distinct from the shared YAML project library.
  const current = document.querySelector('[data-library-current]');
  if (current) fetch('/studio/api/draft', {cache:'no-store'})
    .then(response => response.ok ? response.json() : null)
    .then(draft => {
      if (!draft || draft.draft === null) return;
      const title = draft.fields?.find(field => field.key === 'object_name' && field.status === 'confirmed')?.value;
      if (title) current.querySelector('h2').textContent = title;
      current.querySelector('[data-current-description]').textContent = draft.calculation ? 'Расчёт сохранён · продолжите с того же места' : 'Исходные данные сохраняются автоматически';
      current.hidden = false;
    }).catch(() => { /* Existing saved projects remain available if Studio is off. */ });
})();
