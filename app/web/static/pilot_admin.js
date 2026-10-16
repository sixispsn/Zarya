(() => {
  'use strict';
  let busy = false, pending = null;
  const error = document.querySelector('[data-admin-error]');
  async function post(path, data) {
    const r = await fetch(path, {method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Zarya-Access':'1'},body:JSON.stringify(data)});
    const result = await r.json();
    if (!r.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Не удалось сохранить.');
    return result;
  }
  const consent = document.querySelector('#pilot-consent');
  consent?.addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return; busy = true; error.textContent = '';
    try { await post('/access/participation',{accepted:true,version:consent.dataset.version}); location.replace('/studio'); }
    catch (e) { error.textContent = e.message; } finally { busy = false; }
  });
  const dialog = document.querySelector('#admin-key');
  const invitation = document.querySelector('[data-invitation]');
  async function operate(values) {
    if (busy) return; busy = true; error.textContent = '';
    // Keep the ID on a network failure; never silently issue two invitations.
    const intent = JSON.stringify(values);
    if (!pending || pending.intent !== intent) pending = {intent,id:crypto.randomUUID().replaceAll('-','')};
    try {
      const result = await post('/access/admin',{...values,request_id:pending.id});
      pending = null;
      if (result.key) {
        invitation.value = `Приглашаю в закрытую альфу ЗАРИ.\n${location.origin}/access/login\n\nПерсональный ключ:\n${result.key}\n\nВойдите по ключу и подтвердите условия пилота. Не передавайте ключ другим людям.`;
        document.querySelector('[data-copy-state]').textContent = '';
        dialog.showModal();
      } else if (result.repeated && values.operation !== 'revoke') {
        error.textContent = 'Приглашение уже создано, но ключ повторно не показывается. Обновите список и нажмите «Новый ключ» у участника.';
      } else location.reload();
    } catch (e) { error.textContent = e instanceof TypeError ? 'Связь прервалась. Повторите то же действие — дубликат не создастся.' : e.message; }
    finally { busy = false; }
  }
  document.querySelector('#pilot-invite')?.addEventListener('submit', event => {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    operate({operation:'issue',name:String(fields.get('name')).trim(),days:Number(fields.get('days'))});
  });
  document.querySelectorAll('[data-admin-op]').forEach(button => button.addEventListener('click', () => {
    const revoke = button.dataset.adminOp === 'revoke';
    if (confirm(`${revoke ? 'Отозвать доступ' : 'Выпустить новый ключ на 30 дней'}: ${button.dataset.name}? Текущие сеансы будут закрыты, проекты сохранятся.`)) operate({operation:button.dataset.adminOp,user_id:button.dataset.user,days:30});
  }));
  document.querySelector('[data-copy]')?.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(invitation.value); document.querySelector('[data-copy-state]').textContent = 'Скопировано. Передайте лично.'; }
    catch { invitation.focus(); invitation.select(); document.querySelector('[data-copy-state]').textContent = 'Скопируйте выделенный текст вручную.'; }
  });
  document.querySelector('[data-close]')?.addEventListener('click', () => dialog.close());
  dialog?.addEventListener('close', () => { invitation.value = ''; location.reload(); });
  window.addEventListener('pagehide', () => { if (invitation) invitation.value = ''; });
})();
