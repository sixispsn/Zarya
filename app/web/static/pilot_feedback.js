/* Deliberately text-only: never reads project DOM, files, cookies or query strings. */
(() => {
  'use strict';
  const dialog = document.getElementById('pilot-feedback');
  if (!dialog) return;
  const form = dialog.querySelector('form');
  const result = document.getElementById('feedback-result');
  const error = dialog.querySelector('[role="alert"]');
  let busy = false;
  let requestId = null;
  document.querySelector('[data-feedback-open]')?.addEventListener('click', () => {
    if (form.hidden) { form.hidden = false; result.hidden = true; requestId = null; }
    window.ZaryaMotion?.stop();
    dialog.showModal();
    form.elements.message.focus();
  });
  dialog.querySelector('[data-feedback-close]').addEventListener('click', () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    if (form.elements.message.value.trim().length < 10) {
      error.textContent = 'Опишите замечание чуть подробнее: минимум 10 символов.'; error.hidden = false; return;
    }
    requestId ||= crypto.randomUUID().replaceAll('-', '');
    const payload = {request_id: requestId, category: form.elements.category.value, message: form.elements.message.value.trim()};
    busy = true; error.hidden = true;
    dialog.setAttribute('aria-busy', 'true');
    dialog.querySelectorAll('button, select, textarea').forEach(item => { item.disabled = true; });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/access/feedback', {method: 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'X-Zarya-Studio': '1'}, body: JSON.stringify(payload)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось отправить замечание. Повторите позже.');
      if (typeof data.ticket !== 'string') throw new Error('Сервер не подтвердил отправку. Повторите попытку.');
      form.reset(); form.hidden = true; result.hidden = false;
      result.textContent = `Замечание ${data.ticket} сохранено. Спасибо! Владелец увидит его в закрытом списке.`;
      result.focus();
    } catch (cause) {
      error.textContent = cause.name === 'AbortError' || cause instanceof TypeError
        ? 'Связь прервалась. Текст сохранён в этой форме — повторите отправку, дубля не будет.' : cause.message;
      error.hidden = false;
    } finally {
      clearTimeout(timeout); busy = false; dialog.removeAttribute('aria-busy');
      dialog.querySelectorAll('button, select, textarea').forEach(item => { item.disabled = false; });
    }
  });
})();
