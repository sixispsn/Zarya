/* Upload only explicitly chosen files; never collects the working draft's PDFs. */
(() => {
  'use strict';
  const dialog=document.getElementById('pilot-attachment');if(!dialog)return;
  const form=dialog.querySelector('form'),error=dialog.querySelector('[data-bundle-error]');
  const submit=form.querySelector('[type="submit"]'),progress=form.querySelector('[data-bundle-progress]');
  let busy=false,pending=null;
  const showError=text=>{error.textContent=text;error.hidden=!text;};
  const controls=()=>{
    dialog.setAttribute('aria-busy',String(busy));
    form.querySelectorAll('input,textarea').forEach(el=>{el.disabled=busy||!!pending;});
    submit.disabled=busy;dialog.querySelector('[data-bundle-close]').disabled=busy;progress.hidden=!busy;
    submit.textContent=pending?'Повторить сохранение':'Сохранить комплект';
  };
  document.querySelector('[data-bundle-open]').addEventListener('click',()=>{
    if(!pending){form.reset();showError('');form.querySelector('[data-bundle-files]').replaceChildren();}
    dialog.showModal();controls();
  });
  dialog.querySelector('[data-bundle-close]').addEventListener('click',()=>{if(!busy)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  window.addEventListener('beforeunload',event=>{if(busy||pending){event.preventDefault();event.returnValue='';}});
  form.elements.files.addEventListener('change',()=>{
    const list=form.querySelector('[data-bundle-files]');list.replaceChildren();
    Array.from(form.elements.files.files).forEach(file=>{const li=document.createElement('li');const size=file.size<1048576?`${Math.ceil(file.size/1024)} КБ`:`${(file.size/1048576).toFixed(1)} МБ`;li.textContent=`${file.name} · ${size}`;list.append(li);});
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;showError('');
    if(!pending){
      const files=Array.from(form.elements.files.files);
      if(!files.length||files.length>10||files.some(f=>f.size>20*1048576)||files.reduce((n,f)=>n+f.size,0)>40*1048576){showError('Выберите от 1 до 10 PDF: до 20 МБ на файл и 40 МБ всего.');return;}
      if(files.some(f=>!f.name.toLowerCase().endsWith('.pdf'))){showError('Можно прикрепить только PDF.');return;}
      pending={files,metadata:{object_id:dialog.dataset.objectId,version:Number(dialog.dataset.version),
        request_id:crypto.randomUUID().replaceAll('-',''),expertise_ref:form.elements.expertise_ref.value.trim(),
        note:form.elements.note.value.trim(),consent:form.elements.consent.checked,expertise_declared:form.elements.expertise_declared.checked}};
    }
    const body=new FormData();body.append('metadata',JSON.stringify(pending.metadata));
    pending.files.forEach(f=>body.append('files',f));
    busy=true;controls();const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),150000);
    try{
      const response=await fetch('/studio/api/pilot-attachments',{method:'POST',credentials:'same-origin',headers:{'X-Zarya-Studio':'1'},body,signal:controller.signal});
      const data=await response.json().catch(()=>({}));
      if(!response.ok){const e=new Error(typeof data.detail==='string'?data.detail:'Не удалось прикрепить комплект.');e.status=response.status;throw e;}
      if(!/^[a-f0-9]{32}$/.test(data.bundle_id)||data.object_id!==pending.metadata.object_id||data.version!==pending.metadata.version)throw new Error('Нет квитанции');
      pending=null;busy=false;location.assign(`/studio/pilot-objects/${data.object_id}/versions/${data.version}#bundle-${data.bundle_id}`);location.reload();
    }catch(e){
      if(e.status&&e.status<500){pending=null;showError(e.message);}
      else showError('Ответ не получен. Повторите сохранение: отправятся те же файлы, без дублирования комплекта.');
    }finally{clearTimeout(timeout);busy=false;controls();}
  });
})();
