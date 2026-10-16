(() => {
  'use strict';
  let busy = false, pending = null;
  async function choose(values) {
    if (busy) return; busy = true;
    const error = document.querySelector('[data-project-error]'); error.textContent = '';
    const intent = JSON.stringify(values);
    if (!pending || pending.intent !== intent) pending = {intent,id:crypto.randomUUID().replaceAll('-','')};
    try {
      const r = await fetch('/studio/api/projects',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Zarya-Studio':'1'},body:JSON.stringify({...values,request_id:pending.id})});
      const result = await r.json();
      if (!r.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Не удалось открыть проект.');
      location.assign('/studio?view=project');
    } catch(e) { error.textContent = e instanceof TypeError ? 'Связь прервалась. Повторите действие.' : e.message; }
    finally { busy = false; }
  }
  document.querySelector('#studio-new-project')?.addEventListener('submit', event => {event.preventDefault(); choose({title:String(new FormData(event.currentTarget).get('title')).trim()});});
  document.querySelectorAll('[data-open-project]').forEach(button => button.addEventListener('click',()=>choose({project_id:button.dataset.openProject})));
})();
