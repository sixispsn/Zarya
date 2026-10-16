/* Local copy only: no import, merge, validation or server revision upgrade. */
(() => {
  'use strict';
  function create(draft,payload) {
    if(!draft?.project_id || !Number.isSafeInteger(draft.revision) || draft.revision<0
      || payload?.revision!==draft.revision || !payload.answers || Array.isArray(payload.answers)
      || typeof payload.answers!=='object') throw new Error('Нет согласованного снимка ввода.');
    const fields=new Map(draft.fields.map(row=>[row.key,row]));
    const keys=Object.keys(payload.answers);
    if(keys.some(key=>!fields.has(key))) throw new Error('Неизвестное поле копии ввода.');
    const presets=payload.preset_keys || [];
    if(!Array.isArray(presets) || presets.some(key=>!keys.includes(key))) throw new Error('Некорректные отметки типового ввода.');
    // Detached JSON preserves raw strings, false, null and obsolete choices.
    // Only edited fields and their baseline values; no documents or results.
    return JSON.parse(JSON.stringify({format:'zarya-unsaved-input',version:1,
      notice:'Несохранённый ввод для ручной сверки. Не проект, не результат расчёта и не файл автоматического импорта.',
      project_id:draft.project_id,base_revision:draft.revision,
      answers:payload.answers,preset_keys:presets,
      base_fields:keys.map(key=>({key,value:fields.get(key).value,status:fields.get(key).status}))}));
  }
  window.ZaryaInputRecovery={create};
})();
