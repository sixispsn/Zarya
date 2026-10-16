(() => {
  'use strict';
  const form = document.querySelector('#pilot-login');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    const key = form.querySelector('#pilot-key');
    const error = document.querySelector('#pilot-error');
    button.disabled = true; error.textContent = '';
    try {
      const response = await fetch('/access/login', {
        method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{'Content-Type':'application/json', 'X-Zarya-Access':'1'},
        body:JSON.stringify({key:key.value.trim(), remember_device:form.querySelector('#pilot-remember').checked})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось войти. Проверьте ключ.');
      key.value = '';
      window.location.replace(data.location === '/access/participation' ? data.location : '/studio');
    } catch (cause) {
      error.textContent = cause instanceof TypeError ? 'Сервер недоступен. Повторите попытку.' : cause.message;
    } finally { button.disabled = false; }
  });
})();
