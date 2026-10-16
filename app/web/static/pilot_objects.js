/* Explicit sharing only: the server constructs the snapshot after a revision check. */
(() => {
  'use strict';
  const dialog=document.getElementById('pilot-snapshot');
  if(!dialog) return;
  const form=dialog.querySelector('form'), error=dialog.querySelector('[data-snapshot-error]');
  const result=dialog.querySelector('[data-snapshot-result]');
  const submit=form.querySelector('[type="submit"]');
  let loaded=null, busy=false, pending=null, lastObject=null;
  const showError=text=>{error.textContent=text;error.hidden=!text;};
  const target=()=>{
    const existing=!!form.elements.object_id.value;
    form.querySelector('[data-snapshot-title-field]').hidden=existing;
    form.elements.title.required=!existing;
  };
  const controls=()=>{
    dialog.setAttribute('aria-busy',String(busy));
    form.querySelectorAll('input,select,textarea').forEach(e=>{e.disabled=busy || !!pending;});
    submit.disabled=busy;
    dialog.querySelector('[data-snapshot-close]').disabled=busy;
    submit.textContent=pending?'Повторить сохранение':'Сохранить отдельную версию';
  };
  async function request(path,options={}) {
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch('/studio/api/'+path,{credentials:'same-origin',...options,signal:controller.signal,
        headers:{'Content-Type':'application/json','X-Zarya-Studio':'1'}});
      const data=await response.json().catch(()=>({}));
      if(!response.ok) {const e=new Error(typeof data.detail==='string'?data.detail:'Не удалось сохранить версию.');e.status=response.status;throw e;}
      return data;
    } finally {clearTimeout(timeout);}
  }
  async function open() {
    if(busy) return;
    window.ZaryaMotion?.stop();dialog.showModal();
    if(pending) {controls();return;} // Retry the exact request after an uncertain response.
    showError('');result.hidden=true;form.hidden=true;busy=true;controls();
    try {
      loaded=await request('pilot-snapshot');
      const selected=form.elements.object_id.value || lastObject;
      form.elements.object_id.replaceChildren(new Option('Новый объект пилота',''));
      loaded.objects.forEach(row=>form.elements.object_id.add(new Option(`${row.title} · версий ${row.versions}`,row.id)));
      if(loaded.objects.some(row=>row.id===selected)) form.elements.object_id.value=selected;
      form.elements.consent.checked=false;target();
      dialog.querySelector('[data-snapshot-preview]').textContent=JSON.stringify(loaded.snapshot,null,2);
      dialog.querySelector('[data-snapshot-state]').textContent=loaded.snapshot.results.state==='current'
        ?'Сохраним исходные и актуальные численные результаты с их ограничениями.'
        :'Актуального расчёта нет: сохранится только версия исходных. Чтобы добавить результаты, сначала пересчитайте проект.';
      form.hidden=false;
    } catch(e) {showError(e.status?e.message:'Не удалось загрузить данные. Закройте окно и повторите попытку.');}
    finally {busy=false;controls();}
  }
  window.ZaryaPilotObjects=Object.freeze({open});
  form.elements.object_id.addEventListener('change',target);
  dialog.querySelector('[data-snapshot-close]').addEventListener('click',()=>{if(!busy)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy || !loaded) return;
    if(!pending && !form.elements.object_id.value && !form.elements.title.value.trim()) {showError('Укажите название или псевдоним объекта.');return;}
    pending ||= {request_id:crypto.randomUUID().replaceAll('-',''),revision:loaded.revision,snapshot_sha256:loaded.snapshot_sha256,
      object_id:form.elements.object_id.value || null,
      title:form.elements.object_id.value?'':form.elements.title.value.trim(),
      note:form.elements.note.value.trim(),consent:form.elements.consent.checked};
    busy=true;showError('');controls();
    try {
      const saved=await request('pilot-versions',{method:'POST',body:JSON.stringify(pending)});
      if(!/^[a-f0-9]{32}$/.test(saved.object_id) || !Number.isInteger(saved.version) || saved.version<1) throw new Error('Сервер не подтвердил сохранение.');
      lastObject=saved.object_id;pending=null;form.reset();form.hidden=true;result.hidden=false;result.replaceChildren();
      const text=document.createElement('p');text.textContent=`Версия ${saved.version} сохранена отдельно. Она доступна вам и владельцу ЗАРИ.`;
      const link=document.createElement('a');link.href=`/studio/pilot-objects/${saved.object_id}/versions/${saved.version}`;link.textContent='Открыть сохранённую версию →';
      result.append(text,link);result.focus();
    } catch(e) {
      if(e.status && e.status<500) {pending=null;showError(e.message+(e.status===409?' Закройте окно и откройте его снова.':''));}
      else showError('Ответ сервера не получен. Повторите сохранение: отправится тот же запрос, без новой копии.');
    } finally {busy=false;controls();}
  });
})();
